from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path

from . import gabinetes_excel
from .campos import texto_norma
from .models import (Gabinete, RegletasDeGabinete, Brigada, CausaIncidencia, Centro, Clave, ClaveOrdenServicio, GrupoClave, NormaMantenimiento, NormaTiempo,
                     NormaTipoOrden, NormaTrabajo, OpcionDeTrabajo, Operario,
                     TipoMantenimiento, TipoOrden, TipoTrabajo, Vehiculo)


class NormaInline(admin.TabularInline):
    model = NormaTiempo
    extra = 0


@admin.register(Clave)
class ClaveAdmin(admin.ModelAdmin):
    """El administrador crea, modifica y elimina claves.

    Una clave que ya se usó en alguna acción no se puede eliminar (se perdería el historial y se alterarían las
    estadísticas): se desmarca 'activa' y deja de ofrecerse en los registros nuevos.
    """

    list_display = ("codigo", "grupo", "clasificacion", "ambito", "descripcion", "revisar", "activa")
    list_filter = ("clasificacion", "grupo", "ambito", "revisar", "activa")
    list_editable = ("clasificacion", "revisar", "activa")
    search_fields = ("codigo", "descripcion")
    inlines = [NormaInline]

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.acciones.exists():
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)  # se elimina de una en una, para poder proteger las ya usadas
        return actions

    def get_search_results(self, request, queryset, search_term):
        queryset, distinct = super().get_search_results(request, queryset, search_term)
        if request.path.endswith("/autocomplete/"):  # al registrar acciones solo se ofrecen las claves activas
            queryset = queryset.filter(activa=True)
        return queryset, distinct

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # las claves de orden de servicio tienen su propia sección (salvo en el autocompletado de las acciones)
        return qs if request.path.endswith("/autocomplete/") else qs.exclude(ambito="ORDEN")


@admin.register(ClaveOrdenServicio)
class ClaveOrdenServicioAdmin(admin.ModelAdmin):
    """Claves de cierre de las órdenes de servicio (motivos por los que una orden no se ejecutó). Las usadas no se eliminan: se desmarcan."""

    list_display = ("codigo", "descripcion", "clasificacion", "activa")
    list_editable = ("clasificacion", "activa")
    search_fields = ("codigo", "descripcion")
    fields = ("codigo", "descripcion", "clasificacion", "activa", "notas")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(ambito="ORDEN")

    def save_model(self, request, obj, form, change):
        obj.ambito = "ORDEN"
        if not obj.grupo_id:
            obj.grupo, _ = GrupoClave.objects.get_or_create(nombre="Orden de servicio")
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.acciones.exists():
            return False
        return super().has_delete_permission(request, obj)


@admin.register(NormaTiempo)
class NormaTiempoAdmin(admin.ModelAdmin):
    """Para cambiar una norma sin alterar el pasado: ponga fecha fin a la anterior y cree otra con su fecha de inicio."""

    list_display = ("clave", "tipo_orden", "tiempo", "nota", "vigente_desde", "vigente_hasta")
    list_filter = ("nota", "tipo_orden", "clave__grupo")
    search_fields = ("clave__codigo",)
    autocomplete_fields = ("clave",)

    @admin.display(description="Minutos", ordering="minutos")
    def tiempo(self, norma):
        return texto_norma(norma.minutos)


@admin.register(Operario)
class OperarioAdmin(admin.ModelAdmin):
    list_display = ("clave", "nombre", "brigada", "activo")
    list_filter = ("brigada", "activo")
    search_fields = ("clave", "nombre")


@admin.register(Vehiculo)
class VehiculoAdmin(admin.ModelAdmin):
    list_display = ("chapa", "descripcion", "activo")
    search_fields = ("chapa",)


@admin.register(Centro)
class CentroAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "activo")
    search_fields = ("codigo", "nombre")


@admin.register(CausaIncidencia)
class CausaIncidenciaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "descuenta_tiempo")
    list_editable = ("descuenta_tiempo",)


class NormaTipoOrdenInline(admin.TabularInline):
    model = NormaTipoOrden
    extra = 0


@admin.register(TipoOrden)
class TipoOrdenAdmin(admin.ModelAdmin):
    """Para cambiar una norma sin alterar el pasado, ponga fecha fin a la vigente y cree otra con su fecha de inicio."""

    list_display = ("codigo", "nombre", "fila_parte", "norma_actual")
    list_editable = ("fila_parte",)
    search_fields = ("codigo", "nombre")
    inlines = [NormaTipoOrdenInline]

    @admin.display(description="Norma vigente (min)")
    def norma_actual(self, tipo):
        from django.utils import timezone
        norma = NormaTipoOrden.vigente(tipo, timezone.localdate())
        return f"{texto_norma(norma.minutos)}{f' · {norma.nota}' if norma.nota else ''}" if norma else "— sin norma —"


class NormaTrabajoInline(admin.TabularInline):
    model = NormaTrabajo
    extra = 0


class OpcionDeTrabajoInline(admin.TabularInline):
    model = OpcionDeTrabajo
    extra = 0


@admin.register(TipoTrabajo)
class TipoTrabajoAdmin(admin.ModelAdmin):
    """Trabajos de las órdenes de trabajo. Cada uno lleva su norma de tiempo (para cambiarla sin alterar el pasado,
    ponga fecha fin a la vigente y cree otra con su fecha de inicio)."""

    list_display = ("nombre", "especialidad", "clave", "medida", "norma_actual", "activo")
    list_editable = ("activo",)
    list_filter = ("especialidad", "medida", "activo")
    search_fields = ("nombre", "clave", "descripcion")
    inlines = [OpcionDeTrabajoInline, NormaTrabajoInline]

    @admin.display(description="Norma vigente (min)")
    def norma_actual(self, tipo):
        from django.utils import timezone
        hoy = timezone.localdate()
        if tipo.medida == "TIPO":
            partes = [f"{o.nombre}: {texto_norma(n.minutos) if (n := NormaTrabajo.vigente(tipo, hoy, o.pk)) else 'sin norma'}" for o in tipo.opciones.filter(activa=True)]
            return " · ".join(partes) or "— sin opciones —"
        norma = NormaTrabajo.vigente(tipo, hoy)
        if not norma:
            return "— sin norma —"
        por = {"UNIDADES": f" por {tipo.unidad or 'unidad'}", "METROS": " por metro"}.get(tipo.medida, "")
        return f"{texto_norma(norma.minutos)}{por}{f' · {norma.nota}' if norma.nota else ''}"


class NormaMantenimientoInline(admin.TabularInline):
    model = NormaMantenimiento
    extra = 0


@admin.register(TipoMantenimiento)
class TipoMantenimientoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "fila_parte", "norma_actual", "activo")
    list_editable = ("fila_parte", "activo")
    inlines = [NormaMantenimientoInline]

    @admin.display(description="Norma vigente (min)")
    def norma_actual(self, tipo):
        from django.utils import timezone
        norma = NormaMantenimiento.vigente(tipo, timezone.localdate())
        return f"{texto_norma(norma.minutos)}{f' · {norma.nota}' if norma.nota else ''}" if norma else "— sin norma —"


for modelo in (Brigada, GrupoClave):
    admin.site.register(modelo)


class RegletasInline(admin.TabularInline):
    model = RegletasDeGabinete
    extra = 0


@admin.register(Gabinete)
class GabineteAdmin(admin.ModelAdmin):
    """Gabinetes y sus regletas. Se pueden cargar y actualizar desde Excel con los botones de arriba."""

    list_display = ("nombre", "centro", "total", "activo")
    list_filter = ("centro", "activo")
    search_fields = ("nombre",)
    inlines = [RegletasInline]
    change_list_template = "admin/catalogos/gabinete/change_list.html"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("centro").prefetch_related("regletas")

    @admin.display(description="Regletas")
    def total(self, gabinete):
        return gabinete.total_regletas or "—"

    def get_urls(self):
        propias = [
            path("plantilla/", self.admin_site.admin_view(self.plantilla), name="catalogos_gabinete_plantilla"),
            path("importar/", self.admin_site.admin_view(self.importar_excel), name="catalogos_gabinete_importar"),
        ]
        return propias + super().get_urls()

    def plantilla(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        return HttpResponse(gabinetes_excel.plantilla_xlsx(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": 'attachment; filename="UDAT_plantilla_gabinetes.xlsx"'})

    def importar_excel(self, request):
        if not (self.has_add_permission(request) and self.has_change_permission(request)):
            raise PermissionDenied
        errores = []
        if request.method == "POST":
            archivo = request.FILES.get("archivo")
            try:
                if archivo is None or not archivo.name.lower().endswith(".xlsx") or archivo.size > 5 * 1024 * 1024:
                    raise ValidationError("Seleccione un Excel .xlsx de menos de 5 MB.")
                resultado = gabinetes_excel.importar(archivo.read())
            except ValidationError as error:
                errores = [{"fila": "—", "mensaje": " ".join(error.messages)}]
            else:
                errores = resultado["errores"]
                if not errores:
                    self.message_user(request, f"Gabinetes importados: {resultado['creados']} nuevo(s) y {resultado['actualizados']} actualizado(s).")
                    return redirect("admin:catalogos_gabinete_changelist")
        contexto = {**self.admin_site.each_context(request), "title": "Importar gabinetes desde Excel", "errores": errores, "opts": self.model._meta}
        return render(request, "admin/catalogos/gabinete/importar.html", contexto)
