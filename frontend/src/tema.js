// Tema claro/oscuro según el gusto del usuario: se recuerda en este navegador y, la primera vez, sigue la preferencia del sistema.
const CLAVE = 'udat-tema';

export function temaGuardado() {
  try { const t = localStorage.getItem(CLAVE); return t === 'claro' || t === 'oscuro' ? t : null; } catch { return null; }
}

export function temaInicial() {
  return temaGuardado() ?? (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'oscuro' : 'claro');
}

export function temaActual() {
  return document.documentElement.dataset.tema === 'oscuro' ? 'oscuro' : 'claro';
}

export function fijarTema(tema, recordar = true) {
  document.documentElement.dataset.tema = tema;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', tema === 'oscuro' ? '#12151c' : '#050752');
  if (recordar) { try { localStorage.setItem(CLAVE, tema); } catch { /* sin almacenamiento: vale solo para esta sesión */ } }
}
