from django.contrib import admin

from .models import (Brigada, CausaIncidencia, Centro, Clave, GrupoClave, NormaTiempo, NormaTrabajo, Operario,
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


@admin.register(NormaTiempo)
class NormaTiempoAdmin(admin.ModelAdmin):
    """Para cambiar una norma sin alterar el pasado: ponga fecha fin a la anterior y cree otra con su fecha de inicio."""

    list_display = ("clave", "tipo_orden", "minutos", "vigente_desde", "vigente_hasta")
    list_filter = ("tipo_orden", "clave__grupo")
    search_fields = ("clave__codigo",)
    autocomplete_fields = ("clave",)


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


@admin.register(TipoOrden)
class TipoOrdenAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "descripcion")
    search_fields = ("codigo", "nombre")


class NormaTrabajoInline(admin.TabularInline):
    model = NormaTrabajo
    extra = 0


@admin.register(TipoTrabajo)
class TipoTrabajoAdmin(admin.ModelAdmin):
    """Trabajos de las órdenes de trabajo. Cada uno lleva su norma de tiempo (para cambiarla sin alterar el pasado,
    ponga fecha fin a la vigente y cree otra con su fecha de inicio)."""

    list_display = ("nombre", "norma_actual", "activo")
    list_editable = ("activo",)
    inlines = [NormaTrabajoInline]

    @admin.display(description="Norma vigente (min)")
    def norma_actual(self, tipo):
        from django.utils import timezone
        norma = NormaTrabajo.vigente(tipo, timezone.localdate())
        return norma.minutos if norma else "— sin norma —"


@admin.register(TipoMantenimiento)
class TipoMantenimientoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "activo")


for modelo in (Brigada, GrupoClave):
    admin.site.register(modelo)
