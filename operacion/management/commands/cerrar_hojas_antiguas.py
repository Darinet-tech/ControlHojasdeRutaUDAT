"""Cierra las hojas de ruta que siguen abiertas pasada la hora de cierre (21:00 por defecto) o de días anteriores."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from operacion.models import HojaDeRuta
from operacion.services import cerrar_hoja, momento_de_cierre_automatico


class Command(BaseCommand):
    help = ("Cierra las hojas abiertas de días anteriores y las de hoy si ya pasó la hora de cierre (HORA_CIERRE_AUTOMATICO): "
            "sus servicios sin cerrar pasan a NO VISITADOS y los contadores de incidencia se detienen a esa hora.")

    def add_arguments(self, parser):
        parser.add_argument("--simular", action="store_true", help="Solo mostrar qué hojas se cerrarían")

    def handle(self, *args, **opciones):
        ahora = timezone.localtime()
        hoy = ahora.date()
        pasada_la_hora = ahora.time() >= settings.HORA_CIERRE_AUTOMATICO
        filtro = Q(fecha__lt=hoy) | (Q(fecha=hoy) if pasada_la_hora else Q(pk__in=[]))
        gracia = ahora - timedelta(hours=settings.HORAS_GRACIA_REAPERTURA)  # las hojas recién reabiertas se respetan
        hojas = (HojaDeRuta.objects.filter(cerrada=False).filter(filtro)
                 .exclude(reabierta_en__gt=gracia))
        hojas = hojas.select_related("brigada").prefetch_related("centros").order_by("fecha")
        if not hojas:
            self.stdout.write("No hay hojas abiertas que cerrar.")
            return
        for hoja in hojas:
            # el cierre se registra a la hora de cierre del día de la hoja, aunque la tarea corra más tarde
            momento = momento_de_cierre_automatico(hoja.fecha)
            sin_cerrar = hoja.acciones.filter(hora_fin__isnull=True, no_visitada=False).count()
            texto = f"{hoja} ({sin_cerrar} servicio(s) sin cerrar)"
            if opciones["simular"]:
                self.stdout.write(f"[SIMULADO] Se cerraría: {texto}")
                continue
            cerrar_hoja(hoja, usuario=None, ahora=momento)
            self.stdout.write(self.style.SUCCESS(f"Cerrada: {texto}"))
