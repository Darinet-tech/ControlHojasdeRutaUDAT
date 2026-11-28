from django.db import migrations

from catalogos.normas_2026 import sustituir_normas


def aplicar(apps, schema_editor):
    """Pone las normas de la instrucción firmada IT-OR-001/24 en una base que tenía las del borrador V2."""
    modelo = lambda n: apps.get_model("catalogos", n)  # noqa: E731
    sustituir_normas(*(modelo(n) for n in ("Clave", "TipoOrden", "TipoMantenimiento", "NormaTiempo", "NormaTipoOrden", "NormaMantenimiento")))


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0019_medida_de_los_trabajos")]

    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
