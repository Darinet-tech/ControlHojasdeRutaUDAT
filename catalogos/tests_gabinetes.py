"""Catálogo de gabinetes (Excel), selección por el probador y gabinetes que quedan a medias."""
import io
from datetime import date, datetime, time

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from rest_framework.test import APIClient

from operacion.parte import parte_diario
from operacion.reportes import resumen_periodo
from operacion.services import (asignar_orden, avance_gabinete, cerrar_hoja, cerrar_sin_ok, certificar_ok, obtener_orden, resumen_hoja)
from operacion.tests import BaseOperacion

from . import gabinetes_excel
from .models import Clave, Gabinete, NormaMantenimiento, TipoMantenimiento

DIA = date(2026, 10, 5)


def excel(*filas, encabezados=gabinetes_excel.ENCABEZADOS):
    libro = Workbook()
    libro.active.title = "Gabinetes"
    libro.active.append(list(encabezados))
    for fila in filas:
        libro.active.append(list(fila))
    memoria = io.BytesIO()
    libro.save(memoria)
    return memoria.getvalue()


class ImportarGabinetesTests(BaseOperacion):
    def test_crea_y_despues_actualiza_sin_tocar_los_que_no_vienen(self):
        r = gabinetes_excel.importar(excel(["Ger3G", "NG", "3", 5, 10, "Esquina"], ["Ger3G", "NG", "4", 2, 20, ""], ["SH1B", "", "", 12]))
        self.assertEqual((r["creados"], r["actualizados"], r["errores"]), (2, 0, []))
        g = Gabinete.objects.get(nombre="Ger3G")
        self.assertEqual((g.total_regletas, g.centro.codigo, g.observaciones, g.regletas.count()), (7, "NG", "Esquina", 2))
        r = gabinetes_excel.importar(excel(["ger3g", "Nueva Gerona", "3", 9, 10, ""]))  # el nombre no distingue mayúsculas; centro por nombre
        self.assertEqual((r["creados"], r["actualizados"]), (0, 1))
        self.assertEqual((Gabinete.objects.get(nombre="Ger3G").total_regletas, Gabinete.objects.get(nombre="SH1B").total_regletas), (9, 12))

    def test_con_un_error_no_se_guarda_nada_y_se_indica_la_fila(self):
        r = gabinetes_excel.importar(excel(["A1G", "NG", "1", 4, 10], ["A2G", "ZZ", "1", "muchas", 15], ["", "", "2", 1], ["A3G", "", "7"],
                                           ["A1G", "NG", "1", 3, 10]))
        self.assertEqual([e["fila"] for e in r["errores"]], [3, 4, 5, 6])
        texto = " ".join(e["mensaje"] for e in r["errores"]).lower()
        for esperado in ("«zz» no existe", "entre 1 y 500", "8, 10 o 20", "falta el nombre", "indique la cantidad", "fila repetida"):
            self.assertIn(esperado, texto)
        self.assertFalse(Gabinete.objects.exists())

    def test_archivos_que_no_sirven(self):
        for contenido, mensaje in ((b"no es un excel", "No se pudo leer"), (excel(), "no tiene gabinetes"),
                                   (excel(["x"], encabezados=["Nombre"]), "Falta la columna")):
            with self.assertRaisesMessage(ValidationError, mensaje):
                gabinetes_excel.importar(contenido)

    def test_la_plantilla_trae_lo_cargado_y_se_vuelve_a_importar(self):
        gabinetes_excel.importar(excel(["Ger3G", "NG", "3", 5, 10, "Nota"], ["SI1A"]))
        plantilla = gabinetes_excel.plantilla_xlsx()
        libro = load_workbook(io.BytesIO(plantilla))
        self.assertEqual(libro.sheetnames, ["Gabinetes", "Instrucciones"])
        self.assertEqual([c.value for c in libro["Gabinetes"][2]], ["Ger3G", "NG", "3", 5, 10, "Nota"])
        self.assertEqual(gabinetes_excel.importar(plantilla)["actualizados"], 2)

    def test_pantallas_de_la_administracion(self):
        self.client.force_login(get_user_model().objects.create_superuser("adm_g", "a@a.cu", "x"))
        self.assertContains(self.client.get("/admin/catalogos/gabinete/"), "Importar desde Excel")
        r = self.client.get("/admin/catalogos/gabinete/plantilla/")
        self.assertTrue(r.content.startswith(b"PK"))
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = self.client.post("/admin/catalogos/gabinete/importar/", {"archivo": SimpleUploadedFile("g.xlsx", excel(["B1", "ZZ"]))})
        self.assertContains(r, "No se importó nada")
        r = self.client.post("/admin/catalogos/gabinete/importar/", {"archivo": SimpleUploadedFile("g.xlsx", excel(["B1", "NG", "", 3]))})
        self.assertEqual((r.status_code, Gabinete.objects.get().total_regletas), (302, 3))

    def test_sin_permiso_no_se_importa(self):
        usuario = get_user_model().objects.create_user("solo_ve", is_staff=True)
        self.client.force_login(usuario)
        self.assertEqual(self.client.get("/admin/catalogos/gabinete/importar/").status_code, 403)


class GabineteEnLaHojaTests(BaseOperacion):
    def setUp(self):
        self.gab = TipoMantenimiento.objects.get(codigo="GAB")
        NormaMantenimiento.objects.create(tipo_mantenimiento=self.gab, minutos=50, vigente_desde=date(2000, 1, 1))
        self.hoja_x = self.hoja(fecha=DIA)

    def a_las(self, h, m=0):
        return timezone.make_aware(datetime.combine(DIA, time(h, m)))

    def accion(self, nombre, regletas=0, hoja=None):
        orden = obtener_orden("PREVENTIVO", self.user, numero_servicio=nombre, tipo_mantenimiento=self.gab)
        a = asignar_orden(hoja or self.hoja_x, orden, self.user)
        a.regletas_mantenidas = regletas
        a.save()
        return a

    def test_con_catalogo_solo_se_aceptan_sus_gabinetes_y_se_guarda_el_nombre_oficial(self):
        self.assertEqual(self.accion("cualquiera").orden.numero_servicio, "cualquiera")  # sin catálogo cargado no se bloquea el trabajo
        gabinetes_excel.importar(excel(["Ger3G", "NG", "", 20]))
        self.assertEqual(self.accion("ger3g").orden.numero_servicio, "Ger3G")
        with self.assertRaisesMessage(ValidationError, "no está en el catálogo"):
            self.accion("Inventado")

    def test_a_medias_cuenta_las_regletas_el_tiempo_normado_y_el_porcentaje(self):
        gabinetes_excel.importar(excel(["Ger3G", "NG", "", 20]))
        a = self.accion("Ger3G", regletas=6)
        cerrar_sin_ok(a, self.user, ahora=self.a_las(13), observaciones="Se continúa mañana")
        self.assertEqual(avance_gabinete(a), {"trabajadas": 6, "total": 20, "pct": 30})
        p = parte_diario(DIA)
        filas = {f["clave"]: f["total"] for g in p["grupos"] for f in g["filas"]}
        self.assertEqual((filas["gabinetes"], filas["otras_p"], p["visitadas"]["total"]), (6, 0, 1))
        r = resumen_hoja(self.hoja_x)
        self.assertEqual((r["tiempo_normado_efectivo_min"], r["efectividad_pct"]), (300, 0.0))  # trabajo hecho, pero aún no efectivo
        self.assertEqual(resumen_periodo("mes", DIA)["totales"]["tiempo_normado_min"], 300)

        otra = self.hoja(fecha=date(2026, 10, 6))  # al día siguiente se retoma la misma orden y el porcentaje se acumula
        b = self.accion("Ger3G", regletas=14, hoja=otra)
        self.assertEqual(b.orden_id, a.orden_id)
        self.assertEqual(avance_gabinete(b), {"trabajadas": 20, "total": 20, "pct": 100})
        b.claves.set(Clave.objects.filter(codigo="27-G"))
        certificar_ok(b, self.user, "", ahora=timezone.make_aware(datetime(2026, 10, 6, 15, 0)))
        api = APIClient()
        api.force_authenticate(get_user_model().objects.create_superuser("adm_h", "a@a.cu", "x"))
        datos = api.get(f"/api/acciones/{b.pk}/").data
        self.assertEqual((datos["avance_gabinete"]["pct"], datos["visita_anterior"]["regletas"]), (100, 6))
        self.assertEqual(api.get("/api/gabinetes/").data[0]["total_regletas"], 20)

    def test_al_cerrar_la_hoja_un_gabinete_con_regletas_no_queda_como_no_visitado(self):
        a, b = self.accion("SH1B", regletas=3), self.accion("SI1A")
        cerrar_hoja(self.hoja_x, self.user, ahora=self.a_las(14))
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((a.estado, b.estado), ("SIN_OK", "NO_VISITADA"))
        self.assertEqual((a.orden.estado, a.tiempo_real_min), ("SIN_SOLUCION", 360))

    def test_en_el_cierre_automatico_no_se_inventa_el_tiempo_real(self):
        a = self.accion("SH1B", regletas=3)
        cerrar_hoja(self.hoja_x, None, ahora=self.a_las(21))
        a.refresh_from_db()
        self.assertEqual((a.estado, a.tiempo_real_min), ("SIN_OK", None))
        self.assertEqual(resumen_hoja(self.hoja_x)["tiempo_normado_efectivo_min"], 0)
        self.assertEqual({f["clave"]: f["total"] for g in parte_diario(DIA)["grupos"] for f in g["filas"]}["gabinetes"], 3)
