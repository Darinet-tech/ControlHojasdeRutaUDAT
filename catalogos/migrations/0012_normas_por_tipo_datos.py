from django.db import migrations

from catalogos.normas_tipo import crear


def aplicar(apps, schema_editor):
    crear(apps.get_model("catalogos", "TipoOrden"), apps.get_model("catalogos", "TipoMantenimiento"),
          apps.get_model("catalogos", "NormaTipoOrden"), apps.get_model("catalogos", "NormaMantenimiento"))


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0011_normas_por_tipo")]
    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
