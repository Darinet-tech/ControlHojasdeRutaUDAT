// Comunicación con la API de Django. Usa la sesión (cookie) y el token CSRF para escribir.

const ETIQUETAS = {
  username: 'Usuario', password: 'Contraseña', fecha: 'Fecha', brigada: 'Brigada', centro: 'Centro',
  operarios: 'Operarios', claves: 'Claves', numero_servicio: 'Número de servicio', causa: 'Causa',
  cliente_contactado: 'Cliente',
};

export class ErrorApi extends Error {
  constructor(mensaje, estado) {
    super(mensaje);
    this.estado = estado;
  }
}

function leerCookie(nombre) {
  const par = document.cookie.split('; ').find((c) => c.startsWith(nombre + '='));
  return par ? decodeURIComponent(par.split('=')[1]) : '';
}

function textoDeError(datos, estado) {
  if (estado === 403) return 'No tiene permiso para esta operación, o su sesión expiró. Vuelva a iniciar sesión.';
  if (!datos) return `Error del servidor (${estado}).`;
  if (typeof datos === 'string') return datos;
  if (datos.detail) return [].concat(datos.detail).join(' ');
  return Object.entries(datos)
    .map(([campo, msgs]) => `${ETIQUETAS[campo] || campo}: ${[].concat(msgs).join(' ')}`)
    .join(' · ');
}

async function pedir(metodo, ruta, cuerpo) {
  const cabeceras = { Accept: 'application/json' };
  if (cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json';
  if (metodo !== 'GET') cabeceras['X-CSRFToken'] = leerCookie('csrftoken');
  const r = await fetch('/api' + ruta, {
    method: metodo,
    headers: cabeceras,
    credentials: 'same-origin',
    body: cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined,
  });
  if (r.status === 204) return null;
  const datos = await r.json().catch(() => null);
  if (!r.ok) throw new ErrorApi(textoDeError(datos, r.status), r.status);
  return datos;
}

export const api = {
  get: (ruta) => pedir('GET', ruta),
  post: (ruta, cuerpo = {}) => pedir('POST', ruta, cuerpo),
  patch: (ruta, cuerpo) => pedir('PATCH', ruta, cuerpo),
};

export const puede = (usuario, permiso) => !!usuario && (usuario.es_superusuario || usuario.permisos.includes(permiso));

// ---------------------------------------------------------------- utilidades de formato

// El día de hoy lo da el servidor (hora de Cuba) al iniciar sesión; solo si aún no se conoce se usa el reloj del equipo.
let hoyDelServidor = null;
export const fijarHoy = (fecha) => { hoyDelServidor = fecha; };

export function hoy() {
  if (hoyDelServidor) return hoyDelServidor;
  const d = new Date();
  const dos = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
}

export const formatearHora = (iso) =>
  iso ? new Date(iso).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', hour12: false }) : '—';

export function minutosATexto(min) {
  if (min === null || min === undefined) return '—';
  const m = Math.round(min);
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min` : `${m} min`;
}

export const porcentaje = (v) => (v === null || v === undefined ? '—' : `${v} %`);

export const fechaLarga = (aaaammdd) =>
  new Date(aaaammdd + 'T12:00:00').toLocaleDateString('es', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
