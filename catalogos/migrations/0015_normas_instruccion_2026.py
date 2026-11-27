from django.db import migrations

from catalogos.normas_2026 import crear_tipos_nuevos, sustituir_normas


def aplicar(apps, schema_editor):
    modelo = lambda nombre: apps.get_model("catalogos", nombre)  # noqa: E731
    if modelo("TipoOrden").objects.exists():  # en una base recién creada lo hace después cargar_inicial
        crear_tipos_nuevos(modelo("TipoOrden"))
    sustituir_normas(*(modelo(n) for n in ("Clave", "TipoOrden", "TipoMantenimiento", "NormaTiempo", "NormaTipoOrden", "NormaMantenimiento")))


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0014_normas_sin_redondeo")]

    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
