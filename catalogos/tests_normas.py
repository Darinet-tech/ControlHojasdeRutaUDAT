"""Las normas oficiales (instrucción en proceso de firma), el tiempo sin redondear y la regla de inicio de jornada."""
from datetime import date, datetime, time
from importlib import import_module
from unittest import mock

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .campos import leer_norma, texto_norma
from .models import (Brigada, Centro, Clave, NormaMantenimiento, NormaTiempo, NormaTipoOrden, Operario, TipoMantenimiento, TipoOrden)

HOY = date(2026, 11, 26)


class CampoDeNormaTests(TestCase):
    def test_se_escribe_y_se_muestra_en_minutos_y_segundos(self):
        for texto in ("24", "48:34", "0,42", "1:30", "16:18"):
            self.assertEqual(texto_norma(float(leer_norma(texto))), texto)
        self.assertEqual(texto_norma(49.0), "49")
        for malo in ("abc", "10:75", "-1", ""):
            with self.assertRaises(ValidationError):
                leer_norma(malo)


class NormasOficialesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_inicial", verbosity=0)

    def orden(self, codigo):
        return texto_norma(NormaTipoOrden.vigente(TipoOrden.objects.get(codigo=codigo), HOY).minutos)

    def clave(self, codigo):
        return texto_norma(NormaTiempo.vigente(Clave.objects.get(codigo=codigo), None, HOY).minutos)

    def test_tipos_de_orden_sin_redondear(self):
        esperado = {"A": "48:34", "AE": "48:34", "TA": "48:34", "TI": "48:34", "TE": "70:20", "B": "23:21", "BS": "17:24", "CPU": "21:30",
                    "CL": "29:19", "CMONT": "29:19", "CMIS": "29:19", "CA": "29:19", "CVIV": "23:42", "CTS": "24", "CD": "24",
                    "AS": "30:29", "REC": "30:29"}
        self.assertEqual({c: self.orden(c) for c in esperado}, esperado)

    def test_preventivos_y_claves(self):
        mant = {t.codigo: NormaMantenimiento.vigente(t, HOY) for t in TipoMantenimiento.objects.all()}
        self.assertEqual(texto_norma(mant.pop("GAB").minutos), "50")  # por regleta trabajada
        self.assertEqual({c: texto_norma(n.minutos) for c, n in mant.items() if n}, {"MPI": "40", "MPPI": "24:02", "MPPE": "27:48", "MTP": "22:47"})
        self.assertEqual([self.clave(c) for c in ("23", "24", "07-ZC", "07-EC", "21-R", "21-C", "22-G", "26-M")],
                         ["39:46", "39:46", "25:33", "25:33", "22:37", "33:25", "24:27", "96"])  # los de la firmada, no los del borrador V2

    def test_las_normas_nuevas_van_marcadas_en_proceso_de_firma(self):
        self.assertEqual(set(NormaTipoOrden.objects.values_list("nota", flat=True)), {"IT-OR-001/24 (válida hasta 16/7/2026)"})
        self.assertEqual(NormaTiempo.objects.filter(nota="IT-OR-001/24 (válida hasta 16/7/2026)").count(), 68)

    def test_cpu_va_en_la_fila_de_cviv_y_bs_en_la_de_bajas(self):
        fila = lambda c: TipoOrden.objects.get(codigo=c).fila_parte  # noqa: E731
        self.assertEqual((fila("CPU"), fila("BS")), (fila("CVIV"), fila("B")))
        self.assertEqual(fila("CTS"), fila("CVIV"))

    def test_la_migracion_sustituye_las_normas_anteriores_de_una_base_existente(self):
        clave = Clave.objects.get(codigo="23")
        NormaTiempo.objects.filter(clave=clave).update(minutos=60, nota="")
        NormaTiempo.objects.create(clave=clave, minutos=70, vigente_desde=date(2026, 11, 1))
        otra = NormaTiempo.objects.get(clave__codigo="70")  # no está en la instrucción: conserva la suya
        antes = otra.minutos
        import_module("catalogos.migrations.0015_normas_instruccion_2026").aplicar(apps, None)
        self.assertEqual([texto_norma(n.minutos) for n in NormaTiempo.objects.filter(clave=clave)], ["39:46"])
        self.assertEqual(NormaTiempo.objects.get(clave__codigo="70").minutos, antes)


class InicioDeJornadaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_inicial", verbosity=0)
        cls.rep = Brigada.objects.get(nombre="Red de Abonados")
        cls.ng = Centro.objects.get(codigo="NG")
        cls.op = Operario.objects.create(clave="J1", nombre="Operario Jornada", brigada=cls.rep)
        cls.probador = get_user_model().objects.create_user("probador_j")
        cls.probador.groups.add(Group.objects.get(name="Probador"))

    def crear(self, hh, mm, **extra):
        api = APIClient()
        api.force_authenticate(self.probador)
        ahora = timezone.make_aware(datetime.combine(timezone.localdate(), time(hh, mm, 20)))
        with mock.patch("django.utils.timezone.now", return_value=ahora):
            return api, api.post("/api/hojas/", {"brigada": self.rep.pk, "centros": [self.ng.pk], "operarios": [self.op.pk], **extra}, format="json")

    def test_creada_antes_o_a_las_ocho_cuenta_desde_las_ocho_sin_justificar(self):
        for hh, mm in ((7, 15), (8, 0)):
            _, r = self.crear(hh, mm, justificacion_inicio="no hace falta")
            self.assertEqual((r.status_code, r.data["hora_inicio"], r.data["justificacion_inicio"]), (201, "08:00:00", ""), r.data)
            from operacion.models import HojaDeRuta
            HojaDeRuta.objects.all().delete()

    def test_creada_despues_exige_justificacion_y_cuenta_desde_ese_momento(self):
        _, r = self.crear(9, 15)
        self.assertEqual(r.status_code, 400)
        self.assertIn("La jornada comienza a las 08:00", str(r.data))
        _, r = self.crear(9, 15, justificacion_inicio="   ")
        self.assertEqual(r.status_code, 400)
        api, r = self.crear(9, 15, justificacion_inicio="Vehículo roto")
        self.assertEqual((r.status_code, r.data["hora_inicio"], r.data["justificacion_inicio"]), (201, "09:15:20", "Vehículo roto"), r.data)
        r = api.patch(f"/api/hojas/{r.data['id']}/", {"justificacion_inicio": "otra"}, format="json")  # no se reescribe después
        self.assertEqual((r.status_code, r.data["justificacion_inicio"]), (200, "Vehículo roto"))


class ClavesFrenteALaInstruccionFirmadaTests(TestCase):
    """Total de cada clave en el escaneo de la IT-OR-001/24 (leído página por página). Detecta que se cargue otra cosa (p. ej. el borrador V2)."""

    FIRMADA = {
        "01-C": "19:00", "02-C": "19:00", "01-R": "18:29", "24": "39:46", "23": "39:46", "23-C": "31:56", "24-C": "31:56", "09-C": "11:12",
        "21-R": "22:37", "21": "22:37", "22-G": "24:27", "27-G": "16:47", "36": "9:53", "39": "9:53", "25": "15:00", "37": "15:00",
        "07-ZC": "25:33", "07-EC": "25:33", "07-EP": "16:02", "07-IC": "17:53", "21-C": "33:25", "25-C": "46:06", "26-T": "46:06",
        "25-R": "27:27", "38-R": "27:27", "35-A": "9:16", "08-FA": "15:00", "60-A": "31:41", "15-Z": "25:00", "26-M": "96:00",
        "39-FA": "8:00", "14-R": "16:57", "14-RD": "7:37", "10DQ-TXD": "24:27", "1DMC-TXD": "43:51", "27RI-TXD": "74:00",
        "36D-TXD": "9:53", "9DI-TXD": "74:00",
    }

    def test_las_normas_cargadas_son_las_de_la_firmada(self):
        call_command("cargar_inicial", verbosity=0)
        cargadas = {c: texto_norma(NormaTiempo.vigente(Clave.objects.get(codigo=c), None, HOY).minutos) for c in self.FIRMADA}
        esperadas = {c: texto_norma(float(leer_norma(t))) for c, t in self.FIRMADA.items()}
        self.assertEqual(cargadas, esperadas)

    def test_el_error_del_borrador_no_se_repite(self):
        """Ninguna clave puede quedar 24 minutos por debajo de la firmada (el borrador V2 perdía 24 al pasar de 24 «horas»)."""
        call_command("cargar_inicial", verbosity=0)
        for codigo, texto in self.FIRMADA.items():
            minutos = NormaTiempo.vigente(Clave.objects.get(codigo=codigo), None, HOY).minutos
            self.assertGreater(minutos, 24 * 0 + 5, codigo)
            self.assertAlmostEqual(minutos, float(leer_norma(texto)), places=3, msg=codigo)
