"""Utilidades para no levantar dos servidores en el mismo puerto.

En Windows dos procesos pueden abrir el MISMO puerto sin error (el sistema lo permite): ambos dicen estar levantados, pero las
peticiones las atiende solo uno, y con varios proyectos Django a la vez se termina viendo el /admin de otro proyecto."""
import socket


def puerto_ocupado(puerto, host="127.0.0.1"):
    """True si ya hay un servidor escuchando en ese puerto."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, int(puerto))) == 0
