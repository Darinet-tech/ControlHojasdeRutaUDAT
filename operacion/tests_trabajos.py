"""Órdenes de trabajo: el probador anota la cantidad (postes, metros) o el tipo (caja terminal) y la norma se calcula sumando los trabajos."""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from catalogos.models import NormaTrabajo, OpcionDeTrabajo, TipoTrabajo
from catalogos import normas_de_prueba, trabajos as configuracion

from .models import CantidadDeTrabajo
from .parte import parte_diario
from .reportes import resumen_periodo
from .services import asignar_orden, certificar_ok, norma_accion, obtener_orden, resumen_hoja
from .tests import BaseOperacion

DIA = date(2026, 10, 5)


class OrdenesDeTrabajoPorCantidadTests(BaseOperacion):
    def setUp(self):
        self.poste = TipoTrabajo.objects.get(nombre="Sustitución de poste(s)")
        self.cable = TipoTrabajo.objects.get(nombre="Sustitución de cable de cobre")
        self.caja = normas_de_prueba.trabajo_por_tipo()
        NormaTrabajo.objects.create(tipo_trabajo=self.poste, minutos=110, vigente_desde=date(2026, 1, 1))  # por poste
        NormaTrabajo.objects.create(tipo_trabajo=self.cable, minutos=0.5, vigente_desde=date(2026, 1, 1))  # por metro
        self.hoja_x = self.hoja(fecha=DIA)
        self.api = APIClient()
        self.api.force_authenticate(get_user_model().objects.create_superuser("adm_ot", "a@a.cu", "x"))

    def ot(self, numero, *trabajos):
        orden = obtener_orden("ORDEN_TRABAJO", self.user, numero_orden=numero, trabajos=list(trabajos))
        return asignar_orden(self.hoja_x, orden, self.user, trabajos=list(trabajos))

    def patch(self, accion, **datos):
        return self.api.patch(f"/api/acciones/{accion.pk}/", datos, format="json")

    def test_cada_trabajo_dice_como_se_mide(self):
        medidas = {t["nombre"]: (t["medida"], t["unidad"], [o["nombre"] for o in t["opciones"]]) for t in self.api.get("/api/tipos-trabajo/").data}
        self.assertEqual(medidas["Sustitución de poste(s)"], ("UNIDADES", "poste(s)", []))
        self.assertEqual(medidas["Sustitución de cable de cobre"], ("METROS", "metro(s)", []))
        self.assertEqual(medidas["Sustitución de caja(s) terminal(es)"], ("UNIDADES", "caja(s)", []))  # como en la instrucción (Cable 18: 70 min)
        self.assertEqual(medidas["Sustitución de caja por tipo (prueba)"], ("TIPO", "", ["Con cola", "Multiservicios"]))

    def test_postes_y_metros_se_multiplican_por_la_cantidad(self):
        a = self.ot("9001", self.poste, self.cable)
        r = self.patch(a, cantidades=[{"trabajo": self.poste.pk, "cantidad": 3}, {"trabajo": self.cable.pk, "cantidad": "12,5"}])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["norma_min"], 3 * 110 + 12.5 * 0.5)  # suma de los dos trabajos
        self.assertEqual({d["trabajo"]: (d["cantidad"], d["norma_min"]) for d in r.data["detalle_trabajos"]},
                         {self.poste.pk: (3, 330), self.cable.pk: (12.5, 6.25)})
        self.assertEqual(self.patch(a, cantidades=[{"trabajo": self.poste.pk, "cantidad": 5}]).data["norma_min"], 5 * 110 + 6.25)  # cambia solo ese

    def test_valida_lo_que_se_anota(self):
        a = self.ot("9002", self.poste, self.caja)
        malos = [{"trabajo": self.poste.pk, "cantidad": 0}, {"trabajo": self.poste.pk, "cantidad": 2.5}, {"trabajo": self.poste.pk, "cantidad": "x"},
                 {"trabajo": self.poste.pk, "cantidad": 100001}, {"trabajo": self.caja.pk, "opcion": 999999}, {"trabajo": self.cable.pk, "cantidad": 2}]
        for malo in malos:
            self.assertEqual(self.patch(a, cantidades=[malo]).status_code, 400, malo)
        self.assertFalse(CantidadDeTrabajo.objects.exists())

    def test_quitar_un_trabajo_borra_lo_anotado(self):
        a = self.ot("9003", self.poste, self.cable)
        self.patch(a, cantidades=[{"trabajo": self.poste.pk, "cantidad": 2}, {"trabajo": self.cable.pk, "cantidad": 30}])
        self.patch(a, trabajos=[self.cable.pk])
        self.assertEqual(list(a.cantidades.values_list("trabajo__nombre", flat=True)), ["Sustitución de cable de cobre"])

    def test_no_se_da_ok_sin_la_cantidad_y_despues_no_pide_cliente(self):
        a = self.ot("9004", self.poste, self.cable, self.caja)
        r = self.api.get(f"/api/acciones/{a.pk}/").data
        self.assertEqual(sorted(r["trabajos_incompletos"]), sorted([self.poste.pk, self.cable.pk, self.caja.pk]))
        with self.assertRaisesMessage(ValidationError, "la cantidad de sustitución de poste(s)"):
            certificar_ok(a, self.user, "")
        opcion = OpcionDeTrabajo.objects.get(tipo_trabajo=self.caja, nombre="Multiservicios")
        self.patch(a, cantidades=[{"trabajo": self.poste.pk, "cantidad": 1}, {"trabajo": self.cable.pk, "cantidad": 40},
                                  {"trabajo": self.caja.pk, "opcion": opcion.pk}])
        r = self.api.post(f"/api/acciones/{a.pk}/ok/", {}, format="json")  # sin cliente
        self.assertEqual((r.status_code, r.data["estado"], r.data["norma_min"]), (200, "OK", 110 + 20 + 70))

    def test_los_resumenes_en_bloque_dan_lo_mismo_que_los_de_una_hoja(self):
        a = self.ot("9005", self.poste, self.caja)
        opcion = OpcionDeTrabajo.objects.get(tipo_trabajo=self.caja, nombre="Con cola")
        self.patch(a, cantidades=[{"trabajo": self.poste.pk, "cantidad": 2}, {"trabajo": self.caja.pk, "opcion": opcion.pk}])
        from django.utils import timezone
        from datetime import datetime, time
        certificar_ok(a, self.user, "", ahora=timezone.make_aware(datetime.combine(DIA, time(11, 0))))
        self.assertEqual(resumen_hoja(self.hoja_x)["tiempo_normado_efectivo_min"], 2 * 110 + 100)
        self.assertEqual(resumen_periodo("mes", DIA)["totales"]["tiempo_normado_min"], 2 * 110 + 100)

    def test_el_parte_muestra_la_cantidad_de_cada_trabajo(self):
        a = self.ot("9006", self.poste, self.cable, self.caja)
        opcion = OpcionDeTrabajo.objects.get(tipo_trabajo=self.caja, nombre="Con cola")
        self.patch(a, cantidades=[{"trabajo": self.poste.pk, "cantidad": 3}, {"trabajo": self.cable.pk, "cantidad": 12.5},
                                  {"trabajo": self.caja.pk, "opcion": opcion.pk}])
        texto = parte_diario(DIA)["notas"][0]["texto"]
        for esperado in ("Sustitución de poste(s): 3", "Sustitución de cable de cobre: 12,5 m", "Sustitución de caja por tipo (prueba): Con cola"):
            self.assertIn(esperado, texto)

    def test_la_configuracion_inicial_se_puede_repetir_sin_pisar_cambios(self):
        real = TipoTrabajo.objects.get(nombre="Sustitución de caja(s) terminal(es)")
        NormaTrabajo.objects.filter(tipo_trabajo=real).update(minutos=75)  # el especialista la cambió
        cable31 = TipoTrabajo.objects.get(especialidad="Cable", clave="31")
        NormaTrabajo.objects.filter(tipo_trabajo=cable31).update(minutos=7)
        self.poste.unidad = "postes"
        self.poste.save()
        antes = (TipoTrabajo.objects.count(), NormaTrabajo.objects.count())
        configuracion.configurar(TipoTrabajo, OpcionDeTrabajo, NormaTrabajo)
        self.poste.refresh_from_db()
        self.assertEqual(self.poste.unidad, "postes")  # ya tenía su forma de medirse: no se cambia
        self.assertEqual(NormaTrabajo.objects.get(tipo_trabajo=real).minutos, 75)
        self.assertEqual(NormaTrabajo.objects.get(tipo_trabajo=cable31).minutos, 7)  # no se pisan los cambios
        self.assertEqual((TipoTrabajo.objects.count(), NormaTrabajo.objects.count()), antes)  # y no se duplica nada
