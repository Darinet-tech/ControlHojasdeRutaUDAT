"""Actividades de Cable y Línea de la instrucción IT-OR-001/24 y causas de incidencia que cuentan como tiempo efectivo."""
from datetime import date, datetime, time

from django.utils import timezone

from catalogos.models import CausaIncidencia, NormaTrabajo, TipoTrabajo

from .models import CantidadDeTrabajo
from .services import asignar_orden, certificar_ok, finalizar_incidencia, iniciar_incidencia, norma_accion, obtener_orden, resumen_hoja
from .tests import BaseOperacion

DIA = date(2026, 10, 5)


def a_las(h, m=0):
    return timezone.make_aware(datetime.combine(DIA, time(h, m)))


class ActividadesDeLaInstruccionTests(BaseOperacion):
    def actividad(self, especialidad, clave):
        return TipoTrabajo.objects.get(especialidad=especialidad, clave=clave)

    def test_estan_las_actividades_de_cable_y_linea_con_su_norma(self):
        self.assertEqual([TipoTrabajo.objects.filter(especialidad=e).count() for e in ("Cable", "Línea", "Fibra Óptica")], [96, 51, 26])
        norma = lambda t: NormaTrabajo.objects.get(tipo_trabajo=t, opcion__isnull=True).minutos  # noqa: E731
        casos = [(("Cable", "31"), "METROS", 6), (("Cable", "48"), "UNIDADES", 1), (("Cable", "49"), "UNIDADES", 1.5), (("Cable", "18"), "UNIDADES", 70),
                 (("Línea", "69"), "METROS", 0.8), (("Línea", "67"), "METROS", 0.91), (("Línea", "91"), "METROS", 0.42), (("Línea", "5"), "UNIDADES", 110)]
        for (especialidad, clave), medida, minutos in casos:
            t = self.actividad(especialidad, clave)
            self.assertEqual((t.medida, norma(t)), (medida, minutos), (especialidad, clave))
        self.assertEqual(self.actividad("Cable", "48").unidad, "par(es)")
        self.assertEqual(self.actividad("Línea", "69").fuerza_trabajo, "2 linieros A 4 linieros B")
        self.assertEqual(self.actividad("Cable", "31").etiqueta, "Cable 31 · Instalar tramo aéreo hasta 200 pares")

    def test_la_clave_se_repite_entre_especialidades_pero_no_dentro_de_una(self):
        self.assertNotEqual(self.actividad("Cable", "5").nombre, self.actividad("Línea", "5").nombre)  # Cable 5 y Línea 5 son actividades distintas
        self.assertFalse(TipoTrabajo.objects.filter(especialidad="Cable", clave="144").exists())  # «72 horas» es una espera, no un tiempo de trabajo
        self.assertEqual(TipoTrabajo.objects.filter(especialidad="Cable", clave="102").count(), 1)  # estaba repetida en la instrucción

    def test_una_orden_suma_todas_sus_actividades(self):
        """Sustituir 30 m de cable soterrado de hasta 202 pares, con 2 empates y 100 pares empalmados."""
        trabajos = [self.actividad("Cable", c) for c in ("36", "43", "48", "76")]
        orden = obtener_orden("ORDEN_TRABAJO", self.user, numero_orden="9100", trabajos=trabajos)
        a = asignar_orden(self.hoja(fecha=DIA), orden, self.user, trabajos=trabajos)
        for clave, cantidad in (("36", 2), ("43", 30), ("48", 100), ("76", 2)):
            CantidadDeTrabajo.objects.create(accion=a, trabajo=self.actividad("Cable", clave), cantidad=cantidad)
        self.assertEqual(norma_accion(a), 2 * 30 + 30 * 10 + 100 * 1 + 2 * 30)  # 520
        # el cable aéreo cosido de Línea, 30 m: 0,91 min por metro
        linea = [self.actividad("Línea", "67")]
        orden2 = obtener_orden("ORDEN_TRABAJO", self.user, numero_orden="9101", trabajos=linea)
        b = asignar_orden(self.hoja(fecha=date(2026, 10, 6)), orden2, self.user, trabajos=linea)
        CantidadDeTrabajo.objects.create(accion=b, trabajo=linea[0], cantidad=30)
        self.assertAlmostEqual(norma_accion(b), 27.3, places=2)

    def test_fibra_optica_distingue_la_instalacion_y_norma_por_fibra_lo_que_dice_2xfo(self):
        empalme = self.actividad("Fibra Óptica", "164")
        self.assertEqual((empalme.nombre, empalme.medida, empalme.unidad), ("Empalme (fusión o mecánica) (aéreo)", "UNIDADES", "fibra(s)"))
        self.assertEqual([self.actividad("Fibra Óptica", c).nombre.split("(")[-1] for c in ("161", "173", "186")], ["aéreo)", "soterrado)", "enterrado)"])
        norma = lambda c: NormaTrabajo.objects.get(tipo_trabajo=self.actividad("Fibra Óptica", c)).minutos  # noqa: E731
        self.assertEqual([norma(c) for c in ("161", "163", "164", "166", "178")], [30, 40, 2, 2, 240])
        self.assertFalse(NormaTrabajo.objects.filter(tipo_trabajo=self.actividad("Fibra Óptica", "169")).exists())  # la instrucción no le da tiempo
        trabajos = [self.actividad("Fibra Óptica", c) for c in ("162", "164", "166", "169")]
        orden = obtener_orden("ORDEN_TRABAJO", self.user, numero_orden="9200", trabajos=trabajos)
        a = asignar_orden(self.hoja(fecha=DIA), orden, self.user, trabajos=trabajos)
        for t, cantidad in zip(trabajos, (1, 24, 24, 1)):
            CantidadDeTrabajo.objects.create(accion=a, trabajo=t, cantidad=cantidad)
        self.assertEqual(norma_accion(a), 30 + 24 * 2 + 24 * 2)  # 24 fibras; la preparación del registro (169) no suma porque no tiene norma

    def test_una_instalacion_nueva_no_trae_trabajos_de_prueba(self):
        from importlib import import_module
        from django.apps import apps
        import_module("catalogos.migrations.0023_actividades_de_fibra_optica_sin_trabajos_de_prueba").aplicar(apps, None)
        self.assertFalse(TipoTrabajo.objects.filter(especialidad="", nombre__startswith="Sustitución de").exclude(medida="TIPO").exists())
        self.assertEqual(TipoTrabajo.objects.exclude(especialidad="").count(), 173)

    def test_la_importacion_acepta_la_especialidad_y_la_clave(self):
        from .importacion import _actividad
        self.assertEqual([_actividad(t).clave for t in ("Línea 67", "linea 5", "Cable 18", "FIBRA OPTICA 164")], ["67", "5", "18", "164"])
        self.assertEqual(_actividad("Instalar poste 7,5 metros en tierra manualmente").etiqueta[:7], "Línea 5")

    def test_cargar_de_nuevo_no_duplica(self):
        from django.core.management import call_command
        antes = (TipoTrabajo.objects.count(), NormaTrabajo.objects.count())
        call_command("cargar_inicial", verbosity=0)
        self.assertEqual((TipoTrabajo.objects.count(), NormaTrabajo.objects.count()), antes)


class IncidenciasQueCuentanComoTiempoEfectivoTests(BaseOperacion):
    def test_las_causas_que_define_la_instruccion_no_descuentan_tiempo(self):
        efectivas = {c.codigo for c in CausaIncidencia.objects.filter(descuenta_tiempo=False)}
        self.assertEqual(efectivas, {"105", "107", "111", "112"})
        self.assertEqual(CausaIncidencia.objects.get(codigo="111").nombre, "Tiempo de poda")
        self.assertEqual(CausaIncidencia.objects.get(codigo="112").nombre, "Tiempo trasladado")

    def test_una_causa_efectiva_no_se_resta_del_tiempo_real_ni_del_disponible(self):
        for codigo, descuenta in (("112", False), ("100", True)):
            from .models import HojaDeRuta
            HojaDeRuta.objects.all().delete()
            h = self.hoja(fecha=DIA, inicio=time(8, 0))
            a = self.accion(h, f"46 8000{codigo}", ["25-R"])
            iniciar_incidencia(h, CausaIncidencia.objects.get(codigo=codigo), self.user, ahora=a_las(8, 0))
            finalizar_incidencia(h, self.user, ahora=a_las(9, 0))
            certificar_ok(a, self.user, "Cliente", ahora=a_las(10, 0))
            a.refresh_from_db()
            r = resumen_hoja(h, ahora=a_las(11, 0))
            self.assertEqual(a.tiempo_real_min, 60 if descuenta else 120, codigo)  # 120 min desde las 8:00; la lluvia (100) resta 60, el traslado (112) no
            self.assertEqual(r["tiempo_disponible_min"], 2 * (420 - (60 if descuenta else 0)), codigo)
