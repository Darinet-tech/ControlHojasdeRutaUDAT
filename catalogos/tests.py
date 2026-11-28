import importlib
from datetime import date

from django.apps import apps

from django.core.management import call_command
from django.test import TestCase

from .models import Brigada, CausaIncidencia, Centro, Clave, NormaTiempo, TipoOrden


class CargaInicialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_inicial", verbosity=0)

    def test_claves_unicas_y_clasificacion(self):
        # 183 filas del PDF: -3 repetidas (se conserva la de Datos) -3 eliminadas por el negocio
        self.assertEqual(Clave.objects.count(), 189)  # 177 de reparación + 12 de orden de servicio
        reparacion = Clave.objects.filter(ambito="ACCION")  # las claves de orden de servicio (1 a 19) son otro catálogo
        no_efectivas = set(reparacion.filter(clasificacion="NO_EFECTIVA").values_list("codigo", flat=True))
        self.assertEqual(no_efectivas, {"01", "02", "14-P", "21", "22", "23", "24", "25", "27", "29", "36", "36-V",
                                        "36D-TXD", "37", "38", "39", "70"})
        self.assertEqual(reparacion.filter(clasificacion="PENDIENTE").count(), 0)
        self.assertEqual(reparacion.filter(clasificacion="EFECTIVA").count(), 160)
        self.assertEqual(Brigada.objects.count(), 5)

    def test_claves_eliminadas_y_repetidas(self):
        for codigo in ("09-R", "39-W", "63-X"):
            self.assertFalse(Clave.objects.filter(codigo=codigo).exists())
        for codigo in ("11DW-TXD", "1DMC-TXD", "3DS-TXD"):
            self.assertEqual(Clave.objects.get(codigo=codigo).grupo.nombre, "Datos")

    def test_solo_quedan_por_revisar_las_reclasificadas(self):
        revisar = set(Clave.objects.filter(revisar=True).values_list("codigo", flat=True))
        self.assertEqual(revisar, {"07-EP", "07-IP", "08", "09", "35-D"})

    def test_tipos_de_orden(self):
        self.assertEqual(TipoOrden.objects.count(), 17)  # incluye CMIS, CD y CA, del parte diario, y CPU y BS, de la instrucción de normas
        self.assertEqual(TipoOrden.objects.get(codigo="CMONT").nombre, "Cambio de montaje")

    def test_causas_de_incidencia_oficiales(self):
        causas = dict(CausaIncidencia.objects.values_list("codigo", "nombre"))
        self.assertEqual(causas, {
            "100": "Lluvia", "101": "Traslado de personal", "102": "Esperando materiales",
            "105": "Esperando por probador", "106": "Problemas con el transporte",
            "107": "Realizando actividades comerciales", "108": "Otras causas", "110": "Autorizado por el jefe"})
        self.assertTrue(all(c.descuenta_tiempo for c in CausaIncidencia.objects.all()))

    def test_centros_con_codigo(self):
        self.assertEqual(dict(Centro.objects.values_list("codigo", "nombre")),
                         {"NG": "Nueva Gerona", "FI": "La Fé", "FO": "La Reforma"})
        self.assertEqual(str(Centro.objects.get(codigo="NG")), "Nueva Gerona (NG)")

    def test_normas_importadas(self):
        self.assertEqual(NormaTiempo.vigente(Clave.objects.get(codigo="25-R"), None, date(2026, 10, 1)).minutos, 27.45)  # 27:27 en la instrucción firmada
        self.assertEqual(NormaTiempo.objects.count(), 177)

    def test_es_idempotente(self):
        call_command("cargar_inicial", verbosity=0)
        self.assertEqual(Clave.objects.count(), 189)  # 177 de reparación + 12 de orden de servicio
        self.assertEqual(NormaTiempo.objects.count(), 177)


class MigracionDecisionesTests(TestCase):
    """Una base creada con la versión anterior queda corregida al ejecutar `migrate`."""

    def test_corrige_una_base_con_el_estado_anterior(self):
        from .models import GrupoClave

        rep, datos = GrupoClave.objects.create(nombre="Reparador"), GrupoClave.objects.create(nombre="Datos")
        for codigo, grupo, clas in [("09-R", rep, "EFECTIVA"), ("63-X", datos, "EFECTIVA"),
                                    ("36-V", rep, "PENDIENTE"), ("36D-TXD", datos, "EFECTIVA"),
                                    ("3DS-TXD", rep, "EFECTIVA")]:
            Clave.objects.create(codigo=codigo, grupo=grupo, clasificacion=clas, revisar=True, notas="x")
        modulo = importlib.import_module("catalogos.migrations.0002_decisiones_negocio")
        modulo.aplicar_decisiones(apps, None)
        self.assertEqual(set(Clave.objects.filter(ambito="ACCION").values_list("codigo", flat=True)), {"36-V", "36D-TXD", "3DS-TXD"})
        self.assertEqual(Clave.objects.get(codigo="36-V").clasificacion, "NO_EFECTIVA")
        self.assertEqual(Clave.objects.get(codigo="36D-TXD").clasificacion, "NO_EFECTIVA")
        dup = Clave.objects.get(codigo="3DS-TXD")
        self.assertEqual((dup.grupo.nombre, dup.notas, dup.revisar), ("Datos", "", False))


class NormaVigenciaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_inicial", verbosity=0)
        cls.clave = Clave.objects.get(codigo="25-R")
        cls.tipo = TipoOrden.objects.create(nombre="Avería")

    def test_norma_especifica_tiene_prioridad(self):
        NormaTiempo.objects.create(clave=self.clave, tipo_orden=self.tipo, minutos=60, vigente_desde=date(2026, 1, 1))
        self.assertEqual(NormaTiempo.vigente(self.clave, self.tipo, date(2026, 10, 1)).minutos, 60)
        self.assertEqual(NormaTiempo.vigente(self.clave, None, date(2026, 10, 1)).minutos, 27.45)

    def test_cambio_de_norma_no_altera_el_pasado(self):
        NormaTiempo.objects.filter(clave=self.clave).update(vigente_hasta=date(2026, 6, 30))
        NormaTiempo.objects.create(clave=self.clave, minutos=50, vigente_desde=date(2026, 7, 1))
        self.assertEqual(NormaTiempo.vigente(self.clave, None, date(2026, 6, 15)).minutos, 27.45)
        self.assertEqual(NormaTiempo.vigente(self.clave, None, date(2026, 7, 15)).minutos, 50)


class ProteccionDeClavesTests(TestCase):
    """El administrador puede crear, modificar y eliminar claves, salvo las que ya tienen historial."""

    @classmethod
    def setUpTestData(cls):
        call_command("cargar_inicial", verbosity=0)

    def setUp(self):
        from django.contrib import admin
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory

        self.admin = admin.site._registry[Clave]
        self.request = RequestFactory().get("/")
        self.request.user = get_user_model().objects.create_superuser("adm", "a@a.cu", "x")

    def test_clave_sin_uso_se_puede_eliminar_y_crear(self):
        nueva = Clave.objects.create(codigo="99-X", grupo=Clave.objects.get(codigo="25-R").grupo, clasificacion="EFECTIVA")
        NormaTiempo.objects.create(clave=nueva, minutos=30, vigente_desde=date(2026, 1, 1))
        self.assertTrue(self.admin.has_delete_permission(self.request, nueva))
        nueva.delete()
        self.assertFalse(Clave.objects.filter(codigo="99-X").exists())

    def test_clave_usada_en_una_accion_no_se_puede_eliminar(self):
        from datetime import date as d

        from operacion.models import Accion, HojaDeRuta, OrdenServicio

        centro = Centro.objects.get(codigo="NG")
        hoja = HojaDeRuta.objects.create(fecha=d(2026, 10, 1), brigada=Brigada.objects.first())
        hoja.centros.set([centro])
        accion = Accion.objects.create(hoja=hoja, orden=OrdenServicio.objects.create(numero_servicio="46 1"))
        clave = Clave.objects.get(codigo="25-R")
        accion.claves.add(clave)
        self.assertFalse(self.admin.has_delete_permission(self.request, clave))
        self.assertNotIn("delete_selected", self.admin.get_actions(self.request))


class CatalogoDeClavesDeOrdenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        call_command("cargar_inicial", verbosity=0)
        cls.admin = get_user_model().objects.create_superuser("adm", "a@a.cu", "x")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_seccion_propia_en_la_administracion(self):
        r = self.client.get("/admin/catalogos/claveordenservicio/")
        self.assertContains(r, "Casa cerrada")
        self.assertNotContains(r, "25-R")  # las de reparación no están aquí
        self.assertNotContains(self.client.get("/admin/catalogos/clave/"), "Casa cerrada")  # ni estas en el catálogo de reparación

    def test_una_clave_nueva_de_orden_queda_en_su_ambito(self):
        r = self.client.post("/admin/catalogos/claveordenservicio/add/", {"codigo": "20", "descripcion": "Otra", "clasificacion": "NO_EFECTIVA",
                                                                        "activa": "on", "notas": ""})
        self.assertEqual(r.status_code, 302)
        nueva = Clave.objects.get(codigo="20")
        self.assertEqual((nueva.ambito, nueva.grupo.nombre), ("ORDEN", "Orden de servicio"))

    def test_los_roles_ven_el_catalogo(self):
        from django.contrib.auth.models import Group
        self.assertTrue(Group.objects.get(name="Especialista").permissions.filter(codename="change_claveordenservicio").exists())
        self.assertTrue(Group.objects.get(name="Probador").permissions.filter(codename="view_claveordenservicio").exists())

