from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import HojaDeRuta


@receiver(m2m_changed, sender=HojaDeRuta.operarios.through)
def un_operario_una_hoja_por_dia(sender, instance, action, reverse, pk_set, **kwargs):
    """Red de seguridad: aunque se agregue un operario por otro camino, no puede quedar en dos hojas el mismo día."""
    if action != "pre_add" or not pk_set:
        return
    from .services import validar_operarios_libres

    if not reverse:  # hoja.operarios.add(...)
        validar_operarios_libres(instance.fecha, list(pk_set), excluir_hoja=instance)
    else:  # operario.hojas.add(...)
        for hoja in HojaDeRuta.objects.filter(pk__in=pk_set):
            validar_operarios_libres(hoja.fecha, [instance.pk], excluir_hoja=hoja)
