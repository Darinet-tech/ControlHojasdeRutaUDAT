"""Envía por correo el informe del día (PDF y Excel) con el corte de la hora actual. Se programa a las 16:00."""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from operacion.correo import enviar_informe_diario


class Command(BaseCommand):
    help = "Envía el informe diario a los destinatarios definidos por el administrador (desde la cuenta del jefe de la UDAT)."

    def add_arguments(self, parser):
        parser.add_argument("--fecha", help="AAAA-MM-DD (por defecto, hoy)")
        parser.add_argument("--forzar", action="store_true", help="Enviar aunque el informe de ese día ya se haya enviado")
        parser.add_argument("--simular", action="store_true", help="Solo mostrar qué se enviaría, sin enviar ni registrar nada")

    def handle(self, *args, **opciones):
        fecha = date.fromisoformat(opciones["fecha"]) if opciones["fecha"] else None
        estado, mensaje, _ = enviar_informe_diario(fecha=fecha, forzar=opciones["forzar"], simular=opciones["simular"])
        if estado == "ERROR":
            raise CommandError(mensaje)  # código de salida distinto de cero: el planificador lo marca como fallido
        self.stdout.write(self.style.SUCCESS(f"[{estado}] {mensaje}") if estado in ("ENVIADO", "SIMULADO") else f"[{estado}] {mensaje}")
