"""Trabajos de las órdenes de trabajo: las actividades de Cable, Línea y Fibra Óptica de la instrucción firmada IT-OR-001/24.

Cada actividad se norma «por unidad» (también por par o por fibra) o «por metro»: el probador anota la cantidad y la norma de la orden es la
**suma** de sus actividades. Los tiempos van sin redondear y con la nota de la instrucción (válida hasta el 16/7/2026, hasta que se firme su
renovación). Las de fibra óptica con «2XFO» se norman a 2 minutos por cada fibra."""
import json
from pathlib import Path

from .normas_2026 import INICIO, NOTA

ARCHIVO = Path(__file__).with_name("actividades_cable_linea.json")  # Cable, Línea y Fibra Óptica


def cargar_actividades(TipoTrabajo, NormaTrabajo):
    """Crea (o completa) las actividades de la instrucción con su norma. No pisa lo que el especialista haya cambiado: solo crea lo que falta."""
    creadas = 0
    for a in json.loads(ARCHIVO.read_text(encoding="utf-8")):
        trabajo = TipoTrabajo.objects.filter(especialidad=a["especialidad"], clave=a["clave"]).first()
        if trabajo is None:
            trabajo = TipoTrabajo.objects.create(
                nombre=a["nombre"], especialidad=a["especialidad"], clave=a["clave"], medida=a["medida"], unidad=a["unidad"],
                fuerza_trabajo=a["fuerza_trabajo"], descripcion=a["descripcion"])
            creadas += 1
        if a["minutos"] is not None and not NormaTrabajo.objects.filter(tipo_trabajo=trabajo, opcion__isnull=True).exists():
            NormaTrabajo.objects.create(tipo_trabajo=trabajo, minutos=round(a["minutos"], 4), vigente_desde=INICIO, nota=NOTA)
    return creadas
