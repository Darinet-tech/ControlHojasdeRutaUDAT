import io
from datetime import date, datetime, timedelta

from django.core.management import call_command
from django.utils import timezone

from .models import Accion, Incidencia, OrdenServicio
from .tests import BaseOperacion
from catalogos.models import CausaIncidencia


class CierreAutomaticoTests(BaseOperacion):
    def ejecutar(self, *args):
        salida = io.StringIO()
        call_command("cerrar_hojas_antiguas", *args, stdout=salida)
        return salida.getvalue()

    def test_cierra_las_hojas_de_dias_anteriores_y_deja_los_servicios_como_no_visitados(self):
        ayer = timezone.localdate() - timedelta(days=3)
        hoja = self.hoja(fecha=ayer)
        accion = self.accion(hoja, "46-111111", ["25-R"])
        self.ejecutar()
        hoja.refresh_from_db(); accion.refresh_from_db()
        self.assertTrue(hoja.cerrada)
        self.assertTrue(accion.no_visitada)
        self.assertEqual(accion.orden.estado, OrdenServicio.Estado.NO_VISITADA)
        self.assertEqual(timezone.localtime(hoja.cerrada_en).date(), ayer)  # cerrada al final del día de la hoja

    def test_no_toca_la_hoja_de_hoy(self):
        hoja = self.hoja(fecha=timezone.localdate())
        self.accion(hoja, "46-222222", ["25-R"])
        self.ejecutar()
        hoja.refresh_from_db()
        self.assertFalse(hoja.cerrada)

    def test_una_incidencia_activa_se_detiene_al_final_del_dia_de_la_hoja(self):
        dia = timezone.localdate() - timedelta(days=5)
        hoja = self.hoja(fecha=dia)
        inicio = timezone.make_aware(datetime.combine(dia, datetime.min.time().replace(hour=10)))
        inc = Incidencia.objects.create(hoja=hoja, causa=CausaIncidencia.objects.first(), inicio=inicio)
        self.ejecutar()
        inc.refresh_from_db()
        self.assertLess(inc.minutos(), 24 * 60)

    def test_simular_no_cierra_nada(self):
        hoja = self.hoja(fecha=timezone.localdate() - timedelta(days=1))
        texto = self.ejecutar("--simular")
        hoja.refresh_from_db()
        self.assertFalse(hoja.cerrada)
        self.assertIn("SIMULADO", texto)
