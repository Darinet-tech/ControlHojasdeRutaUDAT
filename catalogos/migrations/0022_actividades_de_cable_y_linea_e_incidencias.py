from django.db import migrations


def aplicar(apps, schema_editor):
    modelo = lambda n: apps.get_model("catalogos", n)  # noqa: E731
    # Incidencias (AT-1 de la instrucción): 105, 107, 111 y 112 cuentan como tiempo efectivo, es decir, no descuentan tiempo.
    causas = modelo("CausaIncidencia")
    causas.objects.filter(codigo__in=["105", "107"]).update(descuenta_tiempo=False)
    for codigo, nombre in (("111", "Tiempo de poda"), ("112", "Tiempo trasladado")):
        causas.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre, "descuenta_tiempo": False})


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0021_campos_de_las_actividades")]

    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
