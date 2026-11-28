from django.db import migrations


class Migration(migrations.Migration):
    """La forma de medir cada trabajo y los tipos de caja terminal se cargaron aquí en su día. Ahora lo hace la migración 0022 (que ya tiene
    los campos de las actividades) y `cargar_inicial`; este paso quedó vacío para que una base nueva no dependa de campos que aún no existen."""

    dependencies = [("catalogos", "0018_opciondetrabajo_and_more")]

    operations = []
