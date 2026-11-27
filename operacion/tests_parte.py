import io
from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from catalogos.models import Clave, NormaMantenimiento, TipoMantenimiento, TipoOrden, TipoTrabajo

from .informes import generar_informe, generar_parte
from .models import Accion, HojaDeRuta, OrdenServicio
from .parte import CLAVES_DE_FILAS, parte_diario
from .services import (norma_accion, anular_orden, asignar_orden, cerrar_hoja, cerrar_sin_ok, certificar_ok, obtener_orden, pasar_a_brigada,
                       resumen_hoja)
from .reportes import resumen_periodo
from .tests import BaseOperacion, crear_hoja

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

DIA = date(2026, 10, 5)


def a_las(dia, hh, mm=0):
    return timezone.make_aware(datetime(dia.year, dia.month, dia.day, hh, mm))


class ParteBase(BaseOperacion):
    def setUp(self):
        self.hoja_x = self.hoja(fecha=DIA)  # operarios A1-A2
        self.minuto = 0

    def ahora(self):
        self.minuto += 3
        return a_las(self.hoja_x.fecha, 9) + timedelta(minutes=self.minuto)

    def nuevo(self, categoria, n, *, hoja=None, claves=("25-R",), variante="", tipo_orden=None, tipo_mant=None, trabajos=None):
        """Asigna una acción a la hoja (sin cerrarla). Devuelve la acción."""
        hoja = hoja or self.hoja_x
        orden = obtener_orden(
            categoria, self.user, numero_servicio="" if categoria == "ORDEN_TRABAJO" else f"46-{n}",
            tipo_mantenimiento=TipoMantenimiento.objects.get(codigo=tipo_mant) if tipo_mant else None,
            tipo_orden=TipoOrden.objects.get(codigo=tipo_orden) if tipo_orden else None,
            numero_orden=f"{n}" if categoria in ("ORDEN_SERVICIO", "ORDEN_TRABAJO") else "",
            trabajos=trabajos, variante=variante)
        accion = asignar_orden(hoja, orden, self.user, trabajos=trabajos)
        if categoria == "ORDEN_TRABAJO":
            self.anotar(accion)  # cantidad o tipo de cada trabajo: sin ellos no se puede dar el OK
        if accion.es_gabinete:  # sin regletas anotadas no se puede dar el OK
            accion.regletas_sustituidas = 1
            accion.save()
        if categoria != "ORDEN_TRABAJO":
            accion.claves.set(Clave.objects.filter(codigo__in=claves))
        return accion

    def ok(self, accion):
        certificar_ok(accion, self.user, "Cliente", ahora=self.ahora())
        return accion

    def totales(self, fecha=DIA):
        p = parte_diario(fecha)
        return {f["clave"]: f["total"] for g in p["grupos"] for f in g["filas"]} | {"visitadas": p["visitadas"]["total"]}


class FilasDelParteTests(ParteBase):
    def test_correctivos(self):
        self.ok(self.nuevo("CORRECTIVO", 1001))
        self.ok(self.nuevo("CORRECTIVO", 1002, variante="TP"))
        self.ok(self.nuevo("CORRECTIVO", 1003, variante="NHP"))
        cerrar_sin_ok(self.nuevo("CORRECTIVO", 1004, claves=("23",)), self.user, ahora=self.ahora())  # clave de Pendiente de Par
        cerrar_sin_ok(self.nuevo("CORRECTIVO", 1005, claves=("24",)), self.user, ahora=self.ahora())
        cerrar_sin_ok(self.nuevo("CORRECTIVO", 1006, claves=("36",)), self.user, ahora=self.ahora())  # otra causa
        pasar_a_brigada(self.nuevo("CORRECTIVO", 1007, claves=("23",)), self.cable, self.user, ahora=self.ahora())  # pasada: también por claves
        self.nuevo("CORRECTIVO", 1008)  # en curso: todavía no cuenta
        t = self.totales()
        self.assertEqual((t["rep_red"], t["rep_tp"], t["rep_nhp"], t["pend_par"], t["otras_c"]), (1, 1, 1, 3, 1))
        self.assertEqual(t["visitadas"], 7)

    def test_un_correctivo_sin_claves_pero_con_observacion_va_a_otras_causas(self):
        a = self.nuevo("CORRECTIVO", 1010, claves=())
        cerrar_sin_ok(a, self.user, ahora=self.ahora(), observaciones="Cliente ausente")
        self.assertEqual(self.totales()["otras_c"], 1)

    def test_preventivos(self):
        for n, tipo in enumerate(("MPPE", "MPPI", "MPI", "MTP", "GAB"), start=2001):
            self.ok(self.nuevo("PREVENTIVO", n, tipo_mant=tipo))
        cerrar_sin_ok(self.nuevo("PREVENTIVO", 2010, tipo_mant="MPI"), self.user, ahora=self.ahora())
        t = self.totales()
        self.assertEqual((t["mant_red"], t["mant_tp"], t["gabinetes"], t["otras_p"]), (3, 1, 1, 1))

    def test_ordenes_de_servicio(self):
        for n, tipo in enumerate(("A", "TA", "B", "TE", "TI", "AS", "CL", "CMONT", "CMIS", "REC", "CTS", "CVIV", "CD", "CA"), start=3001):
            self.ok(self.nuevo("ORDEN_SERVICIO", n, tipo_orden=tipo))
        self.ok(self.nuevo("ORDEN_SERVICIO", 3100, tipo_orden="A", variante="NH"))  # alta de Nauta Hogar
        anular_orden(self.nuevo("ORDEN_SERVICIO", 3101, tipo_orden="A", claves=()), self.user, ahora=self.ahora())
        cerrar_sin_ok(self.nuevo("ORDEN_SERVICIO", 3102, tipo_orden="B"), self.user, ahora=self.ahora())
        t = self.totales()
        self.assertEqual((t["altas"], t["traslados"], t["bajas"], t["nauta_hogar"], t["te_ti"]), (1, 1, 1, 1, 2))
        self.assertEqual((t["misc"], t["txd"], t["nula"], t["otras_os"]), (5, 4, 1, 1))  # AS CL CMONT CMIS REC | CTS CVIV CD CA

    def test_ordenes_de_trabajo(self):
        poste = TipoTrabajo.objects.get(nombre="Sustitución de poste(s)")
        self.ok(self.nuevo("ORDEN_TRABAJO", 4001, trabajos=[poste]))
        self.nuevo("ORDEN_TRABAJO", 4002, trabajos=[poste])  # en ejecución
        cerrar_sin_ok(self.nuevo("ORDEN_TRABAJO", 4003, trabajos=[poste]), self.user, ahora=self.ahora())  # pendiente de ejecución
        t = self.totales()
        self.assertEqual((t["ot_ok"], t["ot_curso"], t["ot_pend"]), (1, 1, 1))
        self.assertEqual(t["visitadas"], 1)  # las órdenes de trabajo en ejecución o pendientes no son visitas informadas

    def test_lo_no_visitado_no_cuenta_hasta_visitarse(self):
        self.nuevo("CORRECTIVO", 5001)
        cerrar_hoja(self.hoja_x, self.user, ahora=a_las(DIA, 21))  # queda no visitada
        t = self.totales()
        self.assertEqual(sum(v for k, v in t.items() if k in CLAVES_DE_FILAS), 0)

    def test_todas_las_filas_existen_y_las_visitadas_son_la_suma(self):
        self.ok(self.nuevo("CORRECTIVO", 6001))
        self.ok(self.nuevo("PREVENTIVO", 6002, tipo_mant="GAB"))
        p = parte_diario(DIA)
        claves = [f["clave"] for g in p["grupos"] for f in g["filas"]]
        self.assertEqual(claves, CLAVES_DE_FILAS)
        self.assertEqual(p["visitadas"]["valores"], [2])
        self.assertEqual([c["etiqueta"] for c in p["columnas"]], ["A1-A2"])


class AcumuladosYColumnasTests(ParteBase):
    def test_total_del_dia_acumulado_del_mes_y_del_anio(self):
        self.ok(self.nuevo("CORRECTIVO", 7001))
        antes = self.hoja(fecha=DIA - timedelta(days=2), operarios=[self.op1, self.op2])  # mismo mes
        self.ok(self.nuevo("CORRECTIVO", 7002, hoja=antes))
        self.ok(self.nuevo("CORRECTIVO", 7003, hoja=antes))
        anio_pasado = self.hoja(fecha=date(2025, 12, 31), operarios=[self.op1, self.op2])  # otro año: no cuenta
        self.ok(self.nuevo("CORRECTIVO", 7004, hoja=anio_pasado))
        septiembre = self.hoja(fecha=date(2026, 9, 30), operarios=[self.op1, self.op2])  # mismo año, otro mes
        self.ok(self.nuevo("CORRECTIVO", 7005, hoja=septiembre))
        despues = self.hoja(fecha=DIA + timedelta(days=1), operarios=[self.op1, self.op2])  # posterior: no entra en el acumulado de DIA
        self.ok(self.nuevo("CORRECTIVO", 7006, hoja=despues))
        fila = parte_diario(DIA)["grupos"][0]["filas"][0]
        self.assertEqual((fila["total"], fila["mes"], fila["anio"]), (1, 3, 4))

    def test_una_columna_por_hoja_con_las_claves_de_sus_operarios(self):
        otra = crear_hoja(fecha=DIA, brigada=self.cable, centro=self.centro)
        otra.operarios.set([self.op3])
        self.ok(self.nuevo("CORRECTIVO", 7101))
        self.ok(self.nuevo("CORRECTIVO", 7102, hoja=otra))
        self.ok(self.nuevo("CORRECTIVO", 7103, hoja=otra))
        p = parte_diario(DIA)
        etiquetas = {c["etiqueta"]: i for i, c in enumerate(p["columnas"])}
        fila = p["grupos"][0]["filas"][0]
        self.assertEqual((fila["valores"][etiquetas["A1-A2"]], fila["valores"][etiquetas["A3"]], fila["total"]), (1, 2, 3))

    def test_notas_bajo_la_tabla(self):
        self.hoja_x.observaciones = "Cambiando goma, carro ponchado"
        self.hoja_x.save()
        poste = TipoTrabajo.objects.get(nombre="Sustitución de poste(s)")
        a = self.nuevo("ORDEN_TRABAJO", 7201, trabajos=[poste])
        a.descripcion_trabajo = "2 postes cambiados"
        a.save()
        cerrar_sin_ok(self.nuevo("CORRECTIVO", 7202), self.user, ahora=self.ahora(), observaciones="Cita para 15/11")
        texto = parte_diario(DIA)["notas"][0]["texto"]
        for esperado in ("Cambiando goma", "OT 7201", "Sustitución de poste(s)", "2 postes cambiados", "46-7202: Cita para 15/11"):
            self.assertIn(esperado, texto)

    def test_la_brigada_de_linea_informa_con_texto_bajo_la_tabla(self):
        from catalogos.models import Brigada, Operario
        linea, _ = Brigada.objects.update_or_create(nombre="Línea", defaults={"informa_con_texto": True})
        h1 = crear_hoja(fecha=DIA, brigada=linea, centro=self.centro, hora_inicio=time(8, 0))
        h1.operarios.set([self.op3])
        h1.trabajos_realizados = "Se sustituyó el cable de 50 pares por avería urgente"
        h1.save()
        h2 = crear_hoja(fecha=DIA, brigada=linea, centro=self.centro, hora_inicio=time(8, 0))
        h2.operarios.set([Operario.objects.create(clave="A4", nombre="Operario Cuatro", brigada=linea)])
        h2.trabajos_realizados = "Poda en la calle 5ta"
        h2.save()
        self.hoja_x.trabajos_realizados = "no debe salir: su brigada no informa con texto"
        self.hoja_x.save()
        notas = {n["columna"]: n["texto"] for n in parte_diario(DIA)["notas"]}
        self.assertEqual(notas["Brigada de Línea 1 (A3)"], "Se sustituyó el cable de 50 pares por avería urgente")
        self.assertEqual(notas["Brigada de Línea 2 (A4)"], "Poda en la calle 5ta")
        self.assertEqual(len(notas), 2)

    def test_la_api_expone_y_guarda_los_trabajos_de_la_hoja(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        api = APIClient()
        api.force_authenticate(get_user_model().objects.create_superuser("adm9", "a@a.cu", "x"))
        r = api.patch(f"/api/hojas/{self.hoja_x.pk}/", {"trabajos_realizados": "Texto"}, format="json")
        self.assertEqual((r.status_code, r.data["trabajos_realizados"], r.data["informa_con_texto"]), (200, "Texto", False))


class VariantesYNulaTests(ParteBase):
    def test_variantes_validas_por_tipo_de_accion(self):
        with self.assertRaisesMessage(ValidationError, "no corresponde"):
            self.nuevo("PREVENTIVO", 8001, tipo_mant="MPI", variante="TP")
        with self.assertRaisesMessage(ValidationError, "Nauta Hogar (NH) solo corresponde a una orden de servicio de tipo alta"):
            self.nuevo("ORDEN_SERVICIO", 8002, tipo_orden="B", variante="NH")
        with self.assertRaisesMessage(ValidationError, "no corresponde"):
            self.nuevo("CORRECTIVO", 8003, variante="NH")

    def test_anular_solo_ordenes_de_servicio_y_no_cuenta_contra_la_efectividad(self):
        otro_dia = self.hoja(fecha=DIA - timedelta(days=1), operarios=[self.op1, self.op2])
        with self.assertRaisesMessage(ValidationError, "Solo se puede anular una orden de servicio"):
            anular_orden(self.nuevo("CORRECTIVO", 8101, hoja=otro_dia), self.user, ahora=self.ahora())
        self.ok(self.nuevo("ORDEN_SERVICIO", 8102, tipo_orden="A"))
        nula = anular_orden(self.nuevo("ORDEN_SERVICIO", 8103, tipo_orden="A", claves=()), self.user, ahora=self.ahora())
        self.assertEqual((nula.estado, nula.orden.estado), ("ANULADA", OrdenServicio.Estado.ANULADA))
        r = resumen_hoja(self.hoja_x)
        self.assertEqual((r["resultados"]["anuladas"], r["efectividad_pct"]), (1, 100.0))  # la anulada no baja la efectividad

    def test_una_orden_anulada_no_se_reutiliza(self):
        a = self.nuevo("ORDEN_SERVICIO", 8201, tipo_orden="A", claves=())
        anular_orden(a, self.user, ahora=self.ahora())
        nueva = self.nuevo("ORDEN_SERVICIO", 8201, tipo_orden="A")
        self.assertNotEqual(nueva.orden_id, a.orden_id)


class ParteEnInformesYApiTests(ParteBase):
    def setUp(self):
        super().setUp()
        self.ok(self.nuevo("CORRECTIVO", 9001))
        cerrar_sin_ok(self.nuevo("CORRECTIVO", 9002, claves=("23",)), self.user, ahora=self.ahora())
        self.ok(self.nuevo("ORDEN_SERVICIO", 9003, tipo_orden="A", variante="NH"))

    def test_el_parte_es_un_pdf_propio_y_apaisado(self):
        if pdfplumber is None:
            self.skipTest("pdfplumber no está instalado")
        contenido, tipo, nombre = generar_parte(DIA, "pdf")
        self.assertEqual((tipo, nombre), ("application/pdf", "UDAT_parte_diario_2026-10-05.pdf"))
        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            self.assertTrue(all(p.width > p.height for p in pdf.pages))  # todas las hojas del documento son apaisadas
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
        for esperado in ("Parte diario", "A1-A2", "Correctivo", "Reparadas Red de Abonados", "Pendiente de Par", "Nauta Hogar (NH)",
                         "Visitadas en el día", "Total", "Acum.", "mes", "año"):
            self.assertIn(esperado, texto)
        self.assertIn("Visitadas en el día 3 3 3 3", texto)
        self.assertNotIn("Efectividad", texto)  # el resumen del día es del informe, no del parte

    def test_el_informe_ya_no_trae_el_parte(self):
        if pdfplumber is None:
            self.skipTest("pdfplumber no está instalado")
        with pdfplumber.open(io.BytesIO(generar_informe(DIA, "pdf")[0])) as pdf:
            self.assertTrue(all(p.width < p.height for p in pdf.pages))  # el informe sigue siendo vertical
            self.assertNotIn("Parte diario de Mesa de Prueba", " ".join(p.extract_text() or "" for p in pdf.pages))
        from openpyxl import load_workbook
        self.assertNotIn("Parte diario", load_workbook(io.BytesIO(generar_informe(DIA, "xlsx")[0])).sheetnames)

    def test_el_parte_es_un_excel_propio_con_una_sola_hoja(self):
        from openpyxl import load_workbook
        contenido, _, nombre = generar_parte(DIA, "xlsx")
        self.assertEqual(nombre, "UDAT_parte_diario_2026-10-05.xlsx")
        libro = load_workbook(io.BytesIO(contenido))
        self.assertEqual(libro.sheetnames, ["Parte diario"])
        ws = libro["Parte diario"]
        filas = {ws.cell(r, 1).value: [ws.cell(r, c).value for c in range(2, 6)] for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value}
        self.assertEqual(filas["Reparadas Red de Abonados"], [1, 1, 1, 1])  # A1-A2, total, mes, año
        self.assertEqual(filas["Visitadas en el día"], [3, 3, 3, 3])
        self.assertEqual([ws.cell(3, c).value for c in range(2, 6)], ["A1-A2", "Total", "Acumulado mes", "Acumulado año"])
        self.assertEqual(ws.page_setup.orientation, "landscape")

    def test_un_dia_sin_hojas_da_un_parte_con_el_aviso(self):
        if pdfplumber is None:
            self.skipTest("pdfplumber no está instalado")
        with pdfplumber.open(io.BytesIO(generar_parte(date(2026, 1, 2), "pdf")[0])) as pdf:
            self.assertIn("No hay hojas de ruta para este día", pdf.pages[0].extract_text())
        self.assertEqual(generar_parte(date(2026, 1, 2), "xlsx")[2], "UDAT_parte_diario_2026-01-02.xlsx")

    def test_endpoint_del_parte(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        jefe = get_user_model().objects.create_superuser("admin", "a@a.cu", "x")
        api = APIClient()
        api.force_authenticate(jefe)
        r = api.get(f"/api/parte-diario/?fecha={DIA}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c["etiqueta"] for c in r.data["columnas"]], ["A1-A2"])
        self.assertEqual(r.data["visitadas"]["total"], 3)
        self.assertEqual(api.get("/api/parte-diario/?fecha=2026-13-45").status_code, 400)

    def test_descarga_del_parte_por_la_api(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        api = APIClient()
        api.force_authenticate(get_user_model().objects.create_superuser("admin3", "a@a.cu", "x"))
        r = api.get(f"/api/parte-diario/?fecha={DIA}&formato=pdf")
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "application/pdf"))
        self.assertEqual(r["Content-Disposition"], 'inline; filename="UDAT_parte_diario_2026-10-05.pdf"')
        self.assertTrue(r.content.startswith(b"%PDF"))
        r = api.get(f"/api/parte-diario/?fecha={DIA}&formato=xlsx")
        self.assertEqual(r["Content-Disposition"], 'attachment; filename="UDAT_parte_diario_2026-10-05.xlsx"')
        self.assertTrue(r.content.startswith(b"PK"))
        self.assertEqual(api.get(f"/api/parte-diario/?fecha={DIA}&formato=doc").status_code, 400)


class NormasPorTipoTests(ParteBase):
    def test_normas_del_documento_de_normas_de_tiempo(self):
        from catalogos.models import NormaMantenimiento, NormaTipoOrden
        ordenes = {n.tipo_orden.codigo: n.minutos for n in NormaTipoOrden.objects.all()}
        self.assertEqual(ordenes, {"A": 50, "AS": 25, "CL": 25, "B": 35, "TA": 50, "TE": 50, "TI": 50, "REC": 25, "CMIS": 25, "AE": 50,
                                   "CA": 30, "CVIV": 30, "CTS": 30, "CD": 30})
        self.assertEqual({n.tipo_mantenimiento.codigo: n.minutos for n in NormaMantenimiento.objects.all()},
                         {"MPI": 55, "MPPI": 25, "MPPE": 30, "MTP": 25})

    def test_la_norma_de_una_orden_o_un_preventivo_es_la_de_su_tipo_y_no_la_de_sus_claves(self):
        from .services import norma_accion
        self.assertEqual(norma_accion(self.nuevo("ORDEN_SERVICIO", 9501, tipo_orden="B")), 35)
        self.assertEqual(norma_accion(self.nuevo("ORDEN_SERVICIO", 9502, tipo_orden="A", claves=())), 50)  # sin claves también
        self.assertEqual(norma_accion(self.nuevo("PREVENTIVO", 9503, tipo_mant="MPI")), 55)
        self.assertEqual(norma_accion(self.nuevo("PREVENTIVO", 9504, tipo_mant="MTP")), 25)
        self.assertEqual(norma_accion(self.nuevo("CORRECTIVO", 9505)), 45)  # el correctivo sigue normándose por su clave (25-R)

    def test_sin_norma_de_tipo_se_conserva_el_calculo_anterior(self):
        from .services import norma_accion
        cmont = self.nuevo("ORDEN_SERVICIO", 9512, tipo_orden="CMONT", claves=())  # CMONT no viene en el documento
        self.assertIsNone(norma_accion(cmont))
        self.assertIsNone(norma_accion(self.nuevo("PREVENTIVO", 9513, tipo_mant="GAB", claves=())))

    def test_la_productividad_cuenta_el_tiempo_normado_de_las_ordenes_ejecutadas(self):
        from .services import resumen_hoja
        self.ok(self.nuevo("ORDEN_SERVICIO", 9521, tipo_orden="A", claves=()))
        self.assertEqual(resumen_hoja(self.hoja_x)["tiempo_normado_efectivo_min"], 50)

    def test_inicio_avisa_de_los_tipos_sin_norma(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        api = APIClient()
        api.force_authenticate(get_user_model().objects.create_superuser("adm2", "a@a.cu", "x"))
        self.assertEqual(api.get("/api/inicio/").data["catalogos"]["tipos_sin_norma"], ["CMONT", "GAB"])


class GabinetesPorRegletaTests(ParteBase):
    """Cada regleta trabajada (mantenimiento, reparación o sustitución) se norma igual; el parte cuenta regletas, la visita es una."""

    def setUp(self):
        super().setUp()
        gab = TipoMantenimiento.objects.get(codigo="GAB")
        NormaMantenimiento.objects.create(tipo_mantenimiento=gab, minutos=50, vigente_desde=date(2000, 1, 1))

    def gabinete(self, nombre, mantenidas=0, reparadas=0, sustituidas=0):
        orden = obtener_orden("PREVENTIVO", self.user, numero_servicio=nombre, tipo_mantenimiento=TipoMantenimiento.objects.get(codigo="GAB"))
        accion = asignar_orden(self.hoja_x, orden, self.user)
        accion.regletas_mantenidas, accion.regletas_reparadas, accion.regletas_sustituidas = mantenidas, reparadas, sustituidas
        accion.save()
        accion.claves.set(Clave.objects.filter(codigo="25-R"))
        return accion

    def test_se_norma_por_regleta_sea_cual_sea_el_trabajo(self):
        a = self.gabinete("Ger3G", mantenidas=3, reparadas=1, sustituidas=2)
        self.assertEqual((a.regletas, norma_accion(a)), (6, 300))
        self.assertIsNone(norma_accion(self.gabinete("SH1B")))  # sin regletas anotadas no hay tiempo normado (ni se usa el de la clave)

    def test_no_se_da_ok_sin_anotar_las_regletas(self):
        a = self.gabinete("Ger4A")
        with self.assertRaisesMessage(ValidationError, "regletas"):
            certificar_ok(a, self.user, "", ahora=self.ahora())

    def test_el_parte_cuenta_regletas_y_una_sola_visita_por_gabinete(self):
        self.ok(self.gabinete("Ger3G", mantenidas=4, sustituidas=2))
        self.ok(self.gabinete("SI1A", reparadas=1))
        self.ok(self.nuevo("CORRECTIVO", 9901))
        t = self.totales()
        self.assertEqual((t["gabinetes"], t["visitadas"]), (7, 3))
        p = parte_diario(DIA)
        self.assertEqual((p["visitadas"]["valores"], p["visitadas"]["mes"], p["visitadas"]["anio"]), ([3], 3, 3))

    def test_el_resumen_suma_el_tiempo_normado_por_regleta(self):
        self.ok(self.gabinete("Ger2C", sustituidas=4))
        self.assertEqual(resumen_hoja(self.hoja_x)["tiempo_normado_efectivo_min"], 200)
        self.assertEqual(resumen_periodo("mes", DIA)["totales"]["tiempo_normado_min"], 200)

    def test_el_nombre_del_gabinete_es_obligatorio(self):
        with self.assertRaisesMessage(ValidationError, "el nombre del gabinete"):
            obtener_orden("PREVENTIVO", self.user, tipo_mantenimiento=TipoMantenimiento.objects.get(codigo="GAB"))

    def test_por_la_api_las_regletas_solo_van_en_gabinetes(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        api = APIClient()
        api.force_authenticate(get_user_model().objects.create_superuser("adm_gab", "a@a.cu", "x"))
        a = self.gabinete("Ger5B")
        r = api.patch(f"/api/acciones/{a.pk}/", {"regletas_mantenidas": 5}, format="json")
        self.assertEqual((r.status_code, r.data["es_gabinete"], r.data["regletas"], r.data["norma_min"]), (200, True, 5, 250))
        self.assertEqual(api.patch(f"/api/acciones/{a.pk}/", {"regletas_mantenidas": 900}, format="json").status_code, 400)
        correctivo = self.nuevo("CORRECTIVO", 9902)
        r = api.patch(f"/api/acciones/{correctivo.pk}/", {"regletas_reparadas": 2}, format="json")
        self.assertEqual(r.status_code, 400)


class PuntoDeEvaluacionTests(ParteBase):
    def test_se_cumple_desde_el_90_por_ciento(self):
        from .informes import cumple_meta
        self.assertEqual([cumple_meta(v) for v in (None, 89.9, 90, 130)], [None, False, True, True])

    def test_el_informe_marca_la_productividad(self):
        from openpyxl import load_workbook
        self.ok(self.nuevo("CORRECTIVO", 9910))
        ws = load_workbook(io.BytesIO(generar_informe(DIA, "xlsx")[0]))["Resumen"]
        self.assertIn("punto de evaluación 90 %", ws.cell(3, 8).value)
        colores = {c.fill.fgColor.rgb[-6:] for fila in ws.iter_rows() for c in fila if str(c.value).endswith("%") and c.fill.fgColor.rgb}
        self.assertTrue(colores & {"DDF3E4", "FBE0E0"}, colores)
        self.assertTrue(generar_informe(DIA, "pdf")[0].startswith(b"%PDF"))
