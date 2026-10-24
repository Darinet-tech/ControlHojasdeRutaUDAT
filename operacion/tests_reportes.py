from datetime import date

from catalogos.models import Brigada, Centro, CausaIncidencia, Clave, NormaTiempo, TipoOrden

from .models import HojaDeRuta, OrdenServicio
from .reportes import Normas, resumen_periodo
from .services import (asignar_orden, cerrar_hoja, certificar_ok, cerrar_sin_ok, iniciar_incidencia, finalizar_incidencia,
                       pasar_a_brigada, resumen_hoja)
from .tests import BaseOperacion, crear_hoja, hora


def en(dia, hh, mm=0):
    from datetime import datetime

    from django.utils import timezone
    return timezone.make_aware(datetime(2026, 10, dia, hh, mm))


class EscenarioDosDias:
    """Día 5 (hoja A, op1 y op2): OK, sin OK, pasada a Cable y una no visitada, con 60 min de lluvia.
    Día 6 (hoja B, solo op1): un OK sobre el mismo servicio del día 5 (reincidencia).

    Cálculo a mano
      Hoja A: acciones 4, atendidas 3, OK 1 -> efectividad 33.3 %. Reales 60+60+60 = 180 min, normado 45 (clave mayor de
              25-R y 07-IC) -> productividad 25.0 %. Disponible 2 x (420-60) = 720 -> ocupación 25.0 %.
      Hoja B: 1 OK de 1 -> 100 %. Real 60, normado 35 (21-R) -> 58.3 %. Disponible 420 -> ocupación 14.3 %.
      Mes: 2 hojas, 5 acciones, 4 atendidas, 2 OK -> 50.0 %. Real 240, normado 80 -> 33.3 %. Disponible 1140 -> 21.1 %.
    """

    def escenario(self):
        ng = self.centro
        self.hoja_a = crear_hoja(fecha=date(2026, 10, 5), brigada=self.rep, centro=ng)
        self.hoja_a.operarios.set([self.op1, self.op2])
        a1 = self.accion(self.hoja_a, "46 100001", ["25-R", "07-IC"], numero=1)
        a2 = self.accion(self.hoja_a, "46 100002", ["36"], numero=2)
        a3 = self.accion(self.hoja_a, "46 100003", ["23"], numero=3)
        self.accion(self.hoja_a, "46 100004", [], numero=4)
        certificar_ok(a1, self.user, "Cliente", ahora=en(5, 9))
        cerrar_sin_ok(a2, self.user, ahora=en(5, 10))
        pasar_a_brigada(a3, self.cable, self.user, ahora=en(5, 11))
        iniciar_incidencia(self.hoja_a, CausaIncidencia.objects.get(codigo="100"), self.user, ahora=en(5, 12))
        finalizar_incidencia(self.hoja_a, self.user, ahora=en(5, 13))
        cerrar_hoja(self.hoja_a, self.user, ahora=en(5, 15))

        self.hoja_b = crear_hoja(fecha=date(2026, 10, 6), brigada=self.rep, centro=ng)
        self.hoja_b.operarios.set([self.op1])
        # mismo servicio que a1, ya restablecido: el sistema abre una orden nueva = reincidencia
        b1 = asignar_orden(self.hoja_b, OrdenServicio.objects.create(numero_servicio="46 100001"), self.user)
        b1.claves.set(Clave.objects.filter(codigo="21-R"))
        certificar_ok(b1, self.user, "Cliente", ahora=en(6, 9))
        cerrar_hoja(self.hoja_b, self.user, ahora=en(6, 15))


class ResumenesTests(EscenarioDosDias, BaseOperacion):
    def setUp(self):
        self.escenario()
        self.ahora = en(6, 16)

    def test_el_mes_completo(self):
        r = resumen_periodo("mes", date(2026, 10, 20), ahora=self.ahora)
        t = r["totales"]
        self.assertEqual((r["desde"], r["hasta"]), ("2026-10-01", "2026-10-31"))
        self.assertEqual((t["hojas"], t["acciones"], t["atendidas"], t["ok"]), (2, 5, 4, 2))
        self.assertEqual((t["sin_ok"], t["pasadas"], t["no_visitadas"], t["en_curso"]), (1, 1, 1, 0))
        self.assertEqual((t["efectividad_pct"], t["tiempo_real_min"], t["tiempo_normado_min"], t["productividad_pct"]), (50.0, 240, 80, 33.3))
        self.assertEqual((t["incidencias_min"], t["tiempo_disponible_min"], t["ocupacion_pct"]), (60, 1140, 21.1))

    def test_el_dia_con_detalle_por_hoja(self):
        r = resumen_periodo("dia", date(2026, 10, 5), ahora=self.ahora)
        self.assertEqual(r["totales"]["hojas"], 1)
        hoja = r["hojas"][0]
        self.assertEqual((hoja["id"], hoja["cerrada"], hoja["operarios"]), (self.hoja_a.pk, True, ["Operario Dos", "Operario Uno"]))
        self.assertEqual((hoja["efectividad_pct"], hoja["productividad_pct"], hoja["ocupacion_pct"]), (33.3, 25.0, 25.0))
        self.assertEqual(r["incidencias"], [{"codigo": "100", "nombre": "Lluvia", "minutos": 60, "hojas": 1}])

    def test_el_resumen_de_periodo_coincide_con_el_de_cada_hoja(self):
        for hoja in (self.hoja_a, self.hoja_b):
            individual = resumen_hoja(hoja, ahora=self.ahora)
            en_bloque = resumen_periodo("dia", hoja.fecha, ahora=self.ahora)["totales"]
            for propio, bloque in (("efectividad_pct", "efectividad_pct"), ("productividad_pct", "productividad_pct"),
                                   ("ocupacion_pct", "ocupacion_pct"), ("incidencias_min", "incidencias_min"),
                                   ("tiempo_real_min", "tiempo_real_min"), ("tiempo_disponible_min", "tiempo_disponible_min"),
                                   ("tiempo_normado_efectivo_min", "tiempo_normado_min")):
                self.assertEqual(individual[propio], en_bloque[bloque], propio)

    def test_productividad_individual(self):
        por_nombre = {o["nombre"]: o for o in resumen_periodo("mes", date(2026, 10, 1), ahora=self.ahora)["por_operario"]}
        uno, dos = por_nombre["Operario Uno"], por_nombre["Operario Dos"]
        self.assertEqual((uno["dias"], uno["hojas"], uno["acciones"], uno["ok"], uno["efectividad_pct"], uno["productividad_pct"]), (2, 2, 5, 2, 50.0, 33.3))
        self.assertEqual((dos["dias"], dos["hojas"], dos["acciones"], dos["ok"], dos["efectividad_pct"], dos["productividad_pct"]), (1, 1, 4, 1, 33.3, 25.0))
        self.assertNotIn("Operario Tres", por_nombre)

    def test_detalle_por_dia_y_por_mes(self):
        mes = resumen_periodo("mes", date(2026, 10, 1), ahora=self.ahora)
        self.assertEqual([(d["fecha"], d["ok"], d["efectividad_pct"]) for d in mes["por_dia"]], [("2026-10-05", 1, 33.3), ("2026-10-06", 1, 100.0)])
        anio = resumen_periodo("anio", date(2026, 3, 3), ahora=self.ahora)
        self.assertEqual((anio["desde"], anio["hasta"]), ("2026-01-01", "2026-12-31"))
        self.assertEqual([(m["mes"], m["hojas"]) for m in anio["por_mes"]], [("2026-10", 2)])
        self.assertEqual(resumen_periodo("anio", date(2025, 6, 1), ahora=self.ahora)["totales"]["hojas"], 0)

    def test_listados_de_pasadas_no_visitadas_y_reincidencias(self):
        r = resumen_periodo("mes", date(2026, 10, 1), ahora=self.ahora)
        self.assertEqual(r["pasadas_a_brigada"]["lista"], [{"fecha": "2026-10-05", "servicio": "46 100003", "desde": "Red de Abonados",
                                                           "hacia": "Cable", "centro": "NG", "estado_actual": "Pendiente de otra brigada"}])
        self.assertEqual(r["no_visitadas"]["lista"], [{"fecha": "2026-10-05", "servicio": "46 100004", "brigada": "Red de Abonados",
                                                      "centro": "NG", "sigue_sin_visitar": True}])
        self.assertEqual(r["reincidencias"]["lista"], [{"servicio": "46 100001", "ordenes": 2, "acciones": 2,
                                                       "operarios": ["Operario Dos", "Operario Uno"], "ultima_fecha": "2026-10-06"}])

    def test_filtros_por_brigada_y_centro(self):
        otro_centro = Centro.objects.get(codigo="FI")
        self.assertEqual(resumen_periodo("mes", date(2026, 10, 1), brigada=self.cable.pk, ahora=self.ahora)["totales"]["hojas"], 0)
        self.assertEqual(resumen_periodo("mes", date(2026, 10, 1), centro=otro_centro.pk, ahora=self.ahora)["totales"]["hojas"], 0)
        r = resumen_periodo("mes", date(2026, 10, 1), brigada=self.rep.pk, centro=self.centro.pk, ahora=self.ahora)
        self.assertEqual(r["totales"]["hojas"], 2)
        self.assertEqual([b["nombre"] for b in r["por_brigada"]], ["Red de Abonados"])
        self.assertEqual([c["nombre"] for c in r["por_centro"]], ["NG"])

    def test_una_incidencia_activa_cuenta_hasta_el_momento_de_la_consulta(self):
        hoja = crear_hoja(fecha=date(2026, 10, 7), brigada=self.rep, centro=self.centro)
        hoja.operarios.set([self.op3])
        iniciar_incidencia(hoja, CausaIncidencia.objects.get(codigo="106"), self.user, ahora=en(7, 9))
        r = resumen_periodo("dia", date(2026, 10, 7), ahora=en(7, 10, 30))
        self.assertEqual(r["totales"]["incidencias_min"], 90)
        self.assertEqual(r["totales"]["tiempo_disponible_min"], 420 - 90)

    def test_normas_en_memoria_igual_que_la_consulta_normal(self):
        tipo = TipoOrden.objects.get(codigo="A")
        clave = Clave.objects.get(codigo="25-R")
        NormaTiempo.objects.filter(clave=clave).update(vigente_hasta=date(2026, 6, 30))
        NormaTiempo.objects.create(clave=clave, minutos=50, vigente_desde=date(2026, 7, 1))
        NormaTiempo.objects.create(clave=clave, tipo_orden=tipo, minutos=70, vigente_desde=date(2026, 7, 1))
        normas = Normas()
        for codigo in ("25-R", "07-IC", "23", "36"):
            c = Clave.objects.get(codigo=codigo)
            for t in (None, tipo):
                for f in (date(2026, 1, 1), date(2026, 6, 30), date(2026, 7, 1), date(2026, 12, 31)):
                    oficial = NormaTiempo.vigente(c, t, f)
                    self.assertEqual(normas.minutos(c.pk, t.pk if t else None, f), oficial.minutos if oficial else None, (codigo, t, f))


class ReincidenciaConServicioNoVisitadoTests(BaseOperacion):
    def test_cuenta_la_segunda_orden_aunque_no_se_visite_pero_no_atribuye_operarios_a_lo_no_visitado(self):
        h1 = crear_hoja(fecha=date(2026, 10, 5), brigada=self.rep, centro=self.centro)
        h1.operarios.set([self.op1])
        a1 = self.accion(h1, "46 500001", ["25-R"])
        certificar_ok(a1, self.user, "Cliente", ahora=en(5, 9))
        h2 = crear_hoja(fecha=date(2026, 10, 6), brigada=self.rep, centro=self.centro)
        h2.operarios.set([self.op2])
        asignar_orden(h2, OrdenServicio.objects.create(numero_servicio="46 500001"), self.user)  # reportó otra vez
        cerrar_hoja(h2, self.user, ahora=en(6, 15))  # y no se visitó
        r = resumen_periodo("mes", date(2026, 10, 1))["reincidencias"]["lista"]
        self.assertEqual(r, [{"servicio": "46 500001", "ordenes": 2, "acciones": 2, "operarios": ["Operario Uno"],
                              "ultima_fecha": "2026-10-06"}])
