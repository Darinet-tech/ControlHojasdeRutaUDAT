import io
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from openpyxl import Workbook, load_workbook
from rest_framework.test import APIClient

from .importacion import ENCABEZADOS, importar_acciones, leer_filas
from .models import Accion, OrdenServicio
from .services import cambiar_tipo_de_accion, cerrar_hoja
from .tests import BaseOperacion

CSV = """Tipo;Servicio;Tipo de orden;Orden;Mantenimiento;Variante;Centro;Trabajos
Correctivo;46-111111;;;;;;
Correctivo;46-111112;;;;TP;;
Correctivo;46-111113;;;;NH+;;
Preventivo;46-111114;;;MTP;;;
Orden de servicio;46-111115;A;5001;;NH;;
Orden de servicio;46-111116;B;5002;;;;
Orden de trabajo;;;5003;;;;Sustitución de poste(s)
"""


def csv_subido(texto, nombre="acciones.csv"):
    return SimpleUploadedFile(nombre, texto.encode("utf-8"), content_type="text/csv")


class LecturaDelArchivoTests(BaseOperacion):
    def test_lee_un_csv_con_punto_y_coma_y_alias_de_columnas(self):
        filas = leer_filas("a.csv", "TIPO;Número de servicio;Tipo de orden\nC;46-1;\nOS;46-2;A\n;;\n".encode())
        self.assertEqual(filas, [(2, {"tipo": "C", "servicio": "46-1", "tipo_orden": ""}), (3, {"tipo": "OS", "servicio": "46-2", "tipo_orden": "A"})])

    def test_lee_un_excel_y_los_numeros_de_servicio_como_texto(self):
        libro = Workbook()
        hoja = libro.active
        hoja.append(["tipo", "servicio"])
        hoja.append(["Correctivo", 46326407])  # Excel lo guarda como número
        memoria = io.BytesIO()
        libro.save(memoria)
        self.assertEqual(leer_filas("a.xlsx", memoria.getvalue()), [(2, {"tipo": "Correctivo", "servicio": "46326407"})])

    def test_planificacion_diaria_solo_usa_la_columna_servicio(self):
        libro = Workbook()
        hoja = libro.active
        hoja.append([None, "RED PRIMARIA", None, None, "NE"])  # títulos de grupo encima del encabezado
        hoja.append(["SERVICIO", "CABLE", "PAR", "TERM", "NE", "NOMBRE"])
        hoja.append(["46 328758", "24", 140, "NG ED448802", "003-06-187", "CARIDAD"])
        hoja.append(["NG\nED190820", "Ger2A", 64, None, "002-10-232", "EMPRESA"])
        hoja.append(["NGED190856", "Ger4E1", 94, "B5", "002-06-082", "EMPRESA"])
        hoja.append(["11:00 – 02:00 PM"])
        hoja.append([None, None])
        hoja.append([46325311, 2, 46])
        hoja.append(["05:00 – 08:00 PM"])
        memoria = io.BytesIO()
        libro.save(memoria)
        self.assertEqual(leer_filas("plan.xlsx", memoria.getvalue()), [
            (3, {"tipo": "Correctivo", "servicio": "46328758"}), (4, {"tipo": "Correctivo", "servicio": "NGED190820"}),
            (5, {"tipo": "Correctivo", "servicio": "NGED190856"}), (8, {"tipo": "Correctivo", "servicio": "46325311"})])

    def test_archivos_que_no_sirven(self):
        for nombre, contenido, mensaje in [("a.txt", b"x", "Excel (.xlsx) o CSV"), ("a.csv", b"", "vacío"),
                                           ("a.csv", b"orden\n46-1\n", "Falta la columna"), ("a.csv", b"tipo\n", "no tiene filas"),
                                           ("a.xlsx", b"no es un excel", "No se pudo leer")]:
            with self.assertRaisesMessage(ValidationError, mensaje):
                leer_filas(nombre, contenido)


class ImportarAccionesTests(BaseOperacion):
    def setUp(self):
        self.hoja_x = self.hoja(fecha=date(2026, 10, 5))

    def filas(self, texto=CSV):
        return leer_filas("a.csv", texto.encode())

    def test_importa_todos_los_tipos_con_sus_variantes(self):
        r = importar_acciones(self.hoja_x, self.filas(), self.user)
        self.assertEqual((r["filas"], r["validas"], r["importadas"], r["errores"]), (7, 7, 7, []))
        acciones = list(Accion.objects.filter(hoja=self.hoja_x).select_related("orden").order_by("numero"))
        self.assertEqual([a.orden.categoria for a in acciones], ["CORRECTIVO"] * 3 + ["PREVENTIVO", "ORDEN_SERVICIO", "ORDEN_SERVICIO", "ORDEN_TRABAJO"])
        self.assertEqual([a.orden.variante for a in acciones], ["", "TP", "NHP", "", "NH", "", ""])
        self.assertEqual(acciones[3].orden.tipo_mantenimiento.codigo, "MTP")
        self.assertEqual(acciones[6].trabajos.get().nombre, "Sustitución de poste(s)")

    def test_la_simulacion_no_guarda_nada(self):
        r = importar_acciones(self.hoja_x, self.filas(), self.user, simular=True)
        self.assertEqual((r["validas"], r["importadas"], r["simulacion"]), (7, 0, True))
        self.assertFalse(Accion.objects.exists())
        self.assertFalse(OrdenServicio.objects.exists())

    def test_con_algun_error_no_se_importa_ninguna_y_se_informa_de_cada_fila(self):
        texto = ("Tipo;Servicio;Tipo de orden;Orden;Mantenimiento;Variante;Centro;Trabajos\n"
                 "Correctivo;46-222221;;;;;;\n"
                 "Correctivo;;;;;;;\n"                      # falta el servicio
                 "Orden de servicio;46-222223;ZZ;77;;;;\n"  # tipo de orden inexistente
                 "Preventivo;46-222224;;;MPPE;TP;;\n"       # variante que no corresponde
                 "Cosa rara;46-222225;;;;;;\n"              # tipo no válido
                 "Correctivo;46-222226;;;;;XX;\n")          # centro inexistente
        r = importar_acciones(self.hoja_x, self.filas(texto), self.user)
        self.assertEqual((r["validas"], r["importadas"]), (1, 0))
        self.assertEqual([e["fila"] for e in r["errores"]], [3, 4, 5, 6, 7])
        mensajes = {e["fila"]: e["mensaje"] for e in r["errores"]}
        self.assertIn("hay que indicar", mensajes[3])
        self.assertIn("«ZZ» no existe", mensajes[4])
        self.assertIn("no corresponde", mensajes[5])
        self.assertIn("no válido", mensajes[6])
        self.assertIn("centro «XX» no existe", mensajes[7])
        self.assertFalse(Accion.objects.exists())  # todo o nada: ni siquiera la fila buena

    def test_un_servicio_repetido_o_ya_asignado_es_un_error(self):
        r = importar_acciones(self.hoja_x, self.filas("tipo;servicio\nCorrectivo;46-3;\nCorrectivo;46-3\n"), self.user)
        self.assertEqual((r["importadas"], len(r["errores"])), (0, 1))
        self.assertIn("ya está asignado", r["errores"][0]["mensaje"])

    def test_una_hoja_cerrada_no_admite_importar(self):
        cerrar_hoja(self.hoja_x, self.user)
        with self.assertRaisesMessage(ValidationError, "cerrada"):
            importar_acciones(self.hoja_x, self.filas(), self.user)


class ImportarPorLaApiTests(BaseOperacion):
    def setUp(self):
        self.hoja_x = self.hoja(fecha=date(2026, 10, 5))
        self.api = APIClient()
        probador = get_user_model().objects.create_user("probador_imp")
        probador.groups.add(Group.objects.get(name="Probador"))
        self.api.force_authenticate(probador)

    def url(self):
        return f"/api/hojas/{self.hoja_x.pk}/importar/"

    def test_primero_se_comprueba_y_luego_se_importa(self):
        r = self.api.post(self.url(), {"archivo": csv_subido(CSV), "simular": "1"}, format="multipart")
        self.assertEqual((r.status_code, r.data["validas"], r.data["importadas"], r.data["simulacion"]), (200, 7, 0, True))
        self.assertFalse(Accion.objects.exists())
        r = self.api.post(self.url(), {"archivo": csv_subido(CSV), "simular": "0"}, format="multipart")
        self.assertEqual((r.status_code, r.data["importadas"], r.data["errores"]), (200, 7, []))
        self.assertEqual(Accion.objects.filter(hoja=self.hoja_x).count(), 7)

    def test_errores_de_archivo_dan_400(self):
        self.assertEqual(self.api.post(self.url(), {}, format="multipart").status_code, 400)
        r = self.api.post(self.url(), {"archivo": csv_subido("x", "a.txt")}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Excel", str(r.data))

    @override_settings(IMPORTAR_ACCIONES=False)
    def test_se_puede_deshabilitar(self):
        r = self.api.post(self.url(), {"archivo": csv_subido(CSV)}, format="multipart")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Accion.objects.exists())

    def test_el_jefe_no_importa(self):
        jefe = get_user_model().objects.create_user("jefe_imp")
        jefe.groups.add(Group.objects.get(name="Jefe"))
        self.api.force_authenticate(jefe)
        self.assertEqual(self.api.post(self.url(), {"archivo": csv_subido(CSV)}, format="multipart").status_code, 403)

    def test_la_plantilla_se_descarga_y_se_puede_importar(self):
        r = self.api.get("/api/hojas/plantilla-importacion/")
        self.assertEqual(r.status_code, 200)
        libro = load_workbook(io.BytesIO(r.content))
        self.assertEqual(libro.sheetnames, ["Acciones", "Instrucciones"])
        self.assertEqual([c.value for c in libro["Acciones"][1]], ENCABEZADOS)
        subido = SimpleUploadedFile("plantilla.xlsx", r.content)  # la propia plantilla, con sus ejemplos, es válida
        r = self.api.post(self.url(), {"archivo": subido, "simular": "1"}, format="multipart")
        self.assertEqual((r.data["filas"], r.data["errores"]), (5, []))

    def test_la_pantalla_sabe_si_esta_habilitado(self):
        self.assertTrue(self.api.get("/api/auth/me/").data["importar_acciones"])
        with override_settings(IMPORTAR_ACCIONES=False):
            self.assertFalse(self.api.get("/api/auth/me/").data["importar_acciones"])


class CambiarTipoTests(BaseOperacion):
    def setUp(self):
        self.hoja_x = self.hoja(fecha=date(2026, 10, 5))
        self.usuario = get_user_model().objects.create_user("probador_tipo")
        self.usuario.groups.add(Group.objects.get(name="Probador"))
        filas = leer_filas("a.csv", b"servicio\n46 315207\n")
        importar_acciones(self.hoja_x, filas, self.usuario)
        self.accion = Accion.objects.get(hoja=self.hoja_x)

    def test_lo_importado_pasa_a_preventivo_conservando_la_accion(self):
        from catalogos.models import TipoMantenimiento
        numero, pk = self.accion.numero, self.accion.pk
        orden_vieja = self.accion.orden.pk
        mant = TipoMantenimiento.objects.get(codigo="MPI")
        cambiar_tipo_de_accion(self.accion, self.usuario, "PREVENTIVO", mant)
        self.accion.refresh_from_db()
        self.assertEqual((self.accion.pk, self.accion.numero, self.accion.orden.categoria, self.accion.orden.tipo_mantenimiento), (pk, numero, "PREVENTIVO", mant))
        self.assertEqual(self.accion.orden.numero_servicio, "46315207")
        self.assertFalse(OrdenServicio.objects.filter(pk=orden_vieja).exists())  # la orden correctiva se creó solo para esta acción

    def test_un_preventivo_exige_el_tipo_de_mantenimiento(self):
        with self.assertRaisesMessage(ValidationError, "hay que indicar"):
            cambiar_tipo_de_accion(self.accion, self.usuario, "PREVENTIVO")

    def test_cambia_la_variante_de_un_correctivo(self):
        cambiar_tipo_de_accion(self.accion, self.usuario, "CORRECTIVO", variante="TP")
        self.accion.refresh_from_db()
        self.assertEqual(self.accion.orden.variante, "TP")

    def test_no_se_cambia_un_servicio_cerrado_ni_una_hoja_cerrada(self):
        from catalogos.models import TipoMantenimiento
        mant = TipoMantenimiento.objects.get(codigo="MPI")
        cerrar_hoja(self.hoja_x, self.usuario)
        with self.assertRaisesMessage(ValidationError, "cerrada"):
            cambiar_tipo_de_accion(self.accion, self.usuario, "PREVENTIVO", mant)

    def test_por_la_api(self):
        from catalogos.models import TipoMantenimiento
        api = APIClient()
        api.force_authenticate(self.usuario)
        mant = TipoMantenimiento.objects.get(codigo="MPPE")
        r = api.post(f"/api/acciones/{self.accion.pk}/cambiar-tipo/", {"categoria": "PREVENTIVO", "tipo_mantenimiento": mant.pk}, format="json")
        self.assertEqual((r.status_code, r.data["categoria"]), (200, "PREVENTIVO"))
        r = api.post(f"/api/acciones/{self.accion.pk}/cambiar-tipo/", {"categoria": "ORDEN_SERVICIO"}, format="json")
        self.assertEqual(r.status_code, 400)


class SubirExcelPorLaApiTests(BaseOperacion):
    def test_sube_el_excel_de_planificacion_por_la_api(self):
        hoja_x = self.hoja(fecha=date(2026, 10, 5))
        probador = get_user_model().objects.create_user("probador_xl")
        probador.groups.add(Group.objects.get(name="Probador"))
        api = APIClient()
        api.force_authenticate(probador)
        libro = Workbook()
        ws = libro.active
        ws.append(["SERVICIO", "CABLE"])
        ws.append(["46 315207", "24"])
        ws.append(["NG ED190069", "Ger2A"])
        memoria = io.BytesIO()
        libro.save(memoria)
        archivo = SimpleUploadedFile("Planificación Diaria - copia.xlsx", memoria.getvalue(),
                                     content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        r = api.post(f"/api/hojas/{hoja_x.pk}/importar/", {"archivo": archivo}, format="multipart")
        self.assertEqual((r.status_code, r.data["importadas"], r.data["errores"]), (200, 2, []))
        self.assertEqual(sorted(a.orden.numero_servicio for a in Accion.objects.filter(hoja=hoja_x)), ["46315207", "NGED190069"])
