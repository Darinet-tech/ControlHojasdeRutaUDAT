import io
from datetime import date, time
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from .correo import enviar_informe_diario
from .models import DestinatarioInforme, InformeEnviado
from .tests import BaseOperacion, crear_hoja
from .tests_reportes import EscenarioDosDias, en

DIA5 = date(2026, 10, 5)


class EnvioDelInformeTests(EscenarioDosDias, BaseOperacion):
    def setUp(self):
        self.escenario()
        DestinatarioInforme.objects.create(nombre="Jefe de Departamento", correo="jefe.dpto@etecsa.cu")
        DestinatarioInforme.objects.create(nombre="Especialista", correo="especialista@etecsa.cu")
        DestinatarioInforme.objects.create(nombre="Ya no recibe", correo="baja@etecsa.cu", activo=False)
        self.corte = en(5, 16)  # el corte de las 16:00

    def test_el_informe_sale_con_sus_adjuntos_desde_la_cuenta_del_jefe_de_la_udat(self):
        estado, mensaje, registro = enviar_informe_diario(fecha=DIA5, ahora=self.corte)
        self.assertEqual(estado, "ENVIADO", mensaje)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertIn("leonel.hinojosa@etecsa.cu", m.from_email)
        self.assertEqual(m.reply_to, ["leonel.hinojosa@etecsa.cu"])
        self.assertEqual(sorted(m.to), ["especialista@etecsa.cu", "jefe.dpto@etecsa.cu"])  # solo los activos
        self.assertEqual(m.subject, "UDAT · Informe diario 05/10/2026 (corte 16:00)")
        nombres = {a[0]: a for a in m.attachments}
        self.assertEqual(set(nombres), {"UDAT_informe_diario_2026-10-05.pdf", "UDAT_informe_diario_2026-10-05.xlsx"})
        self.assertTrue(nombres["UDAT_informe_diario_2026-10-05.pdf"][1].startswith(b"%PDF"))
        self.assertTrue(nombres["UDAT_informe_diario_2026-10-05.xlsx"][1].startswith(b"PK"))
        for esperado in ("Informe diario — lunes, 5 de octubre de 2026", "Corte a las 16:00", "Hojas de ruta: 1 (1 cerradas y 0 abiertas al corte)",
                         "con OK: 1", "pasadas a otra brigada: 1", "no visitadas: 1", "Efectividad: 33.3 %", "Productividad: 25.0 %"):
            self.assertIn(esperado, m.body)

    def test_queda_registro_con_copia_de_lo_enviado(self):
        _, _, registro = enviar_informe_diario(fecha=DIA5, ahora=self.corte)
        registro.refresh_from_db()
        self.assertEqual((registro.estado, registro.fecha, registro.corte), ("ENVIADO", DIA5, self.corte))
        self.assertEqual(registro.destinatarios, "especialista@etecsa.cu, jefe.dpto@etecsa.cu")
        self.assertTrue(bytes(registro.pdf).startswith(b"%PDF") and bytes(registro.excel).startswith(b"PK"))
        self.assertEqual(bytes(registro.pdf), mail.outbox[0].attachments[0][1])  # la copia es exactamente lo que se envió

    def test_el_corte_se_hace_aunque_haya_hojas_abiertas(self):
        import openpyxl
        abierta = crear_hoja(fecha=DIA5, brigada=self.cable, centro=self.centro)
        abierta.operarios.set([self.op3])
        self.accion(abierta, "46 700001", [])  # los operarios aún no terminan
        enviar_informe_diario(fecha=DIA5, ahora=self.corte)
        m = mail.outbox[0]
        self.assertIn("Hojas de ruta: 2 (1 cerradas y 1 abiertas al corte)", m.body)
        self.assertIn("Hojas todavía abiertas al corte", m.body)
        self.assertIn("NG · Cable (A3)", m.body)
        excel = next(a[1] for a in m.attachments if a[0].endswith(".xlsx"))
        self.assertIn("corte a las 16:00", openpyxl.load_workbook(io.BytesIO(excel))["Resumen"]["A2"].value)
        self.assertFalse(abierta.cerrada)  # el corte no cierra nada

    def test_no_se_repite_el_mismo_dia_salvo_que_se_fuerce(self):
        enviar_informe_diario(fecha=DIA5, ahora=self.corte)
        estado, mensaje, _ = enviar_informe_diario(fecha=DIA5, ahora=self.corte)
        self.assertEqual((estado, len(mail.outbox)), ("YA_ENVIADO", 1))
        self.assertEqual(enviar_informe_diario(fecha=DIA5, ahora=self.corte, forzar=True)[0], "ENVIADO")
        self.assertEqual(len(mail.outbox), 2)

    def test_un_dia_sin_hojas_no_genera_correo(self):
        estado, mensaje, registro = enviar_informe_diario(fecha=date(2026, 10, 20), ahora=en(20, 16))
        self.assertEqual((estado, len(mail.outbox), registro.estado), ("OMITIDO", 0, "OMITIDO"))
        self.assertIn("No hay hojas de ruta", mensaje)

    def test_sin_destinatarios_queda_el_error_registrado(self):
        DestinatarioInforme.objects.all().delete()
        estado, mensaje, registro = enviar_informe_diario(fecha=DIA5, ahora=self.corte)
        self.assertEqual((estado, len(mail.outbox), registro.estado), ("ERROR", 0, "ERROR"))
        self.assertIn("No hay destinatarios activos", registro.detalle)

    def test_si_el_servidor_de_correo_falla_se_registra_y_se_puede_reintentar(self):
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=ConnectionRefusedError("smtp.etecsa.cu no responde")):
            estado, mensaje, registro = enviar_informe_diario(fecha=DIA5, ahora=self.corte)
        self.assertEqual((estado, registro.estado), ("ERROR", "ERROR"))
        self.assertIn("ConnectionRefusedError: smtp.etecsa.cu no responde", registro.detalle)
        self.assertTrue(bytes(registro.pdf).startswith(b"%PDF"))  # el informe quedó generado
        estado, _, _ = enviar_informe_diario(fecha=DIA5, ahora=self.corte)  # un error no cuenta como enviado: el reintento sale
        self.assertEqual((estado, len(mail.outbox)), ("ENVIADO", 1))

    def test_simular_no_envia_ni_registra(self):
        estado, mensaje, registro = enviar_informe_diario(fecha=DIA5, ahora=self.corte, simular=True)
        self.assertEqual((estado, registro, len(mail.outbox), InformeEnviado.objects.count()), ("SIMULADO", None, 0, 0))
        self.assertIn("jefe.dpto@etecsa.cu", mensaje)

    def test_comando_programable(self):
        salida = io.StringIO()
        call_command("enviar_informe_diario", "--fecha", "2026-10-05", stdout=salida)
        self.assertIn("[ENVIADO]", salida.getvalue())
        DestinatarioInforme.objects.all().delete()
        with self.assertRaises(CommandError):  # código de salida distinto de cero: el planificador lo marca como fallido
            call_command("enviar_informe_diario", "--fecha", "2026-10-05", "--forzar")

    def test_configuracion_acordada(self):
        self.assertEqual((settings.EMAIL_HOST, settings.EMAIL_PORT, settings.EMAIL_USE_TLS, settings.EMAIL_HOST_USER), ("smtp.etecsa.cu", 25, False, ""))
        self.assertIn("leonel.hinojosa@etecsa.cu", settings.INFORME_REMITENTE)
        self.assertEqual(settings.INFORME_HORA_CORTE, time(16, 0))


class AdministracionDelEnvioTests(EscenarioDosDias, BaseOperacion):
    def test_el_administrador_define_los_destinatarios_y_audita_lo_enviado(self):
        self.escenario()
        admin = get_user_model().objects.create_superuser("adm_correo", "a@a.cu", "x")
        self.client.force_login(admin)
        DestinatarioInforme.objects.create(nombre="Jefe de Grupo", correo="jefe.grupo@etecsa.cu")
        _, _, registro = enviar_informe_diario(fecha=DIA5, ahora=en(5, 16))
        self.assertContains(self.client.get(reverse("admin:operacion_destinatarioinforme_changelist")), "jefe.grupo@etecsa.cu")
        lista = self.client.get(reverse("admin:operacion_informeenviado_changelist"))
        self.assertContains(lista, "Enviado")
        self.assertContains(lista, reverse("admin:operacion_informeenviado_descargar", args=[registro.pk, "pdf"]))
        pdf = self.client.get(reverse("admin:operacion_informeenviado_descargar", args=[registro.pk, "pdf"]))
        self.assertEqual((pdf.status_code, pdf["Content-Type"]), (200, "application/pdf"))
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertTrue(self.client.get(reverse("admin:operacion_informeenviado_descargar", args=[registro.pk, "xlsx"])).content.startswith(b"PK"))
        self.assertEqual(self.client.get(reverse("admin:operacion_informeenviado_descargar", args=[registro.pk, "docx"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("admin:operacion_informeenviado_change", args=[registro.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:operacion_informeenviado_add")).status_code, 403)  # el registro de auditoría no se crea a mano

    def test_los_demas_roles_no_gestionan_los_destinatarios(self):
        from django.contrib.auth.models import Group
        especialista = get_user_model().objects.create_user("esp_correo", password="x", is_staff=True)
        especialista.groups.add(Group.objects.get(name="Especialista"))
        self.client.force_login(especialista)
        self.assertEqual(self.client.get(reverse("admin:operacion_destinatarioinforme_changelist")).status_code, 403)
