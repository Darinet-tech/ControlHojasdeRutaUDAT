from django.db import migrations

from catalogos import trabajos

DE_PRUEBA = ["Sustitución de poste(s)", "Sustitución de caja(s) terminal(es)", "Sustitución de cable de cobre"]


def aplicar(apps, schema_editor):
    tipos = apps.get_model("catalogos", "TipoTrabajo")
    # Se crearon para probar la aplicación; ahora se usan las actividades de la instrucción.
    de_prueba = tipos.objects.filter(especialidad="", nombre__in=DE_PRUEBA)
    apps.get_model("operacion", "CantidadDeTrabajo").objects.filter(trabajo__in=de_prueba).delete()
    de_prueba.delete()
    trabajos.cargar_actividades(tipos, apps.get_model("catalogos", "NormaTrabajo"))  # Cable, Línea y Fibra Óptica


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0022_actividades_de_cable_y_linea_e_incidencias"), ("operacion", "0018_cantidaddetrabajo")]

    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
