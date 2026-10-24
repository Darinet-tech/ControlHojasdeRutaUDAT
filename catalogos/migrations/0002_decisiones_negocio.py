"""Aplica decisiones del negocio a bases ya creadas con la versión anterior (en una base nueva no hace nada).

- Se eliminan las claves 09-R, 39-W y 63-X.
- 36-V y 36D-TXD son no efectivas (misma familia que la 36).
- 11DW-TXD, 1DMC-TXD y 3DS-TXD quedan solo en el grupo Datos.
"""
from django.db import migrations

ELIMINAR = ["09-R", "39-W", "63-X"]
NO_EFECTIVAS = ["36-V", "36D-TXD"]
SOLO_DATOS = ["11DW-TXD", "1DMC-TXD", "3DS-TXD"]


def aplicar_decisiones(apps, schema_editor):
    Clave = apps.get_model("catalogos", "Clave")
    GrupoClave = apps.get_model("catalogos", "GrupoClave")
    Clave.objects.filter(codigo__in=ELIMINAR).delete()
    Clave.objects.filter(codigo__in=NO_EFECTIVAS).update(clasificacion="NO_EFECTIVA", revisar=False)
    if Clave.objects.filter(codigo__in=SOLO_DATOS).exists():
        datos, _ = GrupoClave.objects.get_or_create(nombre="Datos")
        Clave.objects.filter(codigo__in=SOLO_DATOS).update(grupo=datos, notas="", revisar=False)


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0001_initial")]
    operations = [migrations.RunPython(aplicar_decisiones, migrations.RunPython.noop)]
