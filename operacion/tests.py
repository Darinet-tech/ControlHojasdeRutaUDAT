from datetime import date, datetime, time

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from io import StringIO

from catalogos.models import Brigada, CausaIncidencia, Centro, Clave, Operario

from .models import Accion, HojaDeRuta, Incidencia, OrdenServicio
from .services import (asignar_no_visitadas, asignar_orden, cerrar_hoja, cerrar_sin_ok, certificar_ok, finalizar_incidencia, historial_servicio,
                       iniciar_incidencia, norma_accion, ordenes_no_visitadas, ordenes_pendientes, pasar_a_brigada,
                       resumen_hoja)

DIA = date(2026, 10, 1)


def crear_hoja(*, centro=None, centros=None, **datos):
    """Crea una hoja de ruta con uno o varios centros."""
    hoja = HojaDeRuta.objects.create(**datos)
    hoja.centros.set(centros if centros is not None else [centro])
    return hoja


def hora(h, m=0):
    return timezone.make_aware(datetime(2026, 10, 1, h, m))


class BaseOperacion(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_inicial", verbosity=0)
        cls.user = get_user_model().objects.create_user("probador1")
        cls.rep = Brigada.objects.get(nombre="Red de Abonados")
        cls.cable = Brigada.objects.get(nombre="Cable")
        cls.centro = Centro.objects.get(codigo="NG")
        cls.op1 = Operario.objects.create(clave="A1", nombre="Operario Uno", brigada=cls.rep)
        cls.op2 = Operario.objects.create(clave="A2", nombre="Operario Dos", brigada=cls.rep)
        cls.op3 = Operario.objects.create(clave="A3", nombre="Operario Tres", brigada=cls.rep)

    def hoja(self, fecha=DIA, operarios=None, inicio=time(8, 0)):
        h = crear_hoja(fecha=fecha, brigada=self.rep, centro=self.centro, hora_inicio=inicio)
        h.operarios.set(operarios or [self.op1, self.op2])
        return h

    def accion(self, hoja, servicio, codigos, numero=1):
        orden, _ = OrdenServicio.objects.get_or_create(numero_servicio=servicio)
        a = Accion.objects.create(hoja=hoja, orden=orden, numero=numero, centro=hoja.centros.first())
        a.claves.set(Clave.objects.filter(codigo__in=codigos))
        return a


class CierreDeAccionesTests(BaseOperacion):
    def test_la_clave_mayor_define_la_norma(self):
        a = self.accion(self.hoja(), "46 326407", ["25-R", "07-IC"])  # 45 y 20 minutos
        self.assertEqual(norma_accion(a), 45)

    def test_ok_requiere_claves_y_cliente(self):
        h = self.hoja()
        with self.assertRaises(ValidationError):
            certificar_ok(self.accion(h, "46 111111", []), self.user, "Cliente")
        with self.assertRaises(ValidationError):
            certificar_ok(self.accion(h, "46 222222", ["25-R"], numero=2), self.user, "  ")

    def test_ok_restablece_la_orden_y_genera_hora_fin(self):
        a = self.accion(self.hoja(), "46 326407", ["25-R", "07-IC"])
        certificar_ok(a, self.user, "Sra. Pérez", ahora=hora(9, 0))
        a.refresh_from_db()
        self.assertTrue(a.ok)
        self.assertEqual(a.certificada_por, self.user)
        self.assertEqual(a.hora_fin, hora(9, 0))
        self.assertEqual(a.orden.estado, OrdenServicio.Estado.RESTABLECIDA)

    def test_tiempo_real_es_fin_menos_fin_de_la_accion_anterior(self):
        h = self.hoja()  # jornada desde las 08:00
        a1 = self.accion(h, "46 000001", ["25-R"], numero=1)
        a2 = self.accion(h, "46 000002", ["23"], numero=2)
        a3 = self.accion(h, "46 000003", ["21-R"], numero=3)
        certificar_ok(a1, self.user, "Cliente", ahora=hora(9, 0))      # 08:00 -> 09:00 = 60
        pasar_a_brigada(a2, self.cable, self.user, ahora=hora(10, 15))  # 09:00 -> 10:15 = 75
        cerrar_sin_ok(a3, self.user, ahora=hora(11, 0))                 # 10:15 -> 11:00 = 45
        self.assertEqual([a.tiempo_real_min for a in (a1, a2, a3)], [60, 75, 45])

    def test_la_jornada_empieza_a_las_08_por_defecto(self):
        h = crear_hoja(fecha=DIA, brigada=self.rep, centro=self.centro)  # sin indicar hora de inicio
        h.operarios.set([self.op1])
        self.assertEqual(h.hora_inicio, time(8, 0))
        a = self.accion(h, "46 000004", ["25-R"])
        certificar_ok(a, self.user, "Cliente", ahora=hora(9, 30))
        self.assertEqual(a.tiempo_real_min, 90)  # 08:00 -> 09:30

    def test_no_se_cierra_dos_veces(self):
        a = self.accion(self.hoja(), "46 000005", ["25-R"])
        certificar_ok(a, self.user, "Cliente", ahora=hora(9, 0))
        with self.assertRaises(ValidationError):
            pasar_a_brigada(a, self.cable, self.user, ahora=hora(9, 30))

    def test_pasar_a_otra_brigada_deja_el_servicio_pendiente_para_esa_brigada(self):
        a = self.accion(self.hoja(), "46 333333", ["23"])
        pasar_a_brigada(a, self.cable, self.user, ahora=hora(9, 0))
        a.refresh_from_db()
        self.assertFalse(a.ok)
        self.assertEqual(a.pasada_a, self.cable)
        self.assertEqual(a.orden.estado, OrdenServicio.Estado.PENDIENTE)
        self.assertIn(a.orden, ordenes_pendientes(self.cable))
        self.assertNotIn(a.orden, ordenes_pendientes(Brigada.objects.get(nombre="Línea")))

    def test_pendiente_asignado_a_una_hoja_abierta_no_se_ofrece_de_nuevo(self):
        a = self.accion(self.hoja(), "46 888888", ["23"])
        pasar_a_brigada(a, self.cable, self.user, ahora=hora(9, 0))
        self.assertEqual(ordenes_pendientes(self.cable).count(), 1)
        hoja_cable = crear_hoja(fecha=DIA, brigada=self.cable, centro=self.centro)
        hoja_cable.operarios.set([self.op3])
        Accion.objects.create(hoja=hoja_cable, orden=a.orden, numero=1)  # se asigna a la hoja de Cable
        self.assertEqual(ordenes_pendientes(self.cable).count(), 0)
        cerrar_hoja(hoja_cable, self.user, ahora=hora(15, 0))  # la hoja se cierra con la acción sin cerrar
        self.assertEqual(ordenes_pendientes(self.cable).count(), 1)  # vuelve a quedar disponible

    def test_resumen_de_hoja(self):
        h = self.hoja()  # 2 operarios -> 840 min disponibles
        a1 = self.accion(h, "46 326407", ["25-R", "07-IC"], numero=1)
        a2 = self.accion(h, "46 444444", ["36"], numero=2)
        certificar_ok(a1, self.user, "Cliente", ahora=hora(9, 0))  # 60 min reales, norma 45
        cerrar_sin_ok(a2, self.user, ahora=hora(9, 30))           # 30 min reales, sin OK
        r = resumen_hoja(h)
        self.assertEqual((r["acciones"], r["efectivas"]), (2, 1))
        self.assertEqual(r["efectividad_pct"], 50.0)
        self.assertEqual(r["tiempo_real_min"], 90)
        self.assertEqual(r["tiempo_normado_efectivo_min"], 45)
        self.assertEqual(r["productividad_pct"], 50.0)
        self.assertEqual(r["tiempo_disponible_min"], 840)
        self.assertEqual(r["ocupacion_pct"], 10.7)

    def test_historial_muestra_que_operarios_trabajaron_el_servicio(self):
        self.accion(self.hoja(date(2026, 10, 1), operarios=[self.op1]), "46 555555", ["25-R"])
        self.accion(self.hoja(date(2026, 10, 3), operarios=[self.op2]), "46 555555", ["25-R"])
        previos = list(historial_servicio("46 555555"))
        self.assertEqual(len(previos), 2)
        self.assertEqual(list(previos[0].hoja.operarios.all()), [self.op1])


class IncidenciasTests(BaseOperacion):
    def setUp(self):
        self.lluvia = CausaIncidencia.objects.get(codigo="100")
        self.transporte = CausaIncidencia.objects.get(codigo="106")

    def test_el_contador_arranca_y_se_detiene_al_confirmar_el_cambio_de_estado(self):
        h = self.hoja()
        inc = iniciar_incidencia(h, self.lluvia, self.user, ahora=hora(9, 0))
        self.assertTrue(inc.activa)
        finalizar_incidencia(h, self.user, ahora=hora(10, 30))
        inc.refresh_from_db()
        self.assertFalse(inc.activa)
        self.assertEqual(inc.minutos(), 90)

    def test_iniciar_otra_incidencia_detiene_la_anterior(self):
        h = self.hoja()
        primera = iniciar_incidencia(h, self.lluvia, self.user, ahora=hora(9, 0))
        iniciar_incidencia(h, self.transporte, self.user, ahora=hora(9, 40))
        primera.refresh_from_db()
        self.assertEqual(primera.minutos(), 40)
        self.assertEqual(h.incidencias.filter(fin__isnull=True).count(), 1)

    def test_cerrar_la_hoja_detiene_el_contador_que_sigue_activo(self):
        h = self.hoja()
        inc = iniciar_incidencia(h, self.lluvia, self.user, ahora=hora(13, 0))
        cerrar_hoja(h, self.user, ahora=hora(15, 0))
        inc.refresh_from_db(); h.refresh_from_db()
        self.assertEqual(inc.fin, hora(15, 0))
        self.assertTrue(h.cerrada)
        self.assertEqual(h.cerrada_por, self.user)

    def test_hoja_cerrada_no_admite_incidencias_ni_cierre_de_acciones(self):
        h = self.hoja()
        a = self.accion(h, "46 700001", ["25-R"])
        cerrar_hoja(h, self.user, ahora=hora(15, 0))
        with self.assertRaises(ValidationError):
            iniciar_incidencia(h, self.lluvia, self.user)
        with self.assertRaises(ValidationError):
            certificar_ok(a, self.user, "Cliente", ahora=hora(15, 5))
        with self.assertRaises(ValidationError):
            cerrar_hoja(h, self.user)

    def test_la_incidencia_se_descuenta_del_tiempo_real_de_la_accion(self):
        h = self.hoja()  # jornada desde las 08:00
        a = self.accion(h, "46 700002", ["25-R"])
        iniciar_incidencia(h, self.lluvia, self.user, ahora=hora(8, 30))
        finalizar_incidencia(h, self.user, ahora=hora(9, 30))      # 60 min de lluvia
        certificar_ok(a, self.user, "Cliente", ahora=hora(10, 0))  # 120 min brutos - 60 = 60
        self.assertEqual(a.tiempo_real_min, 60)

    def test_incidencia_que_no_descuenta_no_se_resta(self):
        CausaIncidencia.objects.filter(pk=self.lluvia.pk).update(descuenta_tiempo=False)
        h = self.hoja()
        a = self.accion(h, "46 700003", ["25-R"])
        iniciar_incidencia(h, self.lluvia, self.user, ahora=hora(8, 30))
        finalizar_incidencia(h, self.user, ahora=hora(9, 30))
        certificar_ok(a, self.user, "Cliente", ahora=hora(10, 0))
        self.assertEqual(a.tiempo_real_min, 120)
        self.assertEqual(resumen_hoja(h, ahora=hora(15, 0))["incidencias_min"], 0)

    def test_resumen_real_con_incidencias(self):
        h = self.hoja()  # 2 operarios
        a = self.accion(h, "46 700004", ["25-R"])
        iniciar_incidencia(h, self.lluvia, self.user, ahora=hora(8, 0))
        finalizar_incidencia(h, self.user, ahora=hora(9, 0))
        iniciar_incidencia(h, self.transporte, self.user, ahora=hora(13, 0))  # sigue activa al consultar
        certificar_ok(a, self.user, "Cliente", ahora=hora(10, 0))              # 120 - 60 = 60 min reales
        r = resumen_hoja(h, ahora=hora(14, 0))                                 # transporte: 60 min activos
        self.assertEqual(r["incidencias_min"], 120)
        self.assertEqual(r["incidencias_por_causa"], {"100 - Lluvia": 60, "106 - Problemas con el transporte": 60})
        self.assertEqual(r["tiempo_disponible_min"], 2 * (420 - 120))
        self.assertEqual(r["ocupacion_pct"], 10.0)  # 60 / 600
        self.assertEqual(r["productividad_pct"], 75.0)  # 45 normados / 60 reales


class PantallaAdminTests(BaseOperacion):
    """Lo que hace el probador desde la administración: registrar la incidencia (arranca el contador),
    finalizarla y cerrar la hoja al terminar el día."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from django.urls import reverse

        self.reverse = reverse
        self.probador = get_user_model().objects.create_user("probador", password="x", is_staff=True)
        self.probador.groups.add(Group.objects.get(name="Probador"))
        self.client.force_login(self.probador)
        self.lluvia = CausaIncidencia.objects.get(codigo="100")

    def post_hoja_con_incidencia(self):
        datos = {
            "fecha": "2026-10-01", "brigada": self.rep.pk, "centros": [self.centro.pk], "hora_inicio": "08:00:00",
            "operarios": [self.op1.pk], "observaciones": "",
            "acciones-TOTAL_FORMS": 0, "acciones-INITIAL_FORMS": 0, "acciones-MIN_NUM_FORMS": 0, "acciones-MAX_NUM_FORMS": 1000,
            "incidencias-TOTAL_FORMS": 1, "incidencias-INITIAL_FORMS": 0, "incidencias-MIN_NUM_FORMS": 0,
            "incidencias-MAX_NUM_FORMS": 1000, "incidencias-0-causa": self.lluvia.pk, "incidencias-0-observaciones": "Aguacero",
        }
        return self.client.post(self.reverse("admin:operacion_hojaderuta_add"), datos)

    def test_registrar_la_incidencia_en_la_hoja_arranca_el_contador(self):
        respuesta = self.post_hoja_con_incidencia()
        self.assertEqual(respuesta.status_code, 302)
        hoja = HojaDeRuta.objects.get()
        incidencia = hoja.incidencias.get()
        self.assertEqual((incidencia.causa, incidencia.fin, incidencia.creado_por), (self.lluvia, None, self.probador))

    def test_acciones_finalizar_incidencia_y_cerrar_hoja(self):
        self.post_hoja_con_incidencia()
        hoja = HojaDeRuta.objects.get()
        url = self.reverse("admin:operacion_hojaderuta_changelist")
        self.client.post(url, {"action": "finalizar_incidencia_en_curso", "_selected_action": [hoja.pk]})
        self.assertIsNotNone(hoja.incidencias.get().fin)
        self.client.post(url, {"action": "cerrar_hojas", "_selected_action": [hoja.pk]})
        hoja.refresh_from_db()
        self.assertTrue(hoja.cerrada)

    def test_cerrar_la_hoja_detiene_la_incidencia_activa(self):
        self.post_hoja_con_incidencia()
        hoja = HojaDeRuta.objects.get()
        self.client.post(self.reverse("admin:operacion_hojaderuta_changelist"),
                         {"action": "cerrar_hojas", "_selected_action": [hoja.pk]})
        self.assertIsNotNone(hoja.incidencias.get().fin)

    def test_el_probador_no_puede_modificar_una_hoja_cerrada(self):
        self.post_hoja_con_incidencia()
        hoja = HojaDeRuta.objects.get()
        cerrar_hoja(hoja, self.probador)
        url = self.reverse("admin:operacion_hojaderuta_change", args=[hoja.pk])
        self.assertEqual(self.client.post(url, {"fecha": "2026-10-02"}).status_code, 403)
        hoja.refresh_from_db()
        self.assertEqual(hoja.fecha, DIA)

    def test_todas_las_pantallas_de_administracion_abren(self):
        from django.contrib import admin

        superusuario = get_user_model().objects.create_superuser("su", "s@s.cu", "x")
        self.client.force_login(superusuario)
        self.post_hoja_con_incidencia()
        for modelo in admin.site._registry:
            base = f"/admin/{modelo._meta.app_label}/{modelo._meta.model_name}/"
            for url in (base, base + "add/"):
                esperado = 403 if url.endswith("informeenviado/add/") else 200  # el registro de envíos es de auditoría: no se crea a mano
                self.assertEqual(self.client.get(url).status_code, esperado, url)
        hoja = HojaDeRuta.objects.get()
        self.assertEqual(self.client.get(self.reverse("admin:operacion_hojaderuta_change", args=[hoja.pk])).status_code, 200)


class UnOperarioUnaHojaPorDiaTests(BaseOperacion):
    def test_el_servicio_rechaza_un_operario_que_ya_esta_en_otra_hoja_ese_dia(self):
        self.hoja(operarios=[self.op1, self.op2])
        otra = crear_hoja(fecha=DIA, brigada=self.cable, centro=self.centro)
        with self.assertRaises(ValidationError) as error:
            with transaction.atomic():
                otra.operarios.set([self.op1, self.op3])
        self.assertIn("Operario Uno ya está en la hoja NG · Red de Abonados", error.exception.messages[0])
        self.assertEqual(otra.operarios.count(), 0)

    def test_en_otro_dia_si_puede_estar(self):
        self.hoja(DIA, operarios=[self.op1])
        otra = crear_hoja(fecha=date(2026, 10, 2), brigada=self.rep, centro=self.centro)
        otra.operarios.set([self.op1])
        self.assertEqual(otra.operarios.count(), 1)

    def test_volver_a_guardar_la_misma_hoja_no_choca_consigo_misma(self):
        h = self.hoja(operarios=[self.op1, self.op2])
        h.operarios.set([self.op1, self.op2, self.op3])  # agrega uno nuevo, conserva los demás
        self.assertEqual(h.operarios.count(), 3)

    def test_tambien_se_controla_agregando_desde_el_operario(self):
        self.hoja(operarios=[self.op1])
        otra = crear_hoja(fecha=DIA, brigada=self.cable, centro=self.centro)
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                self.op1.hojas.add(otra)

    def test_el_formulario_de_la_administracion_lo_rechaza(self):
        from django.urls import reverse

        self.hoja(operarios=[self.op1])
        superusuario = get_user_model().objects.create_superuser("su", "s@s.cu", "x")
        self.client.force_login(superusuario)
        datos = {"fecha": str(DIA), "brigada": self.cable.pk, "centros": [self.centro.pk], "hora_inicio": "08:00:00",
                 "operarios": [self.op1.pk], "observaciones": "",
                 "acciones-TOTAL_FORMS": 0, "acciones-INITIAL_FORMS": 0, "acciones-MIN_NUM_FORMS": 0, "acciones-MAX_NUM_FORMS": 1000,
                 "incidencias-TOTAL_FORMS": 0, "incidencias-INITIAL_FORMS": 0, "incidencias-MIN_NUM_FORMS": 0, "incidencias-MAX_NUM_FORMS": 1000}
        respuesta = self.client.post(reverse("admin:operacion_hojaderuta_add"), datos)
        self.assertEqual(respuesta.status_code, 200)  # vuelve al formulario con el error
        self.assertContains(respuesta, "Operario Uno ya está en la hoja")
        self.assertEqual(HojaDeRuta.objects.count(), 1)

    def test_comando_para_revisar_datos_anteriores_a_la_regla(self):
        h1 = self.hoja(operarios=[self.op1])
        h2 = crear_hoja(fecha=DIA, brigada=self.cable, centro=self.centro)
        salida = StringIO()
        call_command("operarios_duplicados", stdout=salida)
        self.assertIn("No hay operarios repetidos", salida.getvalue())
        HojaDeRuta.operarios.through.objects.create(hojaderuta=h2, operario=self.op1)  # dato viejo, sin pasar por la regla
        salida = StringIO()
        call_command("operarios_duplicados", stdout=salida)
        self.assertIn("Operario Uno", salida.getvalue())
        self.assertIn(f"hoja {h1.pk}", salida.getvalue())


class ServiciosNoVisitadosTests(BaseOperacion):
    def cierre_del_dia(self):
        """Día 1: un OK, un pase a Cable y un servicio al que no se llegó."""
        h = self.hoja(DIA, operarios=[self.op1, self.op2])
        a1 = self.accion(h, "46 100001", ["25-R"], numero=1)
        a2 = self.accion(h, "46 100002", ["23"], numero=2)
        a3 = self.accion(h, "46 100003", [], numero=3)
        certificar_ok(a1, self.user, "Cliente", ahora=hora(9, 0))
        pasar_a_brigada(a2, self.cable, self.user, ahora=hora(10, 0))
        cerrar_hoja(h, self.user, ahora=hora(15, 0))
        return h, a1, a2, a3

    def test_al_cerrar_la_hoja_lo_que_no_se_cerro_pasa_a_no_visitado(self):
        h, a1, a2, a3 = self.cierre_del_dia()
        for a in (a1, a2, a3):
            a.refresh_from_db(); a.orden.refresh_from_db()
        self.assertEqual((a1.estado, a2.estado, a3.estado), ("OK", "PASADA_A_BRIGADA", "NO_VISITADA"))
        self.assertEqual(a3.orden.estado, OrdenServicio.Estado.NO_VISITADA)
        self.assertEqual(a3.orden.brigada_pendiente, self.rep)  # la brigada que no la visitó
        self.assertEqual(a2.orden.estado, OrdenServicio.Estado.PENDIENTE)  # lo pasado a Cable sigue pendiente de Cable

    def test_el_resumen_muestra_las_pasadas_y_las_no_visitadas(self):
        h, *_ = self.cierre_del_dia()
        r = resumen_hoja(h, ahora=hora(15, 0))
        self.assertEqual(r["resultados"], {"ok": 1, "sin_ok": 0, "pasadas": 1, "no_visitadas": 1, "en_curso": 0})
        self.assertEqual(r["pasadas_a_brigada"], [{"servicio": "46 100002", "brigada": "Cable"}])
        self.assertEqual(r["no_visitadas"], ["46 100003"])
        self.assertEqual(r["efectividad_pct"], 50.0)  # 1 OK de 2 atendidas: lo no visitado no cuenta
        self.assertEqual(r["acciones_sin_cerrar"], [])

    def test_un_pendiente_de_otra_brigada_no_visitado_sigue_pendiente_para_ella(self):
        a = self.accion(self.hoja(DIA, operarios=[self.op1]), "46 200001", ["23"])
        pasar_a_brigada(a, self.cable, self.user, ahora=hora(9, 0))
        hoja_cable = crear_hoja(fecha=date(2026, 10, 2), brigada=self.cable, centro=self.centro)
        hoja_cable.operarios.set([self.op3])
        asignar_orden(hoja_cable, a.orden, self.user)
        cerrar_hoja(hoja_cable, self.user, ahora=hora(15, 0))  # Cable tampoco llegó
        a.orden.refresh_from_db()
        self.assertEqual(a.orden.estado, OrdenServicio.Estado.PENDIENTE)
        self.assertIn(a.orden, ordenes_pendientes(self.cable))
        self.assertEqual(ordenes_no_visitadas(self.cable).count(), 0)

    def test_las_no_visitadas_se_traen_solas_al_dia_siguiente(self):
        h, a1, a2, a3 = self.cierre_del_dia()
        otro_centro = Centro.objects.get(codigo="FI")
        self.assertEqual(ordenes_no_visitadas(self.rep, self.centro).count(), 1)
        self.assertEqual(ordenes_no_visitadas(self.rep, otro_centro).count(), 0)  # otro centro: no se ofrece
        self.assertEqual(ordenes_no_visitadas(self.cable).count(), 0)  # otra brigada: tampoco

        manana = crear_hoja(fecha=date(2026, 10, 2), brigada=self.rep, centro=self.centro)
        manana.operarios.set([self.op1, self.op2])
        acciones = asignar_no_visitadas(manana, self.user)
        self.assertEqual([a.orden.numero_servicio for a in acciones], ["46 100003"])
        self.assertEqual(acciones[0].orden_id, a3.orden_id)  # misma orden: se conserva su historial
        a3.orden.refresh_from_db()
        self.assertEqual((a3.orden.estado, a3.orden.brigada_pendiente), (OrdenServicio.Estado.ABIERTA, None))
        self.assertEqual(ordenes_no_visitadas(self.rep, self.centro).count(), 0)
        self.assertEqual(asignar_no_visitadas(manana, self.user), [])  # no se duplica

    def test_se_pueden_traer_solo_algunas(self):
        h = self.hoja(DIA, operarios=[self.op1])
        a, b = self.accion(h, "46 300001", [], numero=1), self.accion(h, "46 300002", [], numero=2)
        cerrar_hoja(h, self.user, ahora=hora(15, 0))
        manana = crear_hoja(fecha=date(2026, 10, 2), brigada=self.rep, centro=self.centro)
        manana.operarios.set([self.op1])
        traidas = asignar_no_visitadas(manana, self.user, ordenes=[b.orden])
        self.assertEqual([t.orden_id for t in traidas], [b.orden_id])
        self.assertEqual(ordenes_no_visitadas(self.rep, self.centro).count(), 1)


class MigracionHojasAntiguasTests(BaseOperacion):
    def test_una_hoja_cerrada_con_la_version_anterior_deja_sus_servicios_como_no_visitados(self):
        import importlib

        from django.apps import apps

        h = self.hoja(DIA, operarios=[self.op1])
        a = self.accion(h, "46 900001", [])  # sin cerrar
        HojaDeRuta.objects.filter(pk=h.pk).update(cerrada=True)  # así quedaban: hoja cerrada y acción "en curso"
        modulo = importlib.import_module("operacion.migrations.0005_hojas_cerradas_antiguas")
        modulo.convertir_a_no_visitadas(apps, None)
        a.refresh_from_db(); a.orden.refresh_from_db()
        self.assertEqual(a.estado, "NO_VISITADA")
        self.assertEqual((a.orden.estado, a.orden.brigada_pendiente), (OrdenServicio.Estado.NO_VISITADA, self.rep))
        self.assertEqual(ordenes_no_visitadas(self.rep, self.centro).count(), 1)


class VariosCentrosPorHojaTests(BaseOperacion):
    def setUp(self):
        self.ng = Centro.objects.get(codigo="NG")
        self.fi = Centro.objects.get(codigo="FI")
        self.fo = Centro.objects.get(codigo="FO")

    def hoja_dos_centros(self, fecha=DIA, operarios=None):
        h = crear_hoja(fecha=fecha, brigada=self.rep, centros=[self.ng, self.fi])
        h.operarios.set(operarios or [self.op1])
        return h

    def test_la_hoja_muestra_todos_sus_centros(self):
        self.assertEqual(self.hoja_dos_centros().etiqueta_centros, "FI + NG")

    def test_con_varios_centros_hay_que_indicar_el_del_servicio(self):
        h = self.hoja_dos_centros()
        orden = OrdenServicio.objects.create(numero_servicio="46 600001")
        with self.assertRaises(ValidationError) as error:
            asignar_orden(h, orden, self.user)
        self.assertIn("indique el centro del servicio", error.exception.messages[0])
        with self.assertRaises(ValidationError):
            asignar_orden(h, orden, self.user, centro=self.fo)  # La Reforma no es uno de los centros de la hoja
        self.assertEqual(asignar_orden(h, orden, self.user, centro=self.fi).centro, self.fi)

    def test_con_un_solo_centro_se_asigna_solo(self):
        h = self.hoja(DIA, operarios=[self.op1])
        self.assertEqual(asignar_orden(h, OrdenServicio.objects.create(numero_servicio="46 600002"), self.user).centro, self.centro)

    def test_lo_no_visitado_vuelve_al_centro_donde_estaba(self):
        dia1 = crear_hoja(fecha=DIA, brigada=self.rep, centro=self.fi)
        dia1.operarios.set([self.op1])
        a = self.accion(dia1, "46 600003", [])
        cerrar_hoja(dia1, self.user, ahora=hora(15, 0))
        # la hoja del día siguiente trabaja en NG y FI: la acción vuelve a FI sin preguntar
        dia2 = self.hoja_dos_centros(date(2026, 10, 2))
        traidas = asignar_no_visitadas(dia2, self.user)
        self.assertEqual([(t.orden_id, t.centro) for t in traidas], [(a.orden_id, self.fi)])
        # una hoja que solo trabaja en NG no recibe lo que quedó en FI
        dia3 = crear_hoja(fecha=date(2026, 10, 3), brigada=self.rep, centro=self.ng)
        dia3.operarios.set([self.op2])
        cerrar_hoja(dia2, self.user, ahora=hora(15, 0))
        self.assertEqual(ordenes_no_visitadas(self.rep, [self.ng]).count(), 0)
        self.assertEqual(ordenes_no_visitadas(self.rep, [self.ng, self.fi]).count(), 1)

    def test_el_resumen_por_centro_sigue_a_cada_servicio(self):
        from .reportes import resumen_periodo

        h = self.hoja_dos_centros(operarios=[self.op1, self.op2])
        a1 = asignar_orden(h, OrdenServicio.objects.create(numero_servicio="46 600010"), self.user, centro=self.ng)
        a2 = asignar_orden(h, OrdenServicio.objects.create(numero_servicio="46 600011"), self.user, centro=self.fi)
        a1.claves.set(Clave.objects.filter(codigo="25-R")); a2.claves.set(Clave.objects.filter(codigo="36"))
        certificar_ok(a1, self.user, "Cliente", ahora=hora(9, 0))      # 60 min, norma 45
        cerrar_sin_ok(a2, self.user, ahora=hora(10, 0))                # 60 min, sin OK
        r = resumen_periodo("dia", DIA, ahora=hora(16, 0))
        self.assertEqual((r["totales"]["hojas"], r["totales"]["acciones"], r["totales"]["ok"]), (1, 2, 1))  # la hoja cuenta una vez
        por_centro = {c["nombre"]: c for c in r["por_centro"]}
        self.assertEqual((por_centro["NG"]["acciones"], por_centro["NG"]["ok"], por_centro["NG"]["efectividad_pct"], por_centro["NG"]["productividad_pct"]), (1, 1, 100.0, 75.0))
        self.assertEqual((por_centro["FI"]["acciones"], por_centro["FI"]["ok"], por_centro["FI"]["efectividad_pct"], por_centro["FI"]["productividad_pct"]), (1, 0, 0.0, 0.0))
        self.assertEqual(sum(c["acciones"] for c in r["por_centro"]), r["totales"]["acciones"])  # el desglose suma el total
        self.assertEqual(r["hojas"][0]["centro"], "FI + NG")
        # el filtro por centro trae las hojas que trabajaron en él
        self.assertEqual(resumen_periodo("dia", DIA, centro=self.fi.pk, ahora=hora(16, 0))["totales"]["hojas"], 1)
        self.assertEqual(resumen_periodo("dia", DIA, centro=self.fo.pk, ahora=hora(16, 0))["totales"]["hojas"], 0)

    def test_la_administracion_acepta_varios_centros(self):
        from django.urls import reverse

        superusuario = get_user_model().objects.create_superuser("su2", "s@s.cu", "x")
        self.client.force_login(superusuario)
        datos = {"fecha": str(DIA), "brigada": self.rep.pk, "centros": [self.ng.pk, self.fi.pk], "hora_inicio": "08:00:00",
                 "operarios": [self.op1.pk], "observaciones": "",
                 "acciones-TOTAL_FORMS": 0, "acciones-INITIAL_FORMS": 0, "acciones-MIN_NUM_FORMS": 0, "acciones-MAX_NUM_FORMS": 1000,
                 "incidencias-TOTAL_FORMS": 0, "incidencias-INITIAL_FORMS": 0, "incidencias-MIN_NUM_FORMS": 0, "incidencias-MAX_NUM_FORMS": 1000}
        self.assertEqual(self.client.post(reverse("admin:operacion_hojaderuta_add"), datos).status_code, 302)
        self.assertEqual(HojaDeRuta.objects.get().etiqueta_centros, "FI + NG")
        self.assertContains(self.client.get(reverse("admin:operacion_hojaderuta_changelist")), "FI + NG")
