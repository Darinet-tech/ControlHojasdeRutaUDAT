"""Resúmenes por período (día, mes, año).

Usa las mismas reglas que `services.resumen_hoja` (que calcula una sola hoja), pero cargando los datos en bloque para
que un año completo se calcule rápido. Las pruebas comprueban que ambos caminos dan el mismo resultado.

Definiciones:
- efectividad = acciones con OK / acciones atendidas (las no visitadas no cuentan: pasan al siguiente día).
- productividad = minutos normados de las acciones con OK / minutos reales consumidos (ya sin incidencias).
- tiempo disponible = (jornada efectiva - minutos de incidencias que descuentan) x operarios de cada hoja.
- ocupación = minutos reales / tiempo disponible.
- por centro: según el centro de cada servicio (una hoja puede trabajar en varios centros); sin tiempo disponible ni ocupación.
- productividad de un operario = la de las hojas en que participó (la productividad es de la hoja completa).
"""
import calendar
from collections import defaultdict
from datetime import date

from django.conf import settings
from django.utils import timezone

from catalogos.models import NormaTiempo, NormaTrabajo

from .models import Accion, HojaDeRuta, Incidencia, OrdenServicio, estado_de_accion, etiqueta_orden

MAXIMO_LISTADO = 500


class Normas:
    """Normas de tiempo en memoria: misma regla que NormaTiempo.vigente, sin una consulta por clave."""

    def __init__(self):
        self.por_clave = defaultdict(list)
        for n in NormaTiempo.objects.values("clave_id", "tipo_orden_id", "minutos", "vigente_desde", "vigente_hasta"):
            self.por_clave[n["clave_id"]].append(n)

    def minutos_trabajo(self, trabajo_id, fecha):
        if not hasattr(self, "_trabajos"):
            self._trabajos = defaultdict(list)
            for n in NormaTrabajo.objects.values("tipo_trabajo_id", "minutos", "vigente_desde", "vigente_hasta"):
                self._trabajos[n["tipo_trabajo_id"]].append(n)
        vigentes = [n for n in self._trabajos.get(trabajo_id, [])
                    if n["vigente_desde"] <= fecha and (n["vigente_hasta"] is None or n["vigente_hasta"] >= fecha)]
        return max(vigentes, key=lambda n: n["vigente_desde"])["minutos"] if vigentes else None

    def minutos(self, clave_id, tipo_orden_id, fecha):
        vigentes = [n for n in self.por_clave.get(clave_id, [])
                    if n["vigente_desde"] <= fecha and (n["vigente_hasta"] is None or n["vigente_hasta"] >= fecha)]
        if tipo_orden_id is not None:
            especificas = [n for n in vigentes if n["tipo_orden_id"] == tipo_orden_id]
            if especificas:
                return max(especificas, key=lambda n: n["vigente_desde"])["minutos"]
        generales = [n for n in vigentes if n["tipo_orden_id"] is None]
        return max(generales, key=lambda n: n["vigente_desde"])["minutos"] if generales else None


def rango(periodo, fecha):
    if periodo == "dia":
        return fecha, fecha
    if periodo == "mes":
        return fecha.replace(day=1), fecha.replace(day=calendar.monthrange(fecha.year, fecha.month)[1])
    if periodo == "anio":
        return date(fecha.year, 1, 1), date(fecha.year, 12, 31)
    raise ValueError(f"Período desconocido: {periodo}")


def _porcentaje(parte, total):
    return round(100 * parte / total, 1) if total else None


def indicadores(lista):
    """Indicadores de un conjunto de hojas (cada una ya calculada por `_estadisticas_por_hoja`)."""
    suma = lambda campo: sum(h[campo] for h in lista)  # noqa: E731
    atendidas, ok = suma("atendidas"), suma("ok")
    real, normado = suma("real"), suma("normado")
    disponible = sum(h["n_operarios"] * max(0, settings.JORNADA_EFECTIVA_MIN - h["incidencias_min"]) for h in lista)
    return {
        "hojas": len(lista), "acciones": suma("acciones"), "atendidas": atendidas, "ok": ok, "sin_ok": suma("sin_ok"),
        "pasadas": suma("pasadas"), "no_visitadas": suma("no_visitadas"), "en_curso": suma("en_curso"),
        "efectividad_pct": _porcentaje(ok, atendidas),
        "tiempo_real_min": real, "tiempo_normado_min": normado, "productividad_pct": _porcentaje(normado, real),
        "incidencias_min": suma("incidencias_min"), "tiempo_disponible_min": disponible,
        "ocupacion_pct": _porcentaje(real, disponible),
    }


def indicadores_de_acciones(filas):
    """Indicadores de un grupo de acciones (p. ej. las de un centro). No hay tiempo disponible ni ocupación: el tiempo
    disponible es de la hoja completa y no se puede repartir entre los centros de una misma hoja."""
    cuenta = lambda estado: sum(1 for f in filas if f["estado"] == estado)  # noqa: E731
    atendidas = sum(1 for f in filas if f["estado"] != "NO_VISITADA")
    ok, real, normado = cuenta("OK"), sum(f["tiempo_real_min"] or 0 for f in filas), sum(f["normado"] for f in filas)
    return {"hojas": len({f["hoja_id"] for f in filas}), "acciones": len(filas), "atendidas": atendidas, "ok": ok,
            "sin_ok": cuenta("SIN_OK"), "pasadas": cuenta("PASADA_A_BRIGADA"), "no_visitadas": cuenta("NO_VISITADA"),
            "en_curso": cuenta("EN_CURSO"), "efectividad_pct": _porcentaje(ok, atendidas), "tiempo_real_min": real,
            "tiempo_normado_min": normado, "productividad_pct": _porcentaje(normado, real), "incidencias_min": None,
            "tiempo_disponible_min": None, "ocupacion_pct": None}


def _estadisticas_por_hoja(base, ahora):
    """Una fila de estadísticas por hoja, más las acciones (filas planas) para los listados."""
    normas = Normas()
    hojas = {h.pk: h for h in base.select_related("brigada", "vehiculo").prefetch_related("operarios", "centros")}
    stats = {
        pk: {"hoja_id": pk, "fecha": h.fecha, "brigada": h.brigada.nombre, "brigada_id": h.brigada_id,
             "centro": h.etiqueta_centros, "cerrada": h.cerrada, "vehiculo": h.vehiculo.chapa if h.vehiculo_id else None,
             "operarios": [(o.pk, o.nombre) for o in h.operarios.all()], "n_operarios": h.operarios.count(),
             "acciones": 0, "atendidas": 0, "ok": 0, "sin_ok": 0, "pasadas": 0, "no_visitadas": 0, "en_curso": 0,
             "real": 0, "normado": 0, "incidencias_min": 0}
        for pk, h in hojas.items()
    }

    claves_de = defaultdict(list)
    for accion_id, clave_id in Accion.claves.through.objects.filter(accion__hoja__in=base).values_list("accion_id", "clave_id"):
        claves_de[accion_id].append(clave_id)

    trabajos_de = defaultdict(list)
    for accion_id, trabajo_id in Accion.trabajos.through.objects.filter(accion__hoja__in=base).values_list("accion_id", "tipotrabajo_id"):
        trabajos_de[accion_id].append(trabajo_id)

    filas = list(Accion.objects.filter(hoja__in=base).values(
        "id", "hoja_id", "orden_id", "orden__numero_servicio", "orden__categoria", "orden__numero_orden", "orden__tipo_orden__codigo",
        "orden__tipo_mantenimiento__codigo", "orden__tipo_orden_id", "orden__estado", "centro__codigo", "ok",
        "no_visitada", "pasada_a_id", "pasada_a__nombre", "hora_fin", "tiempo_real_min"))
    contador = {"OK": "ok", "SIN_OK": "sin_ok", "PASADA_A_BRIGADA": "pasadas", "NO_VISITADA": "no_visitadas", "EN_CURSO": "en_curso"}
    for f in filas:
        f["estado"] = estado_de_accion(f["ok"], f["pasada_a_id"], f["no_visitada"], f["hora_fin"])
        f["etiqueta"] = etiqueta_orden(f["orden__categoria"], f["orden__numero_servicio"], f["orden__tipo_mantenimiento__codigo"] or "",
                                       f["orden__tipo_orden__codigo"] or "", f["orden__numero_orden"])
        e = stats[f["hoja_id"]]
        e["acciones"] += 1
        e[contador[f["estado"]]] += 1
        if f["estado"] != "NO_VISITADA":
            e["atendidas"] += 1
        e["real"] += f["tiempo_real_min"] or 0
        f["normado"] = 0
        if f["estado"] == "OK":
            if f["orden__categoria"] == "ORDEN_TRABAJO":  # una orden de trabajo se norma por sus trabajos
                minutos = [normas.minutos_trabajo(t, e["fecha"]) for t in trabajos_de[f["id"]]]
            else:
                minutos = [normas.minutos(c, f["orden__tipo_orden_id"], e["fecha"]) for c in claves_de[f["id"]]]
            f["normado"] = max([m for m in minutos if m is not None], default=0)
            e["normado"] += f["normado"]

    por_causa = defaultdict(lambda: {"minutos": 0, "hojas": set()})
    for i in Incidencia.objects.filter(hoja__in=base).values("hoja_id", "inicio", "fin", "causa__codigo", "causa__nombre", "causa__descuenta_tiempo"):
        minutos = max(0, round(((i["fin"] or ahora) - i["inicio"]).total_seconds() / 60))
        if i["causa__descuenta_tiempo"]:
            stats[i["hoja_id"]]["incidencias_min"] += minutos
        causa = por_causa[(i["causa__codigo"], i["causa__nombre"])]
        causa["minutos"] += minutos
        causa["hojas"].add(i["hoja_id"])
    return stats, filas, por_causa


def _agrupar(stats, clave, nombre):
    grupos = defaultdict(list)
    for e in stats:
        grupos[clave(e)].append(e)
    return [{"nombre": nombre(k), **indicadores(v)} for k, v in sorted(grupos.items(), key=lambda kv: str(kv[0]))]


def hojas_del_periodo(desde, hasta, brigada=None, centro=None, solo_hoja=None):
    """Hojas de ruta de un período, opcionalmente de una brigada, de un centro (las que trabajaron en él) o una sola hoja."""
    base = HojaDeRuta.objects.filter(fecha__range=(desde, hasta))
    if solo_hoja:
        base = base.filter(pk=solo_hoja)
    if brigada:
        base = base.filter(brigada=brigada)
    if centro:
        base = base.filter(centros=centro).distinct()
    return base


def resumen_periodo(periodo, fecha, brigada=None, centro=None, ahora=None, solo_hoja=None):
    """Resumen completo de un día, un mes o un año (opcionalmente de una brigada y/o un centro)."""
    ahora = ahora or timezone.now()
    desde, hasta = rango(periodo, fecha)
    base = hojas_del_periodo(desde, hasta, brigada, centro, solo_hoja)
    stats, filas, por_causa = _estadisticas_por_hoja(base, ahora)
    lista = sorted(stats.values(), key=lambda e: (e["fecha"], e["centro"], e["brigada"]))
    hojas_por_id = stats

    # productividad individual: la de las hojas en que participó cada operario
    por_operario = defaultdict(list)
    for e in lista:
        for operario_id, nombre in e["operarios"]:
            por_operario[(operario_id, nombre)].append(e)
    operarios = sorted(
        ({"id": oid, "nombre": nombre, "dias": len({e["fecha"] for e in v}), **indicadores(v)}
         for (oid, nombre), v in por_operario.items()), key=lambda x: x["nombre"])

    resultado = {
        "periodo": periodo, "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "totales": indicadores(lista),
        "por_brigada": _agrupar(lista, lambda e: e["brigada"], lambda k: k),
        "por_centro": [],  # se completa más abajo, a partir de los servicios de cada centro
        "por_operario": operarios,
        "incidencias": sorted(({"codigo": c, "nombre": n, "minutos": v["minutos"], "hojas": len(v["hojas"])}
                               for (c, n), v in por_causa.items()), key=lambda x: x["codigo"]),
    }
    if periodo == "mes":
        resultado["por_dia"] = [{"fecha": k.isoformat(), **indicadores(v)} for k, v in sorted(_por(lista, lambda e: e["fecha"]).items())]
    if periodo == "anio":
        resultado["por_mes"] = [{"mes": f"{k[0]}-{k[1]:02d}", **indicadores(v)}
                                for k, v in sorted(_por(lista, lambda e: (e["fecha"].year, e["fecha"].month)).items())]
    if periodo == "dia":
        resultado["hojas"] = [{"id": e["hoja_id"], "brigada": e["brigada"], "centro": e["centro"], "cerrada": e["cerrada"],
                               "operarios": [n for _, n in e["operarios"]], **indicadores([e])} for e in lista]

    # por centro: según el centro de cada servicio (una hoja puede trabajar en varios centros)
    por_centro = defaultdict(list)
    for f in filas:
        por_centro[f["centro__codigo"] or "Sin centro"].append(f)
    resultado["por_centro"] = [{"nombre": c, **indicadores_de_acciones(v)} for c, v in sorted(por_centro.items())]

    # por tipo de acción (correctivo, preventivo, orden de servicio, orden de trabajo)
    nombres_categoria = dict(OrdenServicio.Categoria.choices)
    por_categoria = defaultdict(list)
    for f in filas:
        por_categoria[f["orden__categoria"]].append(f)
    resultado["por_categoria"] = [{"nombre": nombres_categoria[c], "codigo": c, **indicadores_de_acciones(v)}
                                  for c in nombres_categoria if (v := por_categoria.get(c))]
    # por vehículo: las hojas de cada vehículo (las hojas sin vehículo no se incluyen)
    por_vehiculo = _por([e for e in lista if e["vehiculo"]], lambda e: e["vehiculo"])
    resultado["por_vehiculo"] = [{"nombre": k, **indicadores(v)} for k, v in sorted(por_vehiculo.items())]

    # listados: lo pasado a otra brigada, lo no visitado y las reincidencias
    etiquetas = dict(OrdenServicio.Estado.choices)
    filas.sort(key=lambda f: (hojas_por_id[f["hoja_id"]]["fecha"], f["id"]))
    pasadas = [{"fecha": hojas_por_id[f["hoja_id"]]["fecha"].isoformat(), "servicio": f["etiqueta"],
                "desde": hojas_por_id[f["hoja_id"]]["brigada"], "hacia": f["pasada_a__nombre"],
                "centro": f["centro__codigo"] or "—", "estado_actual": etiquetas[f["orden__estado"]]}
               for f in filas if f["estado"] == "PASADA_A_BRIGADA"]
    no_visitadas = [{"fecha": hojas_por_id[f["hoja_id"]]["fecha"].isoformat(), "servicio": f["etiqueta"],
                     "brigada": hojas_por_id[f["hoja_id"]]["brigada"], "centro": f["centro__codigo"] or "—",
                     "sigue_sin_visitar": f["orden__estado"] == OrdenServicio.Estado.NO_VISITADA}
                    for f in filas if f["estado"] == "NO_VISITADA"]
    resultado["pasadas_a_brigada"] = {"total": len(pasadas), "lista": pasadas[:MAXIMO_LISTADO]}
    resultado["no_visitadas"] = {"total": len(no_visitadas), "lista": no_visitadas[:MAXIMO_LISTADO]}

    # Reincidencia: el mismo servicio con más de una orden en el período (el cliente volvió a reportar la avería).
    # Los operarios que "lo trabajaron" son solo los que atendieron una acción, no los de una acción no visitada.
    por_servicio = defaultdict(list)
    for f in filas:
        if f["orden__categoria"] == "CORRECTIVO":  # reincidencia = el servicio se vuelve a dañar
            por_servicio[f["orden__numero_servicio"]].append(f)
    reincidencias = []
    for servicio, acciones in por_servicio.items():
        ordenes = {a["orden_id"] for a in acciones}
        if len(ordenes) > 1:
            nombres = sorted({n for a in acciones if a["estado"] != "NO_VISITADA" for _, n in hojas_por_id[a["hoja_id"]]["operarios"]})
            reincidencias.append({"servicio": servicio, "ordenes": len(ordenes), "acciones": len(acciones), "operarios": nombres,
                                  "ultima_fecha": max(hojas_por_id[a["hoja_id"]]["fecha"] for a in acciones).isoformat()})
    reincidencias.sort(key=lambda r: (-r["ordenes"], r["servicio"]))
    resultado["reincidencias"] = {"total": len(reincidencias), "lista": reincidencias[:MAXIMO_LISTADO]}
    return resultado


def _por(lista, clave):
    grupos = defaultdict(list)
    for e in lista:
        grupos[clave(e)].append(e)
    return grupos


def _mejores(filas, cuantos=5):
    """Los de mayor productividad (solo los que tienen tiempo real registrado), con su efectividad y servicios."""
    candidatas = [f for f in filas if f["productividad_pct"] is not None]
    candidatas.sort(key=lambda f: (-f["productividad_pct"], -f["ok"], f["nombre"]))
    return [{"nombre": f["nombre"], "productividad_pct": f["productividad_pct"], "efectividad_pct": f["efectividad_pct"],
             "ok": f["ok"], "acciones": f["acciones"], "hojas": f["hojas"]} for f in candidatas[:cuantos]]


def analisis_de_jefatura(hoy, periodo, ahora=None):
    """Tiempo perdido por incidencias y los más productivos, de la jornada anterior (el último día con hojas antes de hoy),
    del mes o del año."""
    if periodo == "anterior":
        fecha = HojaDeRuta.objects.filter(fecha__lt=hoy).order_by("-fecha").values_list("fecha", flat=True).first()
        if fecha is None:
            return {"periodo": periodo, "fecha": None, "hojas": 0, "incidencias": [], "incidencias_min": 0, "operarios": [], "vehiculos": []}
        r = resumen_periodo("dia", fecha, ahora=ahora)
    else:
        fecha = hoy
        r = resumen_periodo(periodo, hoy, ahora=ahora)
    return {"periodo": periodo, "fecha": fecha.isoformat(), "hojas": r["totales"]["hojas"], "incidencias": r["incidencias"],
            "incidencias_min": r["totales"]["incidencias_min"], "operarios": _mejores(r["por_operario"]), "vehiculos": _mejores(r["por_vehiculo"])}
