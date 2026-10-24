from django.db import models
from django.db.models import Q


class Brigada(models.Model):
    nombre = models.CharField(max_length=60, unique=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Centro(models.Model):
    codigo = models.CharField(max_length=5, unique=True, help_text="Ej.: NG, FI, FO")
    nombre = models.CharField(max_length=60, unique=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"


class Vehiculo(models.Model):
    chapa = models.CharField(max_length=20, unique=True)
    descripcion = models.CharField(max_length=120, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["chapa"]

    def __str__(self):
        return self.chapa


class Operario(models.Model):
    clave = models.CharField("clave del operario", max_length=20, unique=True)
    nombre = models.CharField(max_length=120)
    brigada = models.ForeignKey(Brigada, on_delete=models.PROTECT, related_name="operarios")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.clave} - {self.nombre}"


class CausaIncidencia(models.Model):
    """Claves oficiales de incidencia (100 Lluvia, 101 Traslado de personal...).

    Mientras una incidencia está activa corre un contador; si `descuenta_tiempo` es verdadero, esos minutos se
    restan del tiempo disponible y del tiempo real de las acciones (para que la productividad sea real).
    """

    codigo = models.CharField(max_length=5, unique=True)
    nombre = models.CharField(max_length=80, unique=True)
    descuenta_tiempo = models.BooleanField(
        default=True, help_text="Si está marcado, el tiempo de esta incidencia no cuenta como tiempo de trabajo."
    )

    class Meta:
        verbose_name = "causa de incidencia"
        verbose_name_plural = "causas de incidencia"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class TipoOrden(models.Model):
    """Tipo de orden de servicio. Las normas de tiempo pueden variar según el tipo."""

    codigo = models.CharField(max_length=10, unique=True)
    nombre = models.CharField(max_length=80)
    descripcion = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "tipo de orden de servicio"
        verbose_name_plural = "tipos de orden de servicio"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class GrupoClave(models.Model):
    """Actividad a la que pertenece una clave (Aparatos, Pizarra, Reparador, Cable, Datos...)."""

    nombre = models.CharField(max_length=60, unique=True)

    class Meta:
        verbose_name = "grupo / actividad de claves"
        verbose_name_plural = "grupos / actividades de claves"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Clave(models.Model):
    class Clasificacion(models.TextChoices):
        EFECTIVA = "EFECTIVA", "Efectiva (servicio restablecido)"
        NO_EFECTIVA = "NO_EFECTIVA", "No efectiva (responsabilidad del cliente)"
        PENDIENTE = "PENDIENTE", "Pendiente (depende de otra brigada)"

    class Ambito(models.TextChoices):
        ACCION = "ACCION", "Clave de acción del operario"
        ORDEN = "ORDEN", "Clave de cierre de la orden de servicio"
        DESCRIPTIVO = "DESCRIPTIVO", "Trabajo descriptivo (Cable / Línea)"

    codigo = models.CharField(max_length=20, unique=True)
    grupo = models.ForeignKey(GrupoClave, on_delete=models.PROTECT, related_name="claves")
    descripcion = models.CharField(max_length=300, blank=True)
    clasificacion = models.CharField(max_length=12, choices=Clasificacion.choices)
    ambito = models.CharField(max_length=12, choices=Ambito.choices, default=Ambito.ACCION)
    activa = models.BooleanField(default=True)
    revisar = models.BooleanField(
        default=False, help_text="Marcada por la importación: el administrador debe confirmar sus datos."
    )
    notas = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["codigo"]

    def __str__(self):
        return self.codigo

    @property
    def es_pendiente(self):
        return self.clasificacion == self.Clasificacion.PENDIENTE

    @property
    def es_efectiva(self):
        return self.clasificacion == self.Clasificacion.EFECTIVA


class NormaTiempo(models.Model):
    """Norma de tiempo (minutos) por clave y, opcionalmente, por tipo de orden, con vigencia en el tiempo.

    Si existe una norma para el tipo de orden concreto se usa esa; si no, la norma general (tipo_orden vacío).
    Al cambiar una norma se crea una nueva con otra fecha de inicio: los meses anteriores no se alteran.
    """

    clave = models.ForeignKey(Clave, on_delete=models.CASCADE, related_name="normas")
    tipo_orden = models.ForeignKey(
        TipoOrden, null=True, blank=True, on_delete=models.CASCADE, related_name="normas",
        help_text="Vacío = norma general para cualquier tipo de orden.",
    )
    minutos = models.PositiveSmallIntegerField()
    vigente_desde = models.DateField()
    vigente_hasta = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "norma de tiempo"
        verbose_name_plural = "normas de tiempo"
        ordering = ["clave__codigo", "-vigente_desde"]
        constraints = [
            models.UniqueConstraint(
                fields=["clave", "tipo_orden", "vigente_desde"], name="norma_unica_por_inicio"
            )
        ]

    def __str__(self):
        return f"{self.clave} = {self.minutos} min"

    @classmethod
    def vigente(cls, clave, tipo_orden, fecha):
        qs = cls.objects.filter(clave=clave, vigente_desde__lte=fecha).filter(
            Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=fecha)
        )
        if tipo_orden is not None:
            especifica = qs.filter(tipo_orden=tipo_orden).order_by("-vigente_desde").first()
            if especifica:
                return especifica
        return qs.filter(tipo_orden__isnull=True).order_by("-vigente_desde").first()


class TipoMantenimiento(models.Model):
    """Tipo de mantenimiento preventivo: MPPI, MPPE, MPI."""

    codigo = models.CharField(max_length=10, unique=True)
    nombre = models.CharField(max_length=80)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "tipo de mantenimiento"
        verbose_name_plural = "tipos de mantenimiento"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class TipoTrabajo(models.Model):
    """Trabajo de una orden de trabajo (sustitución de postes, de cajas terminales...). Lo gestionan los especialistas."""

    nombre = models.CharField(max_length=100, unique=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "tipo de trabajo (orden de trabajo)"
        verbose_name_plural = "tipos de trabajo (órdenes de trabajo)"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class NormaTrabajo(models.Model):
    """Norma de tiempo (minutos) de un tipo de trabajo, con vigencia: igual que las normas de las claves."""

    tipo_trabajo = models.ForeignKey(TipoTrabajo, on_delete=models.CASCADE, related_name="normas")
    minutos = models.PositiveSmallIntegerField()
    vigente_desde = models.DateField()
    vigente_hasta = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "norma de tiempo de un trabajo"
        verbose_name_plural = "normas de tiempo de los trabajos"
        ordering = ["tipo_trabajo__nombre", "-vigente_desde"]
        constraints = [models.UniqueConstraint(fields=["tipo_trabajo", "vigente_desde"], name="norma_trabajo_unica_por_inicio")]

    def __str__(self):
        return f"{self.tipo_trabajo} = {self.minutos} min"

    @classmethod
    def vigente(cls, tipo_trabajo, fecha):
        return (cls.objects.filter(tipo_trabajo=tipo_trabajo, vigente_desde__lte=fecha)
                .filter(Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=fecha)).order_by("-vigente_desde").first())
