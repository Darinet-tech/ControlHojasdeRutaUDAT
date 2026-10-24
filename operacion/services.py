"""Reglas de negocio: normas de tiempo, cierre de acciones (OK / pasar a otra brigada / sin OK), resúmenes y calidad."""
from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, Max, OuterRef
from django.utils import timezone

from catalogos.models import NormaTiempo, NormaTrabajo

from .models import Accion, HojaDeRuta, Incidencia, OrdenServicio


def norma_accion(accion):
    """Minutos normados de una acción. Si es una orden de trabajo, el de su trabajo de mayor norma; en las demás,
    el de su clave MAYOR (regla del negocio). None si ninguno tiene norma."""
    fecha = accion.hoja.fecha
    minutos = []
    if accion.orden.categoria == OrdenServicio.Categoria.ORDEN_TRABAJO:
        for trabajo in accion.trabajos.all():
            norma = NormaTrabajo.vigente(trabajo, fecha)
            if norma:
                minutos.append(norma.minutos)
    else:
        tipo = accion.orden.tipo_orden
        for clave in accion.claves.all():
            norma = NormaTiempo.vigente(clave, tipo, fecha)
            if norma:
                minutos.append(norma.minutos)
    return max(minutos) if minutos else None


def es_orden_de_trabajo(accion):
    return accion.orden.categoria == OrdenServicio.Categoria.ORDEN_TRABAJO


def sugerir_ok(accion):
    """Sugerencia (no decisión): hay alguna clave efectiva y ninguna pendiente (una orden de trabajo, con sus trabajos)."""
    if es_orden_de_trabajo(accion):
        return accion.trabajos.exists()
    claves = list(accion.claves.all())
    return any(c.es_efectiva for c in claves) and not any(c.es_pendiente for c in claves)


def _exigir_trabajo_registrado(accion, para):
    """Para cerrar una acción hay que haber registrado lo que se hizo: claves de cierre, o los trabajos de la orden de trabajo."""
    if es_orden_de_trabajo(accion):
        if not accion.trabajos.exists():
            raise ValidationError(f"Seleccione al menos un trabajo de la orden de trabajo antes de {para}.")
    elif not accion.claves.exists():
        raise ValidationError(f"Registre al menos una clave de cierre antes de {para}.")


def _minutos_incidencia(hoja, desde, hasta):
    """Minutos de incidencias que descuentan tiempo y caen dentro de [desde, hasta]. Una incidencia activa cuenta hasta `hasta`."""
    total = 0.0
    for inc in hoja.incidencias.filter(causa__descuenta_tiempo=True):
        ini, fin = max(inc.inicio, desde), min(inc.fin or hasta, hasta)
        if fin > ini:
            total += (fin - ini).total_seconds() / 60
    return total


# ---------------------------------------------------------------- un operario no puede estar en dos hojas el mismo día

def conflictos_de_operarios(fecha, operarios, excluir_hoja=None):
    """Operarios (de `operarios`) que ya están en otra hoja de ruta de esa fecha: lista de (operario, hoja)."""
    ids = [o.pk if hasattr(o, "pk") else o for o in operarios]
    if not ids:
        return []
    enlaces = HojaDeRuta.operarios.through.objects.filter(operario_id__in=ids, hojaderuta__fecha=fecha)
    if excluir_hoja is not None and excluir_hoja.pk:
        enlaces = enlaces.exclude(hojaderuta=excluir_hoja)
    enlaces = enlaces.select_related("operario", "hojaderuta__brigada").prefetch_related("hojaderuta__centros")
    return [(e.operario, e.hojaderuta) for e in enlaces]


def validar_operarios_libres(fecha, operarios, excluir_hoja=None):
    """Lanza ValidationError si algún operario ya está en otra hoja de ruta el mismo día."""
    mensajes = [
        f"{operario.nombre} ya está en la hoja {hoja.etiqueta_centros} · {hoja.brigada.nombre} del {hoja.fecha:%d/%m/%Y}."
        for operario, hoja in conflictos_de_operarios(fecha, operarios, excluir_hoja)
    ]
    if mensajes:
        raise ValidationError(mensajes)


# ---------------------------------------------------------------- incidencias y cierre de la hoja

@transaction.atomic
def iniciar_incidencia(hoja, causa, usuario, observaciones="", ahora=None):
    """Arranca el contador de una incidencia. Si había otra activa, se detiene (cambio de estado)."""
    if hoja.cerrada:
        raise ValidationError("La hoja de ruta está cerrada.")
    ahora = ahora or timezone.now()
    finalizar_incidencia(hoja, usuario, ahora=ahora)
    return Incidencia.objects.create(
        hoja=hoja, causa=causa, inicio=ahora, observaciones=observaciones, creado_por=usuario, modificado_por=usuario
    )


def finalizar_incidencia(hoja, usuario, ahora=None):
    """Detiene el contador de la incidencia activa (el operario confirmó el cambio de estado). None si no hay."""
    activa = hoja.incidencias.filter(fin__isnull=True).first()
    if activa:
        activa.fin = ahora or timezone.now()
        activa.modificado_por = usuario
        activa.save()
    return activa


def acciones_abiertas(hoja):
    """Acciones de la hoja que aún no se cerraron (sin OK, sin pase a otra brigada y sin cierre)."""
    return hoja.acciones.filter(hora_fin__isnull=True, no_visitada=False)


@transaction.atomic
def cerrar_hoja(hoja, usuario, ahora=None):
    """Cierra la hoja al finalizar el día.

    - Detiene cualquier contador de incidencia que siga activo.
    - Los servicios que no se cerraron pasan a NO VISITADOS y quedan guardados para el siguiente día. Si la orden
      era un pendiente de otra brigada, sigue pendiente para esa brigada.
    """
    if hoja.cerrada:
        raise ValidationError("La hoja de ruta ya está cerrada.")
    ahora = ahora or timezone.now()
    finalizar_incidencia(hoja, usuario, ahora=ahora)
    for accion in hoja.acciones.filter(hora_fin__isnull=True, no_visitada=False).select_related("orden"):
        accion.no_visitada = True
        accion.modificado_por = usuario
        accion.save()
        orden = accion.orden
        if orden.estado == OrdenServicio.Estado.ABIERTA:
            orden.estado = OrdenServicio.Estado.NO_VISITADA
            orden.brigada_pendiente = hoja.brigada
            orden.save(update_fields=["estado", "brigada_pendiente", "modificado_en"])
    hoja.cerrada, hoja.cerrada_en, hoja.cerrada_por, hoja.modificado_por = True, ahora, usuario, usuario
    hoja.save()
    return hoja


# ---------------------------------------------------------------- cierre de acciones

def _cerrar(accion, usuario, ahora):
    """Genera la hora de fin y el tiempo real: hora de fin menos la hora de fin de la acción anterior de la hoja.

    Para la primera acción se usa el inicio de la jornada de la hoja (08:00 por defecto).
    """
    if accion.hora_fin is not None:
        raise ValidationError("Esta acción ya está cerrada.")
    if accion.hoja.cerrada or accion.no_visitada:
        raise ValidationError("La hoja de ruta está cerrada.")
    ahora = ahora or timezone.now()
    previa = (
        Accion.objects.filter(hoja=accion.hoja, hora_fin__isnull=False, hora_fin__lte=ahora)
        .exclude(pk=accion.pk)
        .order_by("-hora_fin")
        .first()
    )
    if previa:
        inicio = previa.hora_fin
    else:
        inicio_jornada = accion.hoja.hora_inicio or settings.HORA_INICIO_JORNADA
        inicio = timezone.make_aware(datetime.combine(accion.hoja.fecha, inicio_jornada))
    accion.hora_fin = ahora
    bruto = (ahora - inicio).total_seconds() / 60
    # Las incidencias (lluvia, transporte...) ocurridas entre las dos horas no cuentan como tiempo de trabajo.
    accion.tiempo_real_min = max(0, round(bruto - _minutos_incidencia(accion.hoja, inicio, ahora)))
    accion.modificado_por = usuario


@transaction.atomic
def certificar_ok(accion, usuario, cliente_contactado, ahora=None):
    """El probador da el OK tras hablar con el cliente: cierra la acción y deja la orden restablecida."""
    _exigir_trabajo_registrado(accion, "dar el OK")
    cliente_contactado = (cliente_contactado or "").strip()
    if not cliente_contactado and accion.orden.categoria == OrdenServicio.Categoria.CORRECTIVO:
        raise ValidationError("Indique el cliente con quien se certificó el servicio.")  # el cliente es obligatorio solo en correctivos
    _cerrar(accion, usuario, ahora)
    accion.ok = True
    accion.cliente_contactado = cliente_contactado
    accion.certificada_por = usuario
    accion.certificada_en = accion.hora_fin
    accion.save()
    orden = accion.orden
    orden.estado = OrdenServicio.Estado.RESTABLECIDA
    orden.brigada_pendiente = None
    orden.save(update_fields=["estado", "brigada_pendiente", "modificado_en"])
    return accion


@transaction.atomic
def pasar_a_brigada(accion, brigada, usuario, ahora=None):
    """El servicio no se pudo resolver y depende de otra brigada (cable, línea, reconstrucción, fibra óptica...).

    Cierra la acción (sin OK) y deja la orden pendiente para esa brigada, elegida por el probador en cada caso.
    """
    _exigir_trabajo_registrado(accion, "pasar el servicio a otra brigada")
    _cerrar(accion, usuario, ahora)
    accion.pasada_a = brigada
    accion.save()
    orden = accion.orden
    orden.estado = OrdenServicio.Estado.PENDIENTE
    orden.brigada_pendiente = brigada
    orden.save(update_fields=["estado", "brigada_pendiente", "modificado_en"])
    return accion


@transaction.atomic
def cerrar_sin_ok(accion, usuario, ahora=None):
    """Cierra la acción sin OK ni pase a otra brigada (p. ej. no efectiva por causa del cliente). No es efectiva."""
    _exigir_trabajo_registrado(accion, "cerrar la acción")
    _cerrar(accion, usuario, ahora)
    accion.save()
    return accion


def _en_trabajo():
    """Acciones abiertas de hojas abiertas: el servicio ya está asignado y no se ofrece de nuevo."""
    return Accion.objects.filter(orden=OuterRef("pk"), hora_fin__isnull=True, no_visitada=False, hoja__cerrada=False)


def ordenes_pendientes(brigada, centros=None):
    """Servicios pendientes que deben ofrecerse para asignar a una hoja de esa brigada (opcionalmente de ciertos centros)."""
    qs = OrdenServicio.objects.filter(estado=OrdenServicio.Estado.PENDIENTE, brigada_pendiente=brigada)
    if centros is not None:
        centros = [centros] if not hasattr(centros, "__iter__") else list(centros)
        qs = qs.filter(acciones__centro__in=centros).distinct()
    return qs.exclude(Exists(_en_trabajo()))


def ordenes_no_visitadas(brigada, centros=None):
    """Servicios que la brigada no visitó en días anteriores (opcionalmente de ciertos centros), listos para el nuevo día."""
    qs = OrdenServicio.objects.filter(estado=OrdenServicio.Estado.NO_VISITADA, brigada_pendiente=brigada)
    if centros is not None:
        centros = [centros] if not hasattr(centros, "__iter__") else list(centros)
        qs = qs.filter(acciones__centro__in=centros).distinct()
    return qs.exclude(Exists(_en_trabajo()))


CAMPOS_POR_CATEGORIA = {  # lo que corresponde introducir en cada tipo de acción; el resto no se acepta
    "CORRECTIVO": {"numero_servicio"},
    "PREVENTIVO": {"tipo_mantenimiento", "numero_servicio"},
    "ORDEN_SERVICIO": {"tipo_orden", "numero_orden", "numero_servicio"},
    "ORDEN_TRABAJO": {"numero_orden", "trabajos"},
}
NOMBRES_DE_CAMPOS = {"numero_servicio": "el número del servicio telefónico", "tipo_mantenimiento": "el tipo de mantenimiento",
                     "tipo_orden": "el tipo de orden", "numero_orden": "el número de orden", "trabajos": "los trabajos"}


def obtener_orden(categoria, usuario, numero_servicio="", tipo_mantenimiento=None, tipo_orden=None, numero_orden="", trabajos=None):
    """Busca la orden abierta que corresponde a los datos, o crea una nueva. Valida los campos según la categoría:
    solo se piden (y se aceptan) los que corresponden a ese tipo de acción, para evitar errores de captura.

    Una orden ya restablecida no se reutiliza: se abre otra (reincidencia, en los correctivos)."""
    if categoria not in CAMPOS_POR_CATEGORIA:
        raise ValidationError("La categoría debe ser correctivo, preventivo, orden de servicio u orden de trabajo.")
    numero_servicio, numero_orden = (numero_servicio or "").strip(), (numero_orden or "").strip()
    datos = {"numero_servicio": numero_servicio, "tipo_mantenimiento": tipo_mantenimiento, "tipo_orden": tipo_orden,
             "numero_orden": numero_orden, "trabajos": list(trabajos or [])}
    etiquetas = dict(OrdenServicio.Categoria.choices)
    requeridos = CAMPOS_POR_CATEGORIA[categoria]
    faltan = [NOMBRES_DE_CAMPOS[c] for c in sorted(requeridos) if not datos[c]]
    if faltan:
        raise ValidationError(f"En {etiquetas[categoria].lower()} hay que indicar: {', '.join(faltan)}.")
    sobran = [NOMBRES_DE_CAMPOS[c] for c in datos if c not in requeridos and datos[c]]
    if sobran:
        raise ValidationError(f"En {etiquetas[categoria].lower()} no corresponde indicar: {', '.join(sobran)}.")

    filtro = {"categoria": categoria}
    if categoria in ("ORDEN_SERVICIO", "ORDEN_TRABAJO"):
        filtro["numero_orden"] = numero_orden
        if categoria == "ORDEN_SERVICIO":
            filtro["numero_servicio"] = numero_servicio
    else:
        filtro["numero_servicio"] = numero_servicio
        if categoria == "PREVENTIVO":
            filtro["tipo_mantenimiento"] = tipo_mantenimiento
    orden = OrdenServicio.objects.filter(**filtro).exclude(estado=OrdenServicio.Estado.RESTABLECIDA).order_by("-creado_en").first()
    if orden is None:
        orden = OrdenServicio.objects.create(categoria=categoria, numero_servicio=numero_servicio, tipo_mantenimiento=tipo_mantenimiento,
                                             tipo_orden=tipo_orden, numero_orden=numero_orden, creado_por=usuario, modificado_por=usuario)
    if categoria == "ORDEN_TRABAJO":
        orden.trabajos.set(datos["trabajos"])  # los trabajos de la orden (los últimos indicados)
    return orden


def centro_previo(orden):
    """Centro de la última acción registrada sobre la orden (None si no tiene)."""
    ultima = orden.acciones.filter(centro__isnull=False).select_related("centro").order_by("-hoja__fecha", "-pk").first()
    return ultima.centro if ultima else None


def _centro_del_servicio(hoja, orden, centro):
    """Centro con que se asigna un servicio a la hoja: el indicado, o el único de la hoja, o el que ya tenía."""
    centros = list(hoja.centros.all())
    if centro is not None:
        if centro.pk not in {c.pk for c in centros}:
            raise ValidationError(f"El centro {centro.codigo} no es uno de los centros de la hoja ({hoja.etiqueta_centros}).")
        return centro
    if len(centros) == 1:
        return centros[0]
    previo = centro_previo(orden)
    if previo is not None and previo.pk in {c.pk for c in centros}:
        return previo
    raise ValidationError(f"La hoja trabaja en varios centros ({hoja.etiqueta_centros}): indique el centro del servicio.")


@transaction.atomic
def asignar_orden(hoja, orden, usuario, centro=None, trabajos=None):
    """Crea la acción de una orden en la hoja. Una orden no visitada vuelve a quedar abierta.

    Una orden de trabajo lleva sus trabajos: los indicados, o los que ya tenía en su acción anterior."""
    if hoja.cerrada:
        raise ValidationError("La hoja de ruta está cerrada.")
    if hoja.acciones.filter(orden=orden, hora_fin__isnull=True, no_visitada=False).exists():
        raise ValidationError("Ese servicio ya está asignado a esta hoja y sigue abierto.")
    centro = _centro_del_servicio(hoja, orden, centro)
    if orden.estado == OrdenServicio.Estado.NO_VISITADA:
        orden.estado, orden.brigada_pendiente = OrdenServicio.Estado.ABIERTA, None
        orden.save(update_fields=["estado", "brigada_pendiente", "modificado_en"])
    numero = (hoja.acciones.aggregate(m=Max("numero"))["m"] or 0) + 1
    accion = Accion.objects.create(hoja=hoja, orden=orden, numero=numero, centro=centro, creado_por=usuario, modificado_por=usuario)
    if orden.categoria == OrdenServicio.Categoria.ORDEN_TRABAJO:
        if trabajos is None:
            anterior = orden.acciones.exclude(pk=accion.pk).order_by("-hoja__fecha", "-pk").first()
            trabajos = list(anterior.trabajos.all()) if anterior else list(orden.trabajos.all())
        accion.trabajos.set(trabajos)
    return accion


def asignar_pendientes(hoja, usuario, ordenes=None):
    """Asigna a la hoja los servicios pendientes de su brigada y de cualquiera de sus centros (o solo los indicados)."""
    candidatas = ordenes_pendientes(hoja.brigada, hoja.centros.all())
    if ordenes is not None:
        candidatas = candidatas.filter(pk__in=[o.pk for o in ordenes])
    with transaction.atomic():
        return [asignar_orden(hoja, orden, usuario) for orden in candidatas.order_by("creado_en")]


def asignar_no_visitadas(hoja, usuario, ordenes=None):
    """Asigna a la hoja los servicios no visitados de su brigada y de cualquiera de sus centros (o solo los indicados)."""
    candidatas = ordenes_no_visitadas(hoja.brigada, hoja.centros.all())
    if ordenes is not None:
        candidatas = candidatas.filter(pk__in=[o.pk for o in ordenes])
    with transaction.atomic():
        return [asignar_orden(hoja, orden, usuario) for orden in candidatas.order_by("creado_en")]


def resumen_hoja(hoja, ahora=None):
    """Indicadores de una hoja de ruta.

    - efectividad_pct: acciones con OK / acciones atendidas (las no visitadas no cuentan: pasan al siguiente día).
    - productividad_pct: minutos normados de las acciones efectivas / minutos reales consumidos (ya sin incidencias).
    - tiempo_disponible_min: (jornada efectiva - minutos de incidencias que descuentan) x operarios.
    - ocupacion_pct: minutos reales / tiempo disponible.
    - resultados / pasadas_a_brigada / no_visitadas: qué pasó con cada servicio de la hoja.
    """
    ahora = ahora or timezone.now()
    acciones = list(hoja.acciones.select_related("orden__tipo_orden", "hoja", "pasada_a").prefetch_related("claves"))
    efectivas = [a for a in acciones if a.ok]
    atendidas = [a for a in acciones if not a.no_visitada]
    real = sum(a.tiempo_real_min or 0 for a in acciones)
    normas = {a.pk: norma_accion(a) for a in acciones}
    normado_efectivo = sum(normas[a.pk] or 0 for a in efectivas)

    por_causa, incidencias_min = {}, 0
    for inc in hoja.incidencias.select_related("causa"):
        minutos = inc.minutos(hasta=ahora)
        por_causa[str(inc.causa)] = por_causa.get(str(inc.causa), 0) + minutos
        if inc.causa.descuenta_tiempo:
            incidencias_min += minutos
    disponible = hoja.operarios.count() * max(0, settings.JORNADA_EFECTIVA_MIN - incidencias_min)

    estados = [a.estado for a in acciones]
    return {
        "acciones": len(acciones),
        "efectivas": len(efectivas),
        "efectividad_pct": round(100 * len(efectivas) / len(atendidas), 1) if atendidas else None,
        "resultados": {"ok": estados.count("OK"), "sin_ok": estados.count("SIN_OK"),
                       "pasadas": estados.count("PASADA_A_BRIGADA"), "no_visitadas": estados.count("NO_VISITADA"),
                       "en_curso": estados.count("EN_CURSO")},
        "pasadas_a_brigada": [{"servicio": a.orden.etiqueta, "brigada": a.pasada_a.nombre}
                              for a in acciones if a.estado == "PASADA_A_BRIGADA"],
        "no_visitadas": [a.orden.etiqueta for a in acciones if a.no_visitada],
        "tiempo_real_min": real,
        "tiempo_normado_efectivo_min": normado_efectivo,
        "productividad_pct": round(100 * normado_efectivo / real, 1) if real else None,
        "incidencias_min": incidencias_min,
        "incidencias_por_causa": por_causa,
        "tiempo_disponible_min": disponible,
        "ocupacion_pct": round(100 * real / disponible, 1) if disponible else None,
        "acciones_sin_norma": [a.pk for a in acciones if normas[a.pk] is None],
        "acciones_sin_tiempo_real": [a.pk for a in acciones if a.hora_fin and a.tiempo_real_min is None],
        "acciones_sin_cerrar": [a.pk for a in acciones if a.estado == "EN_CURSO"],
    }


def historial_servicio(numero_servicio, hasta=None, dias=None):
    """Acciones sobre un mismo número de servicio, con los operarios de cada hoja (seguimiento y reincidencias)."""
    qs = (
        Accion.objects.filter(orden__numero_servicio=numero_servicio).exclude(orden__numero_servicio="")
        .select_related("hoja__brigada", "orden")
        .prefetch_related("hoja__operarios", "claves")
        .order_by("hoja__fecha", "numero")
    )
    if hasta and dias:
        qs = qs.filter(hoja__fecha__gte=hasta - timedelta(days=dias), hoja__fecha__lte=hasta)
    return qs
