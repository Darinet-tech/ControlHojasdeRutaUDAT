from django.conf import settings
from django.db import models

from django.utils import timezone

from catalogos.models import (Brigada, CausaIncidencia, Centro, Clave, Operario, TipoMantenimiento, TipoOrden, TipoTrabajo,
                              Vehiculo)


def hora_inicio_jornada():
    return settings.HORA_INICIO_JORNADA


class Auditable(models.Model):
    """Quién y cuándo creó/modificó cada registro (varios probadores trabajan a la vez)."""

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    modificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    modificado_en = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def etiqueta_orden(categoria, numero_servicio="", tipo_mantenimiento="", tipo_orden="", numero_orden=""):
    """Cómo se identifica un trabajo en las hojas y los informes.

    Correctivo: 46-326407 · Preventivo: MPPE 46-326407 · Orden de servicio: TA 1234 46-326407 · Orden de trabajo: OT 567
    """
    partes = {
        "PREVENTIVO": [tipo_mantenimiento, numero_servicio],
        "ORDEN_SERVICIO": [tipo_orden, numero_orden, numero_servicio],
        "ORDEN_TRABAJO": ["OT", numero_orden],
    }.get(categoria, [numero_servicio])
    return " ".join(p for p in partes if p)


def estado_de_accion(ok, pasada_a_id, no_visitada, hora_fin):
    """OK, PASADA_A_BRIGADA, NO_VISITADA, SIN_OK (cerrada sin OK) o EN_CURSO."""
    if ok:
        return "OK"
    if pasada_a_id:
        return "PASADA_A_BRIGADA"
    if no_visitada:
        return "NO_VISITADA"
    return "SIN_OK" if hora_fin else "EN_CURSO"


class HojaDeRuta(Auditable):
    """Se crea solo cuando se definen los operarios y los servicios a reparar; no hay hojas vacías."""

    fecha = models.DateField(db_index=True)
    brigada = models.ForeignKey(Brigada, on_delete=models.PROTECT, related_name="hojas")
    centros = models.ManyToManyField(
        Centro, related_name="hojas", help_text="Un vehículo puede trabajar en varios centros en la misma hoja de ruta."
    )
    vehiculo = models.ForeignKey(Vehiculo, null=True, blank=True, on_delete=models.PROTECT, related_name="hojas")
    operarios = models.ManyToManyField(Operario, related_name="hojas")
    hora_inicio = models.TimeField(
        default=hora_inicio_jornada, null=True, blank=True,
        help_text="Inicio de la jornada (08:00 por defecto): base del tiempo real de la primera acción.",
    )
    observaciones = models.TextField(blank=True)
    cerrada = models.BooleanField(default=False, editable=False, help_text="Se cierra al finalizar el día.")
    cerrada_en = models.DateTimeField(null=True, blank=True, editable=False)
    cerrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )

    class Meta:
        verbose_name = "hoja de ruta"
        verbose_name_plural = "hojas de ruta"
        ordering = ["-fecha", "brigada__nombre"]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y} · {self.brigada} · {self.etiqueta_centros}"

    @property
    def etiqueta_centros(self):
        """Códigos de los centros de la hoja, p. ej. 'NG + FI'."""
        return " + ".join(sorted(c.codigo for c in self.centros.all()))


class Incidencia(Auditable):
    """Periodo en que la hoja de ruta no trabajó por una causa oficial (100 Lluvia, 106 Transporte...).

    El contador arranca al registrarla y se detiene al confirmar el cambio de estado o al cerrar la hoja.
    """

    hoja = models.ForeignKey(HojaDeRuta, on_delete=models.CASCADE, related_name="incidencias")
    causa = models.ForeignKey(CausaIncidencia, on_delete=models.PROTECT, related_name="incidencias")
    inicio = models.DateTimeField(default=timezone.now)
    fin = models.DateTimeField(null=True, blank=True, help_text="Vacío = contador activo.")
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "incidencia"
        verbose_name_plural = "incidencias"
        ordering = ["hoja", "inicio"]

    def __str__(self):
        return f"{self.causa} ({self.hoja})"

    @property
    def activa(self):
        return self.fin is None

    def minutos(self, hasta=None):
        """Minutos transcurridos; si sigue activa cuenta hasta `hasta` (por defecto, ahora)."""
        fin = self.fin or hasta or timezone.now()
        return max(0, round((fin - self.inicio).total_seconds() / 60))


class OrdenServicio(Auditable):
    """Servicio a reparar. Varias órdenes/acciones sobre el mismo número de servicio permiten medir reincidencias."""

    class Estado(models.TextChoices):
        ABIERTA = "ABIERTA", "Abierta"
        PENDIENTE = "PENDIENTE", "Pendiente de otra brigada"
        NO_VISITADA = "NO_VISITADA", "No visitada (pasa al siguiente día)"
        RESTABLECIDA = "RESTABLECIDA", "Restablecida (OK)"

    class Categoria(models.TextChoices):
        CORRECTIVO = "CORRECTIVO", "Correctivo"
        PREVENTIVO = "PREVENTIVO", "Preventivo"
        ORDEN_SERVICIO = "ORDEN_SERVICIO", "Orden de servicio"
        ORDEN_TRABAJO = "ORDEN_TRABAJO", "Orden de trabajo"

    categoria = models.CharField(max_length=14, choices=Categoria.choices, default=Categoria.CORRECTIVO, db_index=True)
    numero_servicio = models.CharField(max_length=30, blank=True, db_index=True, help_text="Servicio telefónico (no aplica a las órdenes de trabajo).")
    tipo_mantenimiento = models.ForeignKey(TipoMantenimiento, null=True, blank=True, on_delete=models.PROTECT, related_name="ordenes",
                                           help_text="Solo preventivos: MPPI, MPPE o MPI.")
    tipo_orden = models.ForeignKey(TipoOrden, null=True, blank=True, on_delete=models.PROTECT, related_name="ordenes",
                                   help_text="Solo órdenes de servicio: A, TA, TE...")
    numero_orden = models.CharField(max_length=30, blank=True, db_index=True, help_text="Número de la orden de servicio o de la orden de trabajo.")
    trabajos = models.ManyToManyField(TipoTrabajo, blank=True, related_name="ordenes",
                                      help_text="Solo órdenes de trabajo: los trabajos de la orden; cada acción parte de ellos.")
    fecha_reporte = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.ABIERTA, db_index=True)
    brigada_pendiente = models.ForeignKey(
        Brigada, null=True, blank=True, on_delete=models.SET_NULL, related_name="ordenes_pendientes",
        help_text="Brigada que debe atender la orden: la destino del pendiente, o la que no la visitó.",
    )

    class Meta:
        verbose_name = "orden de servicio"
        verbose_name_plural = "órdenes de servicio"
        ordering = ["-creado_en"]

    def __str__(self):
        return self.etiqueta

    @property
    def etiqueta(self):
        return etiqueta_orden(self.categoria, self.numero_servicio,
                              self.tipo_mantenimiento.codigo if self.tipo_mantenimiento_id else "",
                              self.tipo_orden.codigo if self.tipo_orden_id else "", self.numero_orden)


class Accion(Auditable):
    """Visita/trabajo de una hoja de ruta sobre una orden. Puede llevar varias claves de cierre.

    `ok` lo decide el probador tras hablar con el cliente: True = servicio restablecido y certificado.
    Sin OK la acción no cuenta como efectiva, aunque alguna de sus claves sea de clasificación efectiva.
    """

    hoja = models.ForeignKey(HojaDeRuta, on_delete=models.CASCADE, related_name="acciones")
    orden = models.ForeignKey(OrdenServicio, on_delete=models.PROTECT, related_name="acciones")
    numero = models.PositiveSmallIntegerField("n.º en la hoja", default=1)
    centro = models.ForeignKey(
        Centro, null=True, blank=True, on_delete=models.PROTECT, related_name="acciones",
        help_text="Centro donde está el servicio (uno de los centros de la hoja).",
    )
    claves = models.ManyToManyField(Clave, blank=True, related_name="acciones")
    trabajos = models.ManyToManyField(TipoTrabajo, blank=True, related_name="acciones",
                                      help_text="Solo órdenes de trabajo: qué trabajos se hacen (sustitución de postes, de cajas...).")
    descripcion_trabajo = models.TextField(blank=True, help_text="Para trabajos descriptivos (Cable / Línea).")
    hora_fin = models.DateTimeField(
        null=True, blank=True, editable=False,
        help_text="Se genera al dar OK, pasar a otra brigada o cerrar sin OK.",
    )
    tiempo_real_min = models.PositiveSmallIntegerField(
        null=True, blank=True, editable=False,
        help_text="Hora de fin menos la hora de fin de la acción anterior de la hoja (o el inicio de la jornada).",
    )
    ok = models.BooleanField(default=False, editable=False)
    no_visitada = models.BooleanField(
        default=False, editable=False,
        help_text="La hoja se cerró sin que se atendiera este servicio: pasa al siguiente día.",
    )
    pasada_a = models.ForeignKey(
        Brigada, null=True, blank=True, on_delete=models.PROTECT, related_name="acciones_recibidas", editable=False,
        help_text="Brigada a la que se pasó la afectación (pendiente).",
    )
    cliente_contactado = models.CharField(
        max_length=120, blank=True, editable=False, help_text="Cliente con quien se certificó el OK."
    )
    certificada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    certificada_en = models.DateTimeField(null=True, blank=True, editable=False)
    observaciones = models.TextField(blank=True)

    class Meta:
        verbose_name = "acción"
        verbose_name_plural = "acciones"
        ordering = ["hoja", "numero"]

    def __str__(self):
        return f"{self.orden} ({self.hoja.fecha:%d/%m/%Y})"

    @property
    def estado(self):
        return estado_de_accion(self.ok, self.pasada_a_id, self.no_visitada, self.hora_fin)


class DestinatarioInforme(models.Model):
    """Persona que recibe el informe diario automático. La lista la define el administrador."""

    nombre = models.CharField(max_length=120)
    correo = models.EmailField(unique=True)
    activo = models.BooleanField(default=True, help_text="Desmarque para dejar de enviarle el informe sin borrarlo de la lista.")

    class Meta:
        verbose_name = "destinatario del informe diario"
        verbose_name_plural = "destinatarios del informe diario"
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} <{self.correo}>"


class InformeEnviado(models.Model):
    """Registro (y copia, para auditoría) de cada informe diario enviado por correo, con el estado en el momento del corte."""

    class Estado(models.TextChoices):
        ENVIADO = "ENVIADO", "Enviado"
        ERROR = "ERROR", "Error al enviar"
        OMITIDO = "OMITIDO", "Omitido"

    fecha = models.DateField(db_index=True, help_text="Día al que corresponde el informe.")
    corte = models.DateTimeField(help_text="Momento del corte: el informe refleja el estado de las hojas en ese instante.")
    estado = models.CharField(max_length=8, choices=Estado.choices)
    remitente = models.CharField(max_length=200, blank=True)
    destinatarios = models.TextField(blank=True)
    asunto = models.CharField(max_length=200, blank=True)
    detalle = models.TextField(blank=True, help_text="Motivo del error o de que se omitiera el envío.")
    pdf = models.BinaryField(null=True, blank=True, editable=False)
    excel = models.BinaryField(null=True, blank=True, editable=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "informe diario enviado"
        verbose_name_plural = "informes diarios enviados"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y} · {self.get_estado_display()}"
