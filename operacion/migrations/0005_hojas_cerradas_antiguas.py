"""Las hojas cerradas con la versión anterior dejaron servicios 'en curso'. Con la regla nueva, al cerrar la hoja lo que
no se cerró es NO VISITADO: se convierten esos casos para que queden guardados para el siguiente día
(en una base nueva no hace nada)."""
from django.db import migrations


def convertir_a_no_visitadas(apps, schema_editor):
    Accion = apps.get_model("operacion", "Accion")
    for accion in Accion.objects.filter(hoja__cerrada=True, hora_fin__isnull=True, no_visitada=False).select_related("orden", "hoja"):
        accion.no_visitada = True
        accion.save(update_fields=["no_visitada"])
        orden = accion.orden
        if orden.estado == "ABIERTA":
            orden.estado, orden.brigada_pendiente_id = "NO_VISITADA", accion.hoja.brigada_id
            orden.save(update_fields=["estado", "brigada_pendiente"])


class Migration(migrations.Migration):
    dependencies = [("operacion", "0004_no_visitadas")]
    operations = [migrations.RunPython(convertir_a_no_visitadas, migrations.RunPython.noop)]
