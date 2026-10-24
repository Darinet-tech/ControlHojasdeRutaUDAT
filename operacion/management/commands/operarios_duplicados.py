"""Lista los operarios que aparecen en más de una hoja de ruta el mismo día (datos creados antes de la regla)."""
from collections import defaultdict

from django.core.management.base import BaseCommand

from operacion.models import HojaDeRuta


class Command(BaseCommand):
    help = "Muestra operarios repetidos en hojas de ruta de un mismo día, para corregirlos desde la administración."

    def handle(self, *args, **opts):
        por_dia = defaultdict(list)
        for hoja in HojaDeRuta.objects.select_related("brigada").prefetch_related("operarios", "centros"):
            for operario in hoja.operarios.all():
                por_dia[(operario, hoja.fecha)].append(hoja)
        repetidos = {k: v for k, v in por_dia.items() if len(v) > 1}
        if not repetidos:
            self.stdout.write(self.style.SUCCESS("No hay operarios repetidos en un mismo día."))
            return
        for (operario, fecha), hojas in sorted(repetidos.items(), key=lambda x: (x[0][1], x[0][0].nombre)):
            donde = "; ".join(f"hoja {h.pk} ({h.etiqueta_centros} · {h.brigada.nombre})" for h in hojas)
            self.stdout.write(f"{fecha:%d/%m/%Y}  {operario.nombre}: {donde}")
        self.stdout.write(self.style.WARNING(f"\n{len(repetidos)} caso(s). Quite al operario de las hojas que sobren en /admin."))
