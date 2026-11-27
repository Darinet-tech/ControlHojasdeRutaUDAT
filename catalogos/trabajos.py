
"""Cómo se mide cada trabajo de las órdenes de trabajo y los tipos de caja terminal (valores iniciales).

Los de la caja terminal vienen de la instrucción de normas (en proceso de firma): sustituir la caja son 70 min (Cable 18) y la de cola lleva
además el módulo de empalme (30 min, Cable 76). Son provisionales hasta revisarlos con el especialista; los pares que se empalmen en el
módulo se pueden normar agregando un trabajo «por unidad» (Cable 48: 1 min por par). Las normas de postes y cables las define el especialista."""
from datetime import date
from decimal import Decimal

INICIO = date(2000, 1, 1)
NOTA = "Provisional: pendiente de revisar con el especialista"

# (nombre, cómo se norma, unidad)
TRABAJOS = [
    ("Sustitución de poste(s)", "UNIDADES", "poste(s)"),
    ("Sustitución de caja(s) terminal(es)", "TIPO", ""),
    ("Sustitución de cable de cobre", "METROS", "metro(s)"),
]
CAJAS = {"Multiservicios": "70:00", "Con cola": "100:00"}


def configurar(TipoTrabajo, OpcionDeTrabajo, NormaTrabajo):
    """Crea los trabajos que falten, les da su forma de medirse (solo si no la tienen) y crea los tipos de caja con su norma."""
    from .normas_2026 import minutos
    for nombre, medida, unidad in TRABAJOS:
        trabajo, _ = TipoTrabajo.objects.get_or_create(nombre=nombre)
        if not trabajo.medida:
            trabajo.medida, trabajo.unidad = medida, unidad
            trabajo.save()
    caja = TipoTrabajo.objects.get(nombre="Sustitución de caja(s) terminal(es)")
    if caja.medida == "TIPO":
        for nombre, tiempo in CAJAS.items():
            opcion, creada = OpcionDeTrabajo.objects.get_or_create(tipo_trabajo=caja, nombre=nombre)
            if creada:
                NormaTrabajo.objects.create(tipo_trabajo=caja, opcion=opcion, minutos=minutos(tiempo), vigente_desde=INICIO, nota=NOTA)
        NormaTrabajo.objects.filter(tipo_trabajo=caja, opcion__isnull=True).delete()  # la norma fija anterior: ahora depende del tipo
