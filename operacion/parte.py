"""Parte diario de la Mesa de Prueba: tabla de acciones por tipo (filas) y por brigada (columnas), con total del día,
acumulado del mes y acumulado del año.

Cada columna es una hoja de ruta del día (su cabecera son las claves/iniciales de los operarios). Cada acción visitada cuenta en UNA fila:

- Correctivo cerrado con OK -> Reparadas Red de Abonados, o Telefonía Pública / Nauta Hogar Plus si así se marcó al insertarlo.
  Sin OK (o pasado a otra brigada) -> Pendiente de Par si alguna de sus claves es de ese grupo (23, 24); si no, Otras causas.
- Preventivo con OK -> según su tipo (Mantenimiento Red de Abonados, Mantenimiento Telefonía Pública, Gabinetes); sin OK -> Otras causas.
- Orden de servicio con OK -> según su tipo (Altas, Traslados, Bajas, Nauta Hogar, TE-TI, Misceláneas, TxD); anulada -> NULA; sin OK -> Otras causas.
- Orden de trabajo -> Ejecutadas (OK), En ejecución (abierta) o Pendientes de ejecución (sin OK, pasada a otra brigada o no visitada).

Lo que sigue en curso o no se visitó (correctivos, preventivos y órdenes de servicio) no cuenta: no se ha informado todavía.
La fila «Visitadas en el día» suma las filas de las acciones visitadas (no incluye en ejecución ni pendientes de las órdenes de trabajo).
"""
from collections import Counter, defaultdict
from datetime import date

from .models import Accion, estado_de_accion
from .reportes import hojas_del_periodo

GRUPOS = [
    ("Correctivo", [("rep_red", "Reparadas Red de Abonados"), ("rep_tp", "Reparadas Telefonía Pública"),
                    ("rep_nhp", "Reparadas Nauta Hogar Plus (NH+)"), ("pend_par", "Pendiente de Par"), ("otras_c", "Otras causas")]),
    ("Preventivo", [("mant_red", "Mantenimiento Red de Abonados"), ("mant_tp", "Mantenimiento Telefonía Pública (MTP)"),
                    ("gabinetes", "Gabinetes (regletas)"), ("otras_p", "Otras causas")]),
    ("Órdenes de Servicio", [("altas", "Altas ejecutadas (A)"), ("traslados", "Traslados Altas (TA)"), ("bajas", "Bajas (B, BS)"),
                             ("nauta_hogar", "Nauta Hogar (NH)"), ("te_ti", "TE – TI"), ("misc", "Misceláneas"), ("nula", "NULA"),
                             ("txd", "TxD"), ("otras_os", "Otras causas")]),
    ("Órdenes de Trabajo", [("ot_ok", "Ejecutadas (OK)"), ("ot_curso", "En ejecución"), ("ot_pend", "Pendientes de ejecución")]),
]
SOBRAN_VISITAS = "_regletas_de_mas"
NO_VISITADAS = {"ot_curso", "ot_pend"}  # no suman en «Visitadas en el día»
CLAVES_DE_FILAS = [clave for _, filas in GRUPOS for clave, _ in filas]


def fila_de(f, claves_del_parte):
    """Fila del parte donde cuenta una acción (None si todavía no cuenta). `f` es una fila de `Accion.values(...)`."""
    categoria, variante = f["orden__categoria"], f["orden__variante"]
    estado = estado_de_accion(f["ok"], f["pasada_a_id"], f["no_visitada"], f["hora_fin"], f["anulada"])
    if categoria == "ORDEN_TRABAJO":
        if estado == "OK":
            return "ot_ok"
        return "ot_curso" if estado == "EN_CURSO" else "ot_pend"
    if estado in ("EN_CURSO", "NO_VISITADA"):
        return None
    if categoria == "CORRECTIVO":
        if estado == "OK":
            return {"TP": "rep_tp", "NHP": "rep_nhp"}.get(variante, "rep_red")
        return "pend_par" if "PENDIENTE_PAR" in claves_del_parte else "otras_c"
    if categoria == "PREVENTIVO":
        if estado == "OK":
            return {"MANT_TP": "mant_tp", "GABINETES": "gabinetes"}.get(f["orden__tipo_mantenimiento__fila_parte"], "mant_red")
        return "otras_p"
    if estado == "ANULADA":  # orden de servicio
        return "nula"
    if estado == "OK":
        fila = f["orden__tipo_orden__fila_parte"]
        if fila == "ALTAS":
            return "nauta_hogar" if variante == "NH" else "altas"
        return {"TRASLADOS": "traslados", "BAJAS": "bajas", "TE_TI": "te_ti", "TXD": "txd"}.get(fila, "misc")
    return "otras_os"


def contar(hojas):
    """({hoja_id: Counter(fila)}, Counter(fila)) de las acciones de esas hojas."""
    claves = defaultdict(set)
    for accion_id, fila in Accion.claves.through.objects.filter(accion__hoja__in=hojas).values_list("accion_id", "clave__fila_parte"):
        if fila:
            claves[accion_id].add(fila)
    por_hoja, total = defaultdict(Counter), Counter()
    for f in Accion.objects.filter(hoja__in=hojas).values(
            "id", "hoja_id", "orden__categoria", "orden__variante", "orden__tipo_orden__fila_parte",
            "orden__tipo_mantenimiento__fila_parte", "regletas_mantenidas", "regletas_reparadas", "regletas_sustituidas", "ok", "anulada", "no_visitada", "pasada_a_id", "hora_fin"):
        fila = fila_de(f, claves[f["id"]])
        if fila:
            cantidad = 1
            if fila == "gabinetes":
                cantidad = f["regletas_mantenidas"] + f["regletas_reparadas"] + f["regletas_sustituidas"]
                por_hoja[f["hoja_id"]][SOBRAN_VISITAS] += cantidad - 1
                total[SOBRAN_VISITAS] += cantidad - 1
            por_hoja[f["hoja_id"]][fila] += cantidad
            total[fila] += cantidad
    return por_hoja, total


def _visitadas(contador):
    # La fila de gabinetes suma regletas, pero cada gabinete atendido es una sola visita: se descuenta la diferencia.
    return sum(n for fila, n in contador.items() if fila not in NO_VISITADAS and fila != SOBRAN_VISITAS) - contador[SOBRAN_VISITAS]


def _notas(hojas, etiquetas):
    """Texto bajo la tabla, por brigada: observaciones de la hoja, descripción de las órdenes de trabajo y motivo de lo cerrado sin OK."""
    ids = [h.pk for h in hojas]
    lineas = defaultdict(list)
    for h in hojas:
        if h.brigada.informa_con_texto and h.trabajos_realizados.strip():
            lineas[h.pk].append(h.trabajos_realizados.strip())
        if h.observaciones.strip():
            lineas[h.pk].append(h.observaciones.strip())
    acciones = (Accion.objects.filter(hoja_id__in=ids).select_related("orden").prefetch_related("trabajos").order_by("hoja_id", "numero"))
    for a in acciones:
        if a.orden.categoria == "ORDEN_TRABAJO":
            partes = [", ".join(sorted(t.nombre for t in a.trabajos.all())), a.descripcion_trabajo.strip(), a.observaciones.strip()]
            lineas[a.hoja_id].append(f"OT {a.orden.numero_orden}: " + " · ".join(p for p in partes if p))
        elif a.observaciones.strip() and a.estado in ("SIN_OK", "PASADA_A_BRIGADA"):
            lineas[a.hoja_id].append(f"{a.orden.etiqueta}: {a.observaciones.strip()}")
    por_brigada = defaultdict(list)
    for h in hojas:
        por_brigada[h.brigada_id].append(h.pk)
    rotulo = {}
    for h in hojas:
        if h.brigada.informa_con_texto:
            varias = len(por_brigada[h.brigada_id]) > 1
            numero = f" {por_brigada[h.brigada_id].index(h.pk) + 1}" if varias else ""
            rotulo[h.pk] = f"Brigada de {h.brigada.nombre}{numero} ({etiquetas[h.pk]})"
    return [{"columna": rotulo.get(pk, etiquetas[pk]), "texto": " | ".join(textos)} for pk, textos in lineas.items()]


def parte_diario(fecha, brigada=None, centro=None):
    """El parte del día `fecha` (hojas de ese día, opcionalmente de una brigada o un centro) con los acumulados del mes y del año."""
    dia = hojas_del_periodo(fecha, fecha, brigada, centro)
    hojas = list(dia.select_related("brigada").prefetch_related("operarios", "centros").order_by("brigada__nombre", "pk"))
    por_hoja, total_dia = contar(dia)
    _, total_mes = contar(hojas_del_periodo(fecha.replace(day=1), fecha, brigada, centro))
    _, total_anio = contar(hojas_del_periodo(date(fecha.year, 1, 1), fecha, brigada, centro))

    etiquetas = {h.pk: "-".join(sorted(o.clave for o in h.operarios.all())) or h.brigada.nombre for h in hojas}
    columnas = [{"hoja_id": h.pk, "etiqueta": etiquetas[h.pk], "brigada": h.brigada.nombre, "centros": h.etiqueta_centros} for h in hojas]

    def fila(clave, etiqueta):
        valores = [por_hoja[h.pk][clave] for h in hojas]
        return {"clave": clave, "etiqueta": etiqueta, "valores": valores, "total": total_dia[clave], "mes": total_mes[clave], "anio": total_anio[clave]}

    visitadas = {"clave": "visitadas", "etiqueta": "Visitadas en el día", "valores": [_visitadas(por_hoja[h.pk]) for h in hojas],
                 "total": _visitadas(total_dia), "mes": _visitadas(total_mes), "anio": _visitadas(total_anio)}
    return {
        "fecha": fecha,
        "columnas": columnas,
        "grupos": [{"nombre": nombre, "filas": [fila(c, e) for c, e in filas]} for nombre, filas in GRUPOS],
        "visitadas": visitadas,
        "notas": _notas(hojas, etiquetas),
    }
