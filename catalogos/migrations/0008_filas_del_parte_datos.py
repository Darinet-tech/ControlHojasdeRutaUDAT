from django.db import migrations

from catalogos.parte_datos import completar


def aplicar(apps, schema_editor):
    completar(apps.get_model("catalogos", "Clave"), apps.get_model("catalogos", "TipoOrden"), apps.get_model("catalogos", "TipoMantenimiento"))


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0007_filas_del_parte")]
    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
