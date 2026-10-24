from django.db import migrations


class Migration(migrations.Migration):
    """Paso 3 de 3: se elimina el campo de centro único, ya copiado a la lista de centros."""

    dependencies = [("operacion", "0007_copiar_centro_de_las_hojas")]
    operations = [migrations.RemoveField("hojaderuta", "centro")]
