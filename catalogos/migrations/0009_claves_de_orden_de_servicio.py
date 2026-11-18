from django.db import migrations

from catalogos.claves_orden import crear


def aplicar(apps, schema_editor):
    crear(apps.get_model("catalogos", "Clave"), apps.get_model("catalogos", "GrupoClave"))


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0008_filas_del_parte_datos")]
    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
