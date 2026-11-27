import { useEffect, useState } from 'react';
import { fijarTema, temaActual } from './tema.js';

export function BotonTema({ className = '' }) {
  const [tema, setTema] = useState(temaActual());
  const alternar = () => { const nuevo = tema === 'oscuro' ? 'claro' : 'oscuro'; fijarTema(nuevo); setTema(nuevo); };
  return (
    <button type="button" className={`boton boton-tema ${className}`} onClick={alternar} aria-pressed={tema === 'oscuro'}
      title={tema === 'oscuro' ? 'Cambiar al tema claro' : 'Cambiar al tema oscuro'}>
      {tema === 'oscuro' ? '☀ Claro' : '☾ Oscuro'}
    </button>
  );
}

export function Chip({ tipo = 'neutro', children, titulo }) {
  return (
    <span className={`chip chip-${tipo}`} title={titulo}>
      {children}
    </span>
  );
}

export const tipoDeClasificacion = { EFECTIVA: 'ok', NO_EFECTIVA: 'mal', PENDIENTE: 'aviso' };

export function Aviso({ tipo = 'error', children, alCerrar }) {
  if (!children) return null;
  return (
    <div className={`aviso aviso-${tipo}`} role={tipo === 'error' ? 'alert' : 'status'}>
      <span>{children}</span>
      {alCerrar && (
        <button className="enlace" onClick={alCerrar} aria-label="Cerrar aviso">
          ✕
        </button>
      )}
    </div>
  );
}

export function Estadistica({ etiqueta, valor, ayuda, nivel }) {
  return (
    <div className={`estadistica ${nivel ? `estadistica-${nivel.tipo}` : ''}`} title={ayuda}>
      <div className="estadistica-valor">{valor}</div>
      <div className="estadistica-etiqueta">{etiqueta}</div>
      {nivel && <div className="estadistica-nivel">{nivel.texto}</div>}
    </div>
  );
}

// Punto de evaluación de la productividad: se cumple desde el 90 %.
export const META_PRODUCTIVIDAD = 90;
export const nivelProductividad = (v) => (v === null || v === undefined ? undefined
  : v >= META_PRODUCTIVIDAD ? { tipo: 'cumple', texto: `✔ Cumple el ${META_PRODUCTIVIDAD} %` }
    : { tipo: 'bajo', texto: `▼ Por debajo del ${META_PRODUCTIVIDAD} %` });
export function Productividad({ valor, texto }) {
  const nivel = nivelProductividad(valor);
  if (!nivel) return texto;
  return <span className={`chip ${nivel.tipo === 'cumple' ? 'chip-ok' : 'chip-mal'}`} title={nivel.texto}>{nivel.tipo === 'cumple' ? '✔' : '▼'} {texto}</span>;
}

export function Modal({ titulo, alCerrar, children }) {
  useEffect(() => {
    const tecla = (e) => e.key === 'Escape' && alCerrar();
    window.addEventListener('keydown', tecla);
    return () => window.removeEventListener('keydown', tecla);
  }, [alCerrar]);
  return (
    <div className="modal-fondo" onClick={alCerrar}>
      <div className="modal" role="dialog" aria-label={titulo} onClick={(e) => e.stopPropagation()}>
        <div className="modal-cabecera">
          <h3>{titulo}</h3>
          <button className="enlace" onClick={alCerrar} aria-label="Cerrar">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
