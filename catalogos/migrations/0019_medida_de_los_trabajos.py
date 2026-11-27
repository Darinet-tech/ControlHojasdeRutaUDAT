from django.db import migrations

from catalogos.trabajos import configurar


def aplicar(apps, schema_editor):
    configurar(apps.get_model("catalogos", "TipoTrabajo"), apps.get_model("catalogos", "OpcionDeTrabajo"), apps.get_model("catalogos", "NormaTrabajo"))


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0018_opciondetrabajo_and_more")]

    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
