"""Envío automático del informe diario por correo, con corte a una hora fija (16:00) aunque haya hojas abiertas.

Sale desde la cuenta del jefe de la UDAT (`INFORME_REMITENTE`) por el servidor `EMAIL_HOST` (sin usuario ni contraseña) hacia
los destinatarios activos que define el administrador. Cada intento queda registrado, con copia de los archivos enviados,
para poder auditarlo. Se programa con el planificador del sistema operativo (ver README): `python manage.py enviar_informe_diario`.
"""
from email.utils import parseaddr

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from .informes import fecha_larga, minutos_a_texto, pct, renderizar, reunir_datos
from .models import DestinatarioInforme, HojaDeRuta, InformeEnviado


def _cuerpo(datos, corte):
    t, hojas = datos["resumen"]["totales"], datos["hojas"]
    abiertas = [h for h in hojas if not h["cerrada"]]
    lineas = [
        "Unidad de Asistencia Técnica (UDAT)",
        f"Informe diario — {fecha_larga(datos['fecha'])}",
        f"Corte a las {timezone.localtime(corte):%H:%M}",
        "",
        f"Hojas de ruta: {t['hojas']} ({t['hojas'] - len(abiertas)} cerradas y {len(abiertas)} abiertas al corte)",
        f"Servicios: {t['acciones']} · con OK: {t['ok']} · sin OK: {t['sin_ok']} · pasadas a otra brigada: {t['pasadas']} · "
        f"no visitadas: {t['no_visitadas']} · en curso: {t['en_curso']}",
        f"Efectividad: {pct(t['efectividad_pct'])} · Productividad: {pct(t['productividad_pct'])} · "
        f"Tiempo real: {minutos_a_texto(t['tiempo_real_min'])} · Incidencias: {minutos_a_texto(t['incidencias_min'])}",
    ]
    if abiertas:
        lineas += ["", "Hojas todavía abiertas al corte (su información puede cambiar al terminar la jornada):"]
        lineas += [f"  - {h['centros']} · {h['brigada']} ({h['operarios_claves']})" for h in abiertas]
    lineas += ["", "Se adjuntan:", "  - PDF: resumen del día y cada hoja de ruta con el formato de la hoja original.",
               "  - Excel: resumen, hojas de ruta y hoja de auditoría con una fila por servicio.", "",
               "Mensaje generado automáticamente por el sistema de la UDAT."]
    return "\n".join(lineas)


def enviar_informe_diario(fecha=None, ahora=None, forzar=False, simular=False):
    """Genera y envía el informe del día con el estado de las hojas en `ahora` (el corte).

    Devuelve (estado, mensaje, registro). `estado` es ENVIADO, ERROR, OMITIDO, YA_ENVIADO o SIMULADO.
    - Si el día no tiene hojas de ruta, no se envía nada (queda registrado como omitido).
    - Si ya se envió el informe de ese día, no se repite (salvo `forzar`).
    - Si hay un fallo (sin destinatarios, servidor de correo caído...), queda registrado como error y se puede reintentar."""
    ahora = ahora or timezone.now()
    fecha = fecha or timezone.localtime(ahora).date()
    if not forzar and not simular and InformeEnviado.objects.filter(fecha=fecha, estado=InformeEnviado.Estado.ENVIADO).exists():
        return "YA_ENVIADO", f"El informe del {fecha:%d/%m/%Y} ya se envió. Use forzar para enviarlo de nuevo.", None

    def registrar(estado, detalle="", **campos):
        if simular:
            return None
        return InformeEnviado.objects.create(fecha=fecha, corte=ahora, estado=estado, detalle=detalle, **campos)

    if not HojaDeRuta.objects.filter(fecha=fecha).exists():
        mensaje = f"No hay hojas de ruta el {fecha:%d/%m/%Y}: no se envía el informe."
        return InformeEnviado.Estado.OMITIDO, mensaje, registrar(InformeEnviado.Estado.OMITIDO, mensaje)

    destinatarios = list(DestinatarioInforme.objects.filter(activo=True).values_list("correo", flat=True))
    remitente = settings.INFORME_REMITENTE
    if not destinatarios:
        mensaje = "No hay destinatarios activos: el administrador debe definir la lista en la administración."
        return InformeEnviado.Estado.ERROR, mensaje, registrar(InformeEnviado.Estado.ERROR, mensaje, remitente=remitente)

    datos = reunir_datos(fecha, ahora=ahora, corte=ahora)
    pdf, tipo_pdf, nombre_pdf = renderizar(datos, "pdf")
    excel, tipo_excel, nombre_excel = renderizar(datos, "xlsx")
    asunto = f"UDAT · Informe diario {fecha:%d/%m/%Y} (corte {timezone.localtime(ahora):%H:%M})"
    campos = {"remitente": remitente, "destinatarios": ", ".join(destinatarios), "asunto": asunto, "pdf": pdf, "excel": excel}
    if simular:
        return "SIMULADO", f"Se enviaría «{asunto}» a: {', '.join(destinatarios)} (desde {remitente}).", None

    mensaje = EmailMessage(asunto, _cuerpo(datos, ahora), from_email=remitente, to=destinatarios, reply_to=[parseaddr(remitente)[1]])
    mensaje.attach(nombre_pdf, pdf, tipo_pdf)
    mensaje.attach(nombre_excel, excel, tipo_excel)
    try:
        mensaje.send(fail_silently=False)
    except Exception as error:  # servidor caído, correo rechazado, tiempo agotado...
        detalle = f"{type(error).__name__}: {error}"
        return InformeEnviado.Estado.ERROR, detalle, registrar(InformeEnviado.Estado.ERROR, detalle, **campos)
    return InformeEnviado.Estado.ENVIADO, f"Informe enviado a {len(destinatarios)} destinatario(s).", registrar(InformeEnviado.Estado.ENVIADO, **campos)
