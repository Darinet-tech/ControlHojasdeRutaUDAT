from collections import Counter

from django.core.exceptions import ValidationError as ErrorDjango
from django.utils import timezone
from rest_framework import serializers

from catalogos.models import (Brigada, Gabinete, CausaIncidencia, Centro, Clave, NormaTrabajo, Operario, TipoMantenimiento, TipoOrden,
                              TipoTrabajo, Vehiculo)
from operacion.models import CantidadDeTrabajo, Accion, HojaDeRuta, Incidencia, OrdenServicio
from operacion.services import (avance_gabinete, datos_de_trabajos, norma_de_trabajo, trabajos_incompletos, momento_del_corte, norma_accion, norma_de_tipo, resumen_hoja, sugerir_ok, validar_claves_de_la_accion,
                                validar_operarios_libres)


# ---------------------------------------------------------------- catálogos (solo lectura)

class BrigadaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brigada
        fields = ["id", "nombre", "activa"]


class CentroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Centro
        fields = ["id", "codigo", "nombre", "activo"]


class VehiculoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehiculo
        fields = ["id", "chapa", "descripcion", "activo"]


class OperarioSerializer(serializers.ModelSerializer):
    brigada_nombre = serializers.CharField(source="brigada.nombre", read_only=True)

    class Meta:
        model = Operario
        fields = ["id", "clave", "nombre", "brigada", "brigada_nombre", "activo"]


class TipoOrdenSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoOrden
        fields = ["id", "codigo", "nombre", "fila_parte"]


class TipoMantenimientoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoMantenimiento
        fields = ["id", "codigo", "nombre", "fila_parte"]


class GabineteSerializer(serializers.ModelSerializer):
    centro_codigo = serializers.CharField(source="centro.codigo", read_only=True, default=None)
    total_regletas = serializers.IntegerField(read_only=True)

    class Meta:
        model = Gabinete
        fields = ["id", "nombre", "centro", "centro_codigo", "total_regletas"]


class TipoTrabajoSerializer(serializers.ModelSerializer):
    norma_min = serializers.SerializerMethodField(help_text="Norma vigente hoy (minutos); por unidad o por metro según el trabajo.")
    opciones = serializers.SerializerMethodField()
    etiqueta = serializers.CharField(read_only=True)

    class Meta:
        model = TipoTrabajo
        fields = ["id", "nombre", "etiqueta", "especialidad", "clave", "fuerza_trabajo", "descripcion", "medida", "unidad", "norma_min", "opciones", "activo"]

    def _vigente(self, tipo, opcion_id):
        hoy = timezone.localdate()
        vigentes = [n for n in tipo.normas.all()
                    if n.opcion_id == opcion_id and n.vigente_desde <= hoy and (n.vigente_hasta is None or n.vigente_hasta >= hoy)]
        return max(vigentes, key=lambda n: n.vigente_desde).minutos if vigentes else None

    def get_norma_min(self, tipo):
        return None if tipo.medida == "TIPO" else self._vigente(tipo, None)

    def get_opciones(self, tipo):
        if tipo.medida != "TIPO":
            return []
        return [{"id": o.pk, "nombre": o.nombre, "norma_min": self._vigente(tipo, o.pk)} for o in tipo.opciones.all() if o.activa]


class CausaIncidenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = CausaIncidencia
        fields = ["id", "codigo", "nombre", "descuenta_tiempo"]


class ClaveSerializer(serializers.ModelSerializer):
    grupo = serializers.CharField(source="grupo.nombre", read_only=True)
    norma_min = serializers.SerializerMethodField(help_text="Norma general vigente hoy (minutos).")

    class Meta:
        model = Clave
        fields = ["id", "codigo", "grupo", "descripcion", "clasificacion", "ambito", "norma_min", "activa"]

    def get_norma_min(self, clave):
        hoy = timezone.localdate()
        generales = [n for n in clave.normas.all() if n.tipo_orden_id is None and n.vigente_desde <= hoy
                     and (n.vigente_hasta is None or n.vigente_hasta >= hoy)]
        return max(generales, key=lambda n: n.vigente_desde).minutos if generales else None


# ---------------------------------------------------------------- operación

class IncidenciaSerializer(serializers.ModelSerializer):
    causa_codigo = serializers.CharField(source="causa.codigo", read_only=True)
    causa_nombre = serializers.CharField(source="causa.nombre", read_only=True)
    minutos = serializers.SerializerMethodField()
    activa = serializers.BooleanField(read_only=True)

    class Meta:
        model = Incidencia
        fields = ["id", "causa", "causa_codigo", "causa_nombre", "inicio", "fin", "activa", "minutos", "observaciones"]

    def get_minutos(self, incidencia):
        return incidencia.minutos()


class IniciarIncidenciaSerializer(serializers.Serializer):
    causa = serializers.PrimaryKeyRelatedField(queryset=CausaIncidencia.objects.all())
    observaciones = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class AccionSerializer(serializers.ModelSerializer):
    numero_servicio = serializers.CharField(source="orden.numero_servicio", read_only=True)
    etiqueta = serializers.CharField(source="orden.etiqueta", read_only=True)
    categoria = serializers.CharField(source="orden.categoria", read_only=True)
    categoria_texto = serializers.CharField(source="orden.get_categoria_display", read_only=True)
    variante = serializers.CharField(source="orden.variante", read_only=True)
    variante_texto = serializers.CharField(source="orden.get_variante_display", read_only=True)
    tipo_mantenimiento = serializers.CharField(source="orden.tipo_mantenimiento.codigo", read_only=True, default=None)
    numero_orden = serializers.CharField(source="orden.numero_orden", read_only=True)
    trabajos = TipoTrabajoSerializer(many=True, read_only=True)
    tipo_orden = serializers.CharField(source="orden.tipo_orden.codigo", read_only=True, default=None)
    centro_codigo = serializers.CharField(source="centro.codigo", read_only=True, default=None)
    estado_orden = serializers.CharField(source="orden.estado", read_only=True)
    claves = ClaveSerializer(many=True, read_only=True)
    pasada_a_nombre = serializers.CharField(source="pasada_a.nombre", read_only=True, default=None)
    norma_min = serializers.SerializerMethodField(help_text="Norma de la clave mayor (minutos).")
    detalle_trabajos = serializers.SerializerMethodField(help_text="Orden de trabajo: la cantidad o el tipo anotado de cada trabajo y su norma.")
    trabajos_incompletos = serializers.SerializerMethodField(help_text="Orden de trabajo: trabajos a los que falta la cantidad o el tipo.")
    es_gabinete = serializers.BooleanField(read_only=True)
    regletas = serializers.IntegerField(read_only=True)
    norma_por_regleta = serializers.SerializerMethodField()
    avance_gabinete = serializers.SerializerMethodField(help_text="Regletas hechas frente a las del gabinete.")
    sugerencia_ok = serializers.SerializerMethodField()
    estado = serializers.SerializerMethodField()
    posterior_al_corte = serializers.SerializerMethodField(help_text="Se cerró después del corte de las 16:00: va en el complemento del parte siguiente.")
    agregada_despues = serializers.SerializerMethodField(help_text="Se agregó a la hoja después de generarla (durante la jornada).")
    visita_anterior = serializers.SerializerMethodField(help_text="Antecedente: la última visita cerrada a este mismo servicio.")

    class Meta:
        model = Accion
        fields = ["id", "hoja", "orden", "numero", "etiqueta", "categoria", "categoria_texto", "variante", "variante_texto", "anulada",
                  "numero_servicio", "tipo_mantenimiento",
                  "tipo_orden", "numero_orden", "trabajos", "centro", "centro_codigo", "estado_orden", "claves",
                  "descripcion_trabajo", "observaciones", "estado", "ok", "cliente_contactado", "pasada_a",
                  "pasada_a_nombre", "hora_fin", "tiempo_real_min", "norma_min", "sugerencia_ok", "posterior_al_corte", "agregada_despues",
                  "visita_anterior", "es_gabinete", "regletas", "regletas_mantenidas", "regletas_reparadas", "regletas_sustituidas",
                  "norma_por_regleta", "avance_gabinete", "detalle_trabajos", "trabajos_incompletos"]

    def get_detalle_trabajos(self, accion):
        fecha = accion.hoja.fecha
        return [{"trabajo": t.pk, "cantidad": cantidad, "opcion": opcion.pk if opcion else None, "opcion_nombre": opcion.nombre if opcion else None,
                 "norma_min": norma_de_trabajo(t, cantidad, opcion.pk if opcion else None, fecha)} for t, cantidad, opcion in datos_de_trabajos(accion)]

    def get_trabajos_incompletos(self, accion):
        return [t.pk for t in trabajos_incompletos(accion)]

    def get_avance_gabinete(self, accion):
        return avance_gabinete(accion)

    def get_norma_por_regleta(self, accion):
        return norma_de_tipo(accion.orden, accion.hoja.fecha) if accion.es_gabinete else None

    def get_agregada_despues(self, accion):
        generada = accion.hoja.generada_en
        return bool(generada and accion.creado_en > generada)

    def get_visita_anterior(self, accion):
        previa = (accion.orden.acciones.filter(pk__lt=accion.pk).exclude(hora_fin__isnull=True, no_visitada=False)
                  .select_related("hoja").prefetch_related("claves").order_by("-pk").first())
        if previa is None:
            return None
        claves = [c.codigo for c in previa.claves.all()]
        regletas = previa.regletas if previa.es_gabinete else 0
        if not (claves or previa.observaciones or regletas):
            return None
        return {"fecha": previa.hoja.fecha, "estado": previa.estado, "claves": claves, "observaciones": previa.observaciones, "regletas": regletas}

    def get_posterior_al_corte(self, accion):
        return bool(accion.hora_fin and accion.hora_fin > momento_del_corte(accion.hoja.fecha))

    def get_norma_min(self, accion):
        return norma_accion(accion)

    def get_sugerencia_ok(self, accion):
        return sugerir_ok(accion) if accion.estado == "EN_CURSO" else None

    def get_estado(self, accion):
        return accion.estado


class ActualizarAccionSerializer(serializers.ModelSerializer):
    """Mientras la acción no esté cerrada, el probador completa sus claves (o los trabajos, en una orden de trabajo)."""

    claves = serializers.PrimaryKeyRelatedField(many=True, queryset=Clave.objects.filter(activa=True), required=False)
    trabajos = serializers.PrimaryKeyRelatedField(many=True, queryset=TipoTrabajo.objects.filter(activo=True), required=False)
    centro = serializers.PrimaryKeyRelatedField(queryset=Centro.objects.all(), required=False)
    cantidades = serializers.ListField(child=serializers.DictField(), required=False, write_only=True,
                                       help_text="Orden de trabajo: [{trabajo, cantidad}] o [{trabajo, opcion}] de los trabajos de la orden.")

    class Meta:
        model = Accion
        fields = ["claves", "trabajos", "cantidades", "descripcion_trabajo", "observaciones", "centro",
                  "regletas_mantenidas", "regletas_reparadas", "regletas_sustituidas"]
        extra_kwargs = {c: {"max_value": 500} for c in ("regletas_mantenidas", "regletas_reparadas", "regletas_sustituidas")}

    def validate_claves(self, claves):
        try:
            validar_claves_de_la_accion(self.instance.orden.categoria, claves)
        except ErrorDjango as error:
            raise serializers.ValidationError(error.messages)
        return claves

    def validate_centro(self, centro):
        if centro.pk not in set(self.instance.hoja.centros.values_list("pk", flat=True)):
            raise serializers.ValidationError(f"El centro {centro.codigo} no es uno de los centros de la hoja.")
        return centro

    def validate(self, datos):
        trabajos = datos.get("trabajos")
        permitidos = {t.pk: t for t in (trabajos if trabajos is not None else self.instance.trabajos.all())}
        limpias = []
        for c in datos.get("cantidades", []):
            trabajo = permitidos.get(c.get("trabajo"))
            if trabajo is None:
                raise serializers.ValidationError({"cantidades": "Ese trabajo no es de esta orden."})
            if trabajo.medida == "TIPO":
                opcion = trabajo.opciones.filter(pk=c.get("opcion"), activa=True).first()
                if opcion is None:
                    raise serializers.ValidationError({"cantidades": f"Elija un tipo válido para {trabajo.nombre.lower()}."})
                limpias.append((trabajo, None, opcion))
            elif trabajo.medida in ("UNIDADES", "METROS"):
                try:
                    cantidad = float(str(c.get("cantidad")).replace(",", "."))
                except (TypeError, ValueError):
                    raise serializers.ValidationError({"cantidades": f"Escriba un número para {trabajo.nombre.lower()}."})
                if not 0 < cantidad <= 100000 or (trabajo.medida == "UNIDADES" and cantidad != int(cantidad)):
                    raise serializers.ValidationError({"cantidades": "La cantidad debe ser mayor que 0" + (" y entera." if trabajo.medida == "UNIDADES" else ".")})
                limpias.append((trabajo, round(cantidad, 2), None))
            else:
                raise serializers.ValidationError({"cantidades": f"{trabajo.nombre} no lleva cantidad."})
        datos["cantidades"] = limpias
        return datos

    def update(self, instance, validated_data):
        limpias = validated_data.pop("cantidades", [])
        instance = super().update(instance, validated_data)
        if "trabajos" in validated_data:  # lo que se quita de la orden pierde su cantidad
            instance.cantidades.exclude(trabajo__in=validated_data["trabajos"]).delete()
        for trabajo, cantidad, opcion in limpias:
            CantidadDeTrabajo.objects.update_or_create(accion=instance, trabajo=trabajo, defaults={"cantidad": cantidad, "opcion": opcion})
        return instance


class CrearAccionSerializer(serializers.Serializer):
    """Asigna un trabajo a la hoja. Se indica el tipo de acción y SOLO los datos que le corresponden (se validan en
    `operacion.services.obtener_orden`):

    - correctivo: numero_servicio
    - preventivo: tipo_mantenimiento + numero_servicio
    - orden_servicio: tipo_orden + numero_orden + numero_servicio
    - orden_trabajo: numero_orden + trabajos (no lleva número de servicio)

    O bien `orden`: una orden que ya existe (un pendiente o un no visitado)."""

    orden = serializers.PrimaryKeyRelatedField(queryset=OrdenServicio.objects.all(), required=False)
    categoria = serializers.ChoiceField(choices=OrdenServicio.Categoria.choices, default=OrdenServicio.Categoria.CORRECTIVO)
    numero_servicio = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    tipo_mantenimiento = serializers.PrimaryKeyRelatedField(queryset=TipoMantenimiento.objects.filter(activo=True), required=False, allow_null=True)
    tipo_orden = serializers.PrimaryKeyRelatedField(queryset=TipoOrden.objects.all(), required=False, allow_null=True)
    numero_orden = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    variante = serializers.ChoiceField(choices=OrdenServicio.Variante.choices, required=False, allow_blank=True, default="",
                                       help_text="Correctivo: TP o NHP (Nauta Hogar Plus). Alta de orden de servicio: NH (Nauta Hogar).")
    trabajos = serializers.PrimaryKeyRelatedField(many=True, queryset=TipoTrabajo.objects.filter(activo=True), required=False)
    centro = serializers.PrimaryKeyRelatedField(queryset=Centro.objects.all(), required=False, allow_null=True,
                                                help_text="Obligatorio si la hoja trabaja en varios centros.")
    claves = serializers.PrimaryKeyRelatedField(many=True, queryset=Clave.objects.filter(activa=True), required=False)
    descripcion_trabajo = serializers.CharField(required=False, allow_blank=True, default="")


class PasarABrigadaSerializer(serializers.Serializer):
    brigada = serializers.PrimaryKeyRelatedField(queryset=Brigada.objects.filter(activa=True))


class CerrarSinOkSerializer(serializers.Serializer):
    observaciones = serializers.CharField(required=False, allow_blank=True, default=None, allow_null=True)


class DarOkSerializer(serializers.Serializer):
    cliente_contactado = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")  # obligatorio solo en correctivos


class CambiarTipoSerializer(serializers.Serializer):
    categoria = serializers.ChoiceField(choices=["CORRECTIVO", "PREVENTIVO"])
    tipo_mantenimiento = serializers.PrimaryKeyRelatedField(queryset=TipoMantenimiento.objects.filter(activo=True), required=False, allow_null=True)
    variante = serializers.ChoiceField(choices=["", "TP", "NHP"], required=False, allow_blank=True, default="")


class HojaSerializer(serializers.ModelSerializer):
    brigada_nombre = serializers.CharField(source="brigada.nombre", read_only=True)
    informa_con_texto = serializers.BooleanField(source="brigada.informa_con_texto", read_only=True)
    centros_codigos = serializers.SerializerMethodField()
    centros_etiqueta = serializers.CharField(source="etiqueta_centros", read_only=True)
    vehiculo_chapa = serializers.CharField(source="vehiculo.chapa", read_only=True, default=None)
    operarios_nombres = serializers.SerializerMethodField()
    cantidad_acciones = serializers.SerializerMethodField()
    resultados = serializers.SerializerMethodField()
    incidencia_activa = serializers.SerializerMethodField()
    generada = serializers.SerializerMethodField()

    class Meta:
        model = HojaDeRuta
        fields = ["id", "fecha", "brigada", "brigada_nombre", "centros", "centros_codigos", "centros_etiqueta", "vehiculo",
                  "vehiculo_chapa", "operarios", "operarios_nombres", "hora_inicio", "justificacion_inicio", "observaciones", "trabajos_realizados",
                  "informa_con_texto", "cerrada", "cerrada_en", "reabierta_en", "generada", "generada_en", "cantidad_acciones", "resultados", "incidencia_activa"]
        read_only_fields = ["fecha", "hora_inicio", "cerrada", "cerrada_en", "reabierta_en", "generada_en"]  # fecha y hora de inicio las pone el servidor al crear
        extra_kwargs = {
            "centros": {"error_messages": {"empty": "Indique al menos un centro."}},
            "operarios": {"error_messages": {"empty": "La hoja de ruta necesita al menos un operario."}},
        }

    def get_generada(self, hoja):
        return hoja.generada_en is not None

    def get_centros_codigos(self, hoja):
        return sorted(c.codigo for c in hoja.centros.all())

    def validate_centros(self, centros):
        if not centros:
            raise serializers.ValidationError("Indique al menos un centro.")
        inactivos = [c.codigo for c in centros if not c.activo]
        if inactivos:
            raise serializers.ValidationError(f"Centros inactivos: {', '.join(inactivos)}")
        return centros

    def get_operarios_nombres(self, hoja):
        return [o.nombre for o in hoja.operarios.all()]

    def get_cantidad_acciones(self, hoja):
        return len(hoja.acciones.all())

    def get_resultados(self, hoja):
        cuenta = Counter(a.estado for a in hoja.acciones.all())
        return {"ok": cuenta["OK"], "sin_ok": cuenta["SIN_OK"], "pasadas": cuenta["PASADA_A_BRIGADA"],
                "no_visitadas": cuenta["NO_VISITADA"], "en_curso": cuenta["EN_CURSO"], "anuladas": cuenta["ANULADA"]}

    def get_incidencia_activa(self, hoja):
        activa = next((i for i in hoja.incidencias.all() if i.fin is None), None)
        return str(activa.causa) if activa else None

    def validate_operarios(self, operarios):
        if not operarios:
            raise serializers.ValidationError("La hoja de ruta necesita al menos un operario.")
        inactivos = [o.clave for o in operarios if not o.activo]
        if inactivos:
            raise serializers.ValidationError(f"Operarios inactivos: {', '.join(inactivos)}")
        return operarios

    def validate(self, datos):
        """Un operario no puede estar en más de una hoja de ruta el mismo día."""
        hoja = self.instance
        if hoja and "centros" in datos:  # no se puede quitar un centro que ya tiene servicios asignados
            usados = set(hoja.acciones.exclude(centro__isnull=True).values_list("centro_id", flat=True))
            quitados = sorted(c.codigo for c in hoja.centros.all() if c.pk in usados and c.pk not in {x.pk for x in datos["centros"]})
            if quitados:
                raise serializers.ValidationError({"centros": f"No se puede quitar el centro {', '.join(quitados)}: ya tiene servicios en esta hoja."})
        if "operarios" in datos:
            fecha = hoja.fecha if hoja else timezone.localdate()
            operarios = datos.get("operarios", list(hoja.operarios.all()) if hoja else [])
            try:
                validar_operarios_libres(fecha, operarios, excluir_hoja=hoja)
            except ErrorDjango as error:
                raise serializers.ValidationError({"operarios": error.messages})
        return datos


class HojaDetalleSerializer(HojaSerializer):
    acciones = AccionSerializer(many=True, read_only=True)
    incidencias = IncidenciaSerializer(many=True, read_only=True)
    resumen = serializers.SerializerMethodField()

    class Meta(HojaSerializer.Meta):
        fields = HojaSerializer.Meta.fields + ["acciones", "incidencias", "resumen"]

    def get_resumen(self, hoja):
        return resumen_hoja(hoja)


class OrdenSerializer(serializers.ModelSerializer):
    tipo_orden_codigo = serializers.CharField(source="tipo_orden.codigo", read_only=True, default=None)
    categoria_texto = serializers.CharField(source="get_categoria_display", read_only=True)
    brigada_pendiente_nombre = serializers.CharField(source="brigada_pendiente.nombre", read_only=True, default=None)
    estado_texto = serializers.CharField(source="get_estado_display", read_only=True)
    ultima_fecha = serializers.SerializerMethodField(help_text="Fecha de la última acción sobre la orden.")
    ultimo_centro = serializers.SerializerMethodField(help_text="Código del centro de la última acción.")
    ultima_observacion = serializers.SerializerMethodField(help_text="Observación de la última acción: por qué quedó pendiente.")
    ultimas_claves = serializers.SerializerMethodField(help_text="Claves de la última acción.")

    class Meta:
        model = OrdenServicio
        fields = ["id", "etiqueta", "categoria", "categoria_texto", "numero_orden", "numero_servicio", "tipo_orden", "tipo_orden_codigo",
                  "fecha_reporte", "estado", "estado_texto",
                  "brigada_pendiente", "brigada_pendiente_nombre", "ultima_fecha", "ultimo_centro", "ultima_observacion", "ultimas_claves"]

    def _ultima(self, orden):
        acciones = sorted(orden.acciones.all(), key=lambda a: (a.hoja.fecha, a.pk))
        return acciones[-1] if acciones else None

    def get_ultima_fecha(self, orden):
        ultima = self._ultima(orden)
        return ultima.hoja.fecha.isoformat() if ultima else None

    def get_ultima_observacion(self, orden):
        ultima = self._ultima(orden)
        return ultima.observaciones if ultima else ""

    def get_ultimas_claves(self, orden):
        ultima = self._ultima(orden)
        return sorted(c.codigo for c in ultima.claves.all()) if ultima else []

    def get_ultimo_centro(self, orden):
        ultima = self._ultima(orden)
        return ultima.centro.codigo if ultima and ultima.centro_id else None


class HistorialSerializer(serializers.ModelSerializer):
    """Una línea del historial de un servicio: quién lo trabajó, cuándo y con qué resultado (calidad / reincidencias)."""

    fecha = serializers.DateField(source="hoja.fecha")
    brigada = serializers.CharField(source="hoja.brigada.nombre")
    operarios = serializers.SerializerMethodField()
    claves = serializers.SerializerMethodField()
    estado = serializers.SerializerMethodField()

    class Meta:
        model = Accion
        fields = ["id", "fecha", "brigada", "operarios", "claves", "estado", "ok", "tiempo_real_min"]

    def get_operarios(self, accion):
        return [o.nombre for o in accion.hoja.operarios.all()]

    def get_claves(self, accion):
        return [c.codigo for c in accion.claves.all()]

    def get_estado(self, accion):
        return accion.estado
