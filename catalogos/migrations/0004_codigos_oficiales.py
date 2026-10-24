"""Paso 2 de 3: asigna códigos a lo que ya existe en la base (en una base nueva no hace nada).

- Causas de incidencia: se convierten a las claves oficiales (100 Lluvia, 102 Esperando materiales,
  106 Problemas con el transporte, 108 Otras causas). Cualquier otra causa creada a mano recibe el código X<n>.
- Centros: Nueva Gerona = NG, La Fé = FI, La Reforma = FO. Cualquier otro centro recibe el código provisional C<n>,
  que el administrador debe corregir.
"""
import unicodedata

from django.db import migrations

CAUSAS = {
    "lluvia": ("100", "Lluvia"),
    "falta de material": ("102", "Esperando materiales"),
    "vehiculo en taller": ("106", "Problemas con el transporte"),
    "otra": ("108", "Otras causas"),
}
CENTROS = {"nueva gerona": "NG", "la fe": "FI", "la reforma": "FO"}


def _norm(texto):
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.strip().lower()


def asignar_codigos(apps, schema_editor):
    Causa = apps.get_model("catalogos", "CausaIncidencia")
    Centro = apps.get_model("catalogos", "Centro")

    usados = set()
    for causa in Causa.objects.order_by("pk"):
        codigo, nombre = CAUSAS.get(_norm(causa.nombre), (None, None))
        if codigo and codigo not in usados and not Causa.objects.filter(nombre=nombre).exclude(pk=causa.pk).exists():
            causa.codigo, causa.nombre = codigo, nombre
        else:
            causa.codigo = f"X{causa.pk}"
        usados.add(causa.codigo)
        causa.save()

    usados = set()
    for centro in Centro.objects.order_by("pk"):
        codigo = CENTROS.get(_norm(centro.nombre))
        centro.codigo = codigo if codigo and codigo not in usados else f"C{centro.pk}"
        usados.add(centro.codigo)
        centro.save()


class Migration(migrations.Migration):
    dependencies = [("catalogos", "0003_codigos_opcionales")]
    operations = [migrations.RunPython(asignar_codigos, migrations.RunPython.noop)]
