from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 3 de 3: los códigos pasan a ser obligatorios."""

    dependencies = [("catalogos", "0004_codigos_oficiales")]
    operations = [
        migrations.AlterField("centro", "codigo", models.CharField(
            max_length=5, unique=True, help_text="Ej.: NG, FI, FO")),
        migrations.AlterField("causaincidencia", "codigo", models.CharField(max_length=5, unique=True)),
        migrations.AlterField("causaincidencia", "descuenta_tiempo", models.BooleanField(
            default=True, help_text="Si está marcado, el tiempo de esta incidencia no cuenta como tiempo de trabajo.")),
        migrations.AlterModelOptions("causaincidencia", options={
            "ordering": ["codigo"], "verbose_name": "causa de incidencia", "verbose_name_plural": "causas de incidencia"}),
    ]
