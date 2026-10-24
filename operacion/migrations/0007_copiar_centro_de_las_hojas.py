"""Paso 2 de 3: cada hoja existente pasa a tener su centro en la nueva lista, y cada servicio ya registrado
queda en el centro de su hoja (en una base nueva no hace nada)."""
from django.db import migrations


def copiar(apps, schema_editor):
    Hoja = apps.get_model("operacion", "HojaDeRuta")
    Accion = apps.get_model("operacion", "Accion")
    for hoja in Hoja.objects.all():
        hoja.centros.add(hoja.centro_id)
        Accion.objects.filter(hoja=hoja, centro__isnull=True).update(centro_id=hoja.centro_id)


class Migration(migrations.Migration):
    dependencies = [("operacion", "0006_centros_multiples")]
    operations = [migrations.RunPython(copiar, migrations.RunPython.noop)]
