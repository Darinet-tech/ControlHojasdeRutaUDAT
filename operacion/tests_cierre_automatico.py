import io
from datetime import date, datetime, timedelta
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from catalogos.models import CausaIncidencia

from .informes import complemento_del_dia_anterior, reunir_datos
from .models import DestinatarioInforme, Incidencia, OrdenServicio
from .services import certificar_ok
from .tests import BaseOperacion


def a_las(dia, hh, mm=0):
    return timezone.make_aware(datetime(dia.year, dia.month, dia.day, hh, mm))


class CierreAutomaticoTests(BaseOperacion):
    def ejecutar(self, *args, ahora=None):
        salida = io.StringIO()
        with mock.patch("django.utils.timezone.now", return_value=ahora or timezone.now()):
            call_command("cerrar_hojas_antiguas", *args, stdout=salida)
        return salida.getvalue()

    def test_cierra_las_hojas_de_dias_anteriores_y_deja_los_servicios_como_no_visitados(self):
        dia = timezone.localdate() - timedelta(days=3)
        hoja = self.hoja(fecha=dia)
        accion = self.accion(hoja, "46-111111", ["25-R"])
        self.ejecutar()
        hoja.refresh_from_db(); accion.refresh_from_db()
        self.assertTrue(hoja.cerrada)
        self.assertTrue(accion.no_visitada)
        self.assertEqual(accion.orden.estado, OrdenServicio.Estado.NO_VISITADA)
        self.assertEqual(timezone.localtime(hoja.cerrada_en), a_las(dia, 21))  # cerrada a la hora de cierre del día de la hoja

    def test_la_hoja_de_hoy_sigue_abierta_antes_de_las_21(self):
        hoy = date(2026, 10, 7)
        hoja = self.hoja(fecha=hoy)
        self.ejecutar(ahora=a_las(hoy, 20, 59))
        hoja.refresh_from_db()
        self.assertFalse(hoja.cerrada)

    def test_la_hoja_de_hoy_se_cierra_a_las_21(self):
        hoy = date(2026, 10, 7)
        hoja = self.hoja(fecha=hoy)
        accion = self.accion(hoja, "46-222222", ["25-R"])
        self.ejecutar(ahora=a_las(hoy, 21, 30))  # aunque la tarea corra tarde, el cierre consta a las 21:00
        hoja.refresh_from_db(); accion.refresh_from_db()
        self.assertTrue(hoja.cerrada and accion.no_visitada)
        self.assertEqual(timezone.localtime(hoja.cerrada_en), a_las(hoy, 21))

    def test_una_incidencia_activa_se_detiene_a_la_hora_de_cierre(self):
        dia = timezone.localdate() - timedelta(days=5)
        hoja = self.hoja(fecha=dia)
        inc = Incidencia.objects.create(hoja=hoja, causa=CausaIncidencia.objects.first(), inicio=a_las(dia, 19))
        self.ejecutar()
        inc.refresh_from_db()
        self.assertEqual(inc.minutos(), 120)

    def test_simular_no_cierra_nada(self):
        hoja = self.hoja(fecha=timezone.localdate() - timedelta(days=1))
        texto = self.ejecutar("--simular")
        hoja.refresh_from_db()
        self.assertFalse(hoja.cerrada)
        self.assertIn("SIMULADO", texto)


class ComplementoDelCorteTests(BaseOperacion):
    DIA = date(2026, 10, 5)

    def setUp(self):
        self.hoja_a = self.hoja(fecha=self.DIA)
        self.antes = self.accion(self.hoja_a, "46-300001", ["25-R"], numero=1)
        self.despues = self.accion(self.hoja_a, "46-300002", ["25-R"], numero=2)
        certificar_ok(self.antes, self.user, "Cliente A", ahora=a_las(self.DIA, 15, 30))
        certificar_ok(self.despues, self.user, "Cliente B", ahora=a_las(self.DIA, 17, 45))  # después del corte de las 16:00
        self.hoja_b = self.hoja(fecha=self.DIA + timedelta(days=1), operarios=[self.op1, self.op2])

    def test_el_parte_del_dia_siguiente_incluye_solo_lo_posterior_al_corte(self):
        comp = complemento_del_dia_anterior(self.DIA + timedelta(days=1))
        self.assertEqual(comp["fecha"], self.DIA)
        self.assertEqual([f["descripcion"].split()[0] for f in comp["acciones"]], ["46-300002"])
        self.assertEqual(comp["totales"]["ok"], 1)

    def test_las_acciones_se_contabilizan_en_el_dia_en_que_se_hicieron(self):
        dia = reunir_datos(self.DIA)["resumen"]["totales"]
        siguiente = reunir_datos(self.DIA + timedelta(days=1))["resumen"]["totales"]
        self.assertEqual((dia["acciones"], dia["ok"]), (2, 2))  # las dos cuentan el día 5
        self.assertEqual(siguiente["acciones"], 0)  # y el complemento no suma nada al día 6

    def test_el_complemento_llega_en_el_correo_y_en_los_adjuntos(self):
        from .correo import enviar_informe_diario
        DestinatarioInforme.objects.create(nombre="Jefe", correo="jefe@etecsa.cu")
        estado, mensaje, _ = enviar_informe_diario(fecha=self.DIA + timedelta(days=1), ahora=a_las(self.DIA + timedelta(days=1), 16))
        self.assertEqual(estado, "ENVIADO", mensaje)
        cuerpo = mail.outbox[0].body
        self.assertIn("Complemento del 05/10/2026", cuerpo)
        self.assertIn("46-300002", cuerpo)
        self.assertNotIn("46-300001", cuerpo)

    def test_sin_acciones_posteriores_no_hay_complemento(self):
        self.assertIsNone(complemento_del_dia_anterior(self.DIA))  # no hay ningún día anterior con hojas
