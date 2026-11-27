from django.db import migrations

from catalogos.normas_2026 import GAB_POR_REGLETA, INICIO, NOTA_GAB, minutos


def aplicar(apps, schema_editor):
    gabinete = apps.get_model("catalogos", "TipoMantenimiento").objects.filter(codigo="GAB").first()
    normas = apps.get_model("catalogos", "NormaMantenimiento")
    if gabinete and not normas.objects.filter(tipo_mantenimiento=gabinete).exists():  # no pisa la que haya puesto el administrador
        normas.objects.create(tipo_mantenimiento=gabinete, minutos=minutos(GAB_POR_REGLETA), vigente_desde=INICIO, nota=NOTA_GAB)


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0015_normas_instruccion_2026")]

    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
