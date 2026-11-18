"""Claves de cierre de las órdenes de servicio (independientes de las claves de reparación).

Son los motivos por los que una orden NO se ejecutó; ejecutarla es «Dar OK» y no lleva clave. Solo están las que realmente se usan
(faltan a propósito la 8, 10 a 12 y 15 a 17). Se crean si faltan y no se pisan los cambios del administrador."""

GRUPO = "Orden de servicio"
# código, descripción, clasificación (NO_EFECTIVA = motivo del cliente; PENDIENTE = depende de otra brigada o de un trabajo especial)
CLAVES_ORDEN = [
    ("1", "El cliente avisará", "NO_EFECTIVA"),
    ("2", "Casa cerrada", "NO_EFECTIVA"),
    ("3", "Requiere inspección", "PENDIENTE"),
    ("4", "Par asignado malo", "PENDIENTE"),
    ("5", "No aparece en esa dirección", "NO_EFECTIVA"),
    ("6", "No autoriza el trabajo", "NO_EFECTIVA"),
    ("7", "Otras causas", "NO_EFECTIVA"),
    ("9", "No desea el trabajo", "NO_EFECTIVA"),
    ("13", "Desea extensión en otra dirección", "NO_EFECTIVA"),
    ("14", "Requiere apoyo del bajante", "PENDIENTE"),
    ("18", "Requiere trabajos especiales (poste)", "PENDIENTE"),
    ("19", "Casa cerrada en proceso judicial", "NO_EFECTIVA"),
]


def crear(Clave, GrupoClave):
    grupo, _ = GrupoClave.objects.get_or_create(nombre=GRUPO)
    for codigo, descripcion, clasificacion in CLAVES_ORDEN:
        Clave.objects.get_or_create(codigo=codigo, defaults={"grupo": grupo, "descripcion": descripcion, "clasificacion": clasificacion,
                                                             "ambito": "ORDEN"})
