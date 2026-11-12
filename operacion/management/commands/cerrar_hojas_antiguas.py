"""Cierra las hojas de ruta de días anteriores que nadie cerró (se programa cada noche, p. ej. a las 00:05)."""
from datetime import datetime, time

from django.core.management.base import BaseCommand
from django.utils import timezone

from operacion.models import HojaDeRuta
from operacion.services import cerrar_hoja


class Command(BaseCommand):
    help = ("Cierra las hojas abiertas con fecha anterior a hoy: sus servicios sin cerrar pasan a NO VISITADOS y los contadores "
            "de incidencia se detienen al final del día de la hoja.")

    def add_arguments(self, parser):
        parser.add_argument("--simular", action="store_true", help="Solo mostrar qué hojas se cerrarían")

    def handle(self, *args, **opciones):
        hoy = timezone.localdate()
        hojas = HojaDeRuta.objects.filter(cerrada=False, fecha__lt=hoy).select_related("brigada").prefetch_related("centros").order_by("fecha")
        if not hojas:
            self.stdout.write("No hay hojas antiguas abiertas.")
            return
        for hoja in hojas:
            # el cierre se registra al final del día de la hoja, para que una incidencia activa no cuente días de más
            fin_del_dia = timezone.make_aware(datetime.combine(hoja.fecha, time(23, 59, 59)))
            sin_cerrar = hoja.acciones.filter(hora_fin__isnull=True, no_visitada=False).count()
            texto = f"{hoja} ({sin_cerrar} servicio(s) sin cerrar)"
            if opciones["simular"]:
                self.stdout.write(f"[SIMULADO] Se cerraría: {texto}")
                continue
            cerrar_hoja(hoja, usuario=None, ahora=fin_del_dia)
            self.stdout.write(self.style.SUCCESS(f"Cerrada: {texto}"))
