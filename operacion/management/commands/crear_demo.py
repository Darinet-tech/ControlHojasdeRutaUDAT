"""Crea una hoja de ruta de ejemplo completa para ver el sistema funcionando.

Escenario (jornada desde las 08:00, 2 operarios):
  09:00  Acción 1  claves 25-R + 07-IC   -> OK con el cliente           (60 min reales)
  09:00-10:00  Incidencia 100 Lluvia      -> el contador corre 60 min
  11:15  Acción 2  clave 23              -> pasa a la brigada de Cable  (135 - 60 de lluvia = 75 min reales)
  12:00  Acción 3  clave 36              -> cerrada sin OK              (45 min reales)
  Al final se cierra la hoja del día.
Se puede repetir: borra la demo anterior y la vuelve a crear.
"""
from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalogos.models import Brigada, CausaIncidencia, Centro, Clave, Operario, Vehiculo
from operacion.models import Accion, HojaDeRuta, OrdenServicio
from operacion.services import (cerrar_hoja, cerrar_sin_ok, certificar_ok, finalizar_incidencia, iniciar_incidencia,
                                pasar_a_brigada, resumen_hoja)

CHAPA_DEMO = "DEMO001"


class Command(BaseCommand):
    help = "Crea una hoja de ruta de ejemplo con OK, pase a otra brigada, incidencia por lluvia y cierre del día."

    def add_arguments(self, parser):
        parser.add_argument("--fecha", help="AAAA-MM-DD (por defecto, hoy)")

    def handle(self, *args, **opts):
        fecha = date.fromisoformat(opts["fecha"]) if opts["fecha"] else timezone.localdate()
        try:
            rep = Brigada.objects.get(nombre="Red de Abonados")
            cable = Brigada.objects.get(nombre="Cable")
            centro = Centro.objects.get(codigo="NG")
            lluvia = CausaIncidencia.objects.get(codigo="100")
            claves = {c.codigo: c for c in Clave.objects.filter(codigo__in=["25-R", "07-IC", "23", "36"])}
        except Exception as error:
            raise CommandError(f"Faltan datos iniciales ({error}). Ejecute primero: python manage.py cargar_inicial")

        User = get_user_model()
        usuario = User.objects.filter(is_superuser=True).first() or User.objects.get_or_create(username="demo_probador")[0]

        HojaDeRuta.objects.filter(vehiculo__chapa=CHAPA_DEMO).delete()  # borra la demo anterior
        OrdenServicio.objects.filter(numero_servicio__startswith="DEMO").delete()

        vehiculo, _ = Vehiculo.objects.get_or_create(chapa=CHAPA_DEMO, defaults={"descripcion": "Vehículo de demostración"})
        ops = [Operario.objects.get_or_create(clave=f"DEMO{i}", defaults={"nombre": f"Operario demo {i}", "brigada": rep})[0]
               for i in (1, 2)]

        hoja = HojaDeRuta.objects.create(fecha=fecha, brigada=rep, vehiculo=vehiculo,
                                         creado_por=usuario, modificado_por=usuario)
        hoja.operarios.set(ops)
        hoja.centros.set([centro])

        def a_las(hh, mm):
            return timezone.make_aware(datetime(fecha.year, fecha.month, fecha.day, hh, mm))

        acciones = []
        for n, (servicio, codigos) in enumerate([("DEMO 46-111111", ["25-R", "07-IC"]), ("DEMO 46-222222", ["23"]),
                                                  ("DEMO 46-333333", ["36"])], start=1):
            orden = OrdenServicio.objects.create(numero_servicio=servicio, creado_por=usuario, modificado_por=usuario)
            accion = Accion.objects.create(hoja=hoja, orden=orden, numero=n, centro=centro, creado_por=usuario, modificado_por=usuario)
            accion.claves.set([claves[c] for c in codigos])
            acciones.append(accion)
        a1, a2, a3 = acciones

        certificar_ok(a1, usuario, "Cliente de ejemplo", ahora=a_las(9, 0))
        iniciar_incidencia(hoja, lluvia, usuario, "Lluvia fuerte", ahora=a_las(9, 0))
        finalizar_incidencia(hoja, usuario, ahora=a_las(10, 0))
        pasar_a_brigada(a2, cable, usuario, ahora=a_las(11, 15))
        cerrar_sin_ok(a3, usuario, ahora=a_las(12, 0))
        cerrar_hoja(hoja, usuario, ahora=a_las(15, 0))

        self.stdout.write(self.style.SUCCESS(f"\nHoja de demostración creada: {hoja}\n"))
        for a in acciones:
            a.refresh_from_db()
            estado = "OK" if a.ok else (f"pasada a {a.pasada_a}" if a.pasada_a else "cerrada sin OK")
            self.stdout.write(f"  {a.orden.numero_servicio:<16} {a.tiempo_real_min:>3} min reales   {estado:<22} orden: {a.orden.get_estado_display()}")
        r = resumen_hoja(hoja, ahora=a_las(15, 0))
        self.stdout.write(
            "\nResumen de la hoja:\n"
            f"  Acciones: {r['acciones']}  Efectivas (con OK): {r['efectivas']}  Efectividad: {r['efectividad_pct']} %\n"
            f"  Tiempo real: {r['tiempo_real_min']} min   Normado efectivo: {r['tiempo_normado_efectivo_min']} min   "
            f"Productividad: {r['productividad_pct']} %\n"
            f"  Incidencias: {r['incidencias_min']} min {r['incidencias_por_causa']}\n"
            f"  Tiempo disponible: {r['tiempo_disponible_min']} min   Ocupación: {r['ocupacion_pct']} %\n"
        )
