from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 1 de 3: agrega los códigos de centro y de causa de incidencia (todavía opcionales)."""

    dependencies = [("catalogos", "0002_decisiones_negocio")]
    operations = [
        migrations.AddField("centro", "codigo", models.CharField(max_length=5, null=True, unique=True)),
        migrations.AddField("causaincidencia", "codigo", models.CharField(max_length=5, null=True, unique=True)),
        migrations.AddField("causaincidencia", "descuenta_tiempo", models.BooleanField(default=True)),
    ]
