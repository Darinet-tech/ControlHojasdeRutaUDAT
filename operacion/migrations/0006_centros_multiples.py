from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Paso 1 de 3: una hoja puede tener varios centros y cada servicio indica el suyo."""

    dependencies = [("catalogos", "0005_codigos_obligatorios"), ("operacion", "0005_hojas_cerradas_antiguas")]
    operations = [
        # el campo anterior se libera del nombre "hojas" mientras conviven los dos
        migrations.AlterField("hojaderuta", "centro", models.ForeignKey(
            on_delete=django.db.models.deletion.PROTECT, related_name="hojas_antiguas", to="catalogos.centro")),
        migrations.AddField("hojaderuta", "centros", models.ManyToManyField(
            help_text="Un vehículo puede trabajar en varios centros en la misma hoja de ruta.",
            related_name="hojas", to="catalogos.centro")),
        migrations.AddField("accion", "centro", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="acciones",
            to="catalogos.centro", help_text="Centro donde está el servicio (uno de los centros de la hoja).")),
    ]
