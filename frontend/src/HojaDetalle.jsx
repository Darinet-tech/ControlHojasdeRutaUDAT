import { useCallback, useEffect, useState } from 'react';
import { api, fechaLarga, formatearHora, minutosATexto, porcentaje, puede } from './api.js';
import { Aviso, Chip, Estadistica, Modal, tipoDeClasificacion } from './componentes.jsx';

// ---------------------------------------------------------------- selector de claves

function SelectorDeClaves({ catalogo, seleccionadas, alCambiar, deshabilitado }) {
  const [texto, setTexto] = useState('');
  const ids = seleccionadas.map((c) => c.id);
  const q = texto.trim().toLowerCase();
  const coincidencias = q
    ? catalogo.filter((c) => !ids.includes(c.id) && `${c.codigo} ${c.descripcion} ${c.grupo}`.toLowerCase().includes(q))
        .sort((a, b) => (b.codigo.toLowerCase() === q) - (a.codigo.toLowerCase() === q) ||
          (b.codigo.toLowerCase().startsWith(q)) - (a.codigo.toLowerCase().startsWith(q)))
        .slice(0, 8)
    : [];

  return (
    <div className="claves">
      <div className="fila fila-chips">
        {seleccionadas.length === 0 && <span className="suave">Sin claves registradas</span>}
        {seleccionadas.map((c) => (
          <Chip key={c.id} tipo={tipoDeClasificacion[c.clasificacion]} titulo={c.descripcion}>
            {c.codigo} · {c.norma_min ?? '?'} min
            {!deshabilitado && (
              <button className="chip-quitar" aria-label={`Quitar clave ${c.codigo}`} onClick={() => alCambiar(ids.filter((i) => i !== c.id))}>×</button>
            )}
          </Chip>
        ))}
      </div>
      {!deshabilitado && (
        <>
          <input placeholder="Agregar clave: escriba el código o parte de la descripción…" value={texto}
            onChange={(e) => setTexto(e.target.value)} aria-label="Buscar clave" />
          {coincidencias.length > 0 && (
            <ul className="sugerencias">
              {coincidencias.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => { alCambiar([...ids, c.id]); setTexto(''); }}>
                    <Chip tipo={tipoDeClasificacion[c.clasificacion]}>{c.codigo}</Chip>
                    <span>{c.descripcion || <em>(sin descripción)</em>}</span>
                    <small className="suave">{c.grupo} · {c.norma_min ?? '?'} min</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {q && coincidencias.length === 0 && <p className="suave">Ninguna clave coincide.</p>}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- trabajos de una orden de trabajo

function SelectorDeTrabajos({ catalogo, seleccionados, alCambiar, deshabilitado }) {
  const ids = seleccionados.map((t) => t.id);
  const faltan = catalogo.filter((t) => !ids.includes(t.id));
  return (
    <div className="claves">
      <div className="fila fila-chips">
        {seleccionados.length === 0 && <span className="suave">Sin trabajos seleccionados</span>}
        {seleccionados.map((t) => (
          <Chip key={t.id} tipo="info">
            {t.nombre}{t.norma_min ? ` · ${t.norma_min} min` : ' · sin norma'}
            {!deshabilitado && <button className="chip-quitar" aria-label={`Quitar trabajo ${t.nombre}`} onClick={() => alCambiar(ids.filter((i) => i !== t.id))}>×</button>}
          </Chip>
        ))}
      </div>
      {!deshabilitado && faltan.length > 0 && (
        <select aria-label="Agregar trabajo" value="" onChange={(e) => e.target.value && alCambiar([...ids, Number(e.target.value)])}>
          <option value="">Agregar trabajo de la orden…</option>
          {faltan.map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}
        </select>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- formulario para asignar un trabajo a la hoja

const CATEGORIAS = [['CORRECTIVO', 'Correctivo'], ['PREVENTIVO', 'Preventivo'], ['ORDEN_SERVICIO', 'Orden de servicio'], ['ORDEN_TRABAJO', 'Orden de trabajo']];

// Solo se muestran (y se envían) los campos que corresponden a cada tipo de acción, para evitar errores de captura.
function FormularioAsignar({ catalogos, hoja, centrosDeLaHoja, ejecutar, verHistorial }) {
  const [categoria, setCategoria] = useState('CORRECTIVO');
  const [servicio, setServicio] = useState('');
  const [mantenimiento, setMantenimiento] = useState('');
  const [tipoOrden, setTipoOrden] = useState('');
  const [numeroOrden, setNumeroOrden] = useState('');
  const [trabajos, setTrabajos] = useState(new Set());
  const [centro, setCentro] = useState('');
  const variosCentros = hoja.centros.length > 1;
  const centroElegido = centro || String(hoja.centros[0]);

  const cambiarCategoria = (nueva) => {
    setCategoria(nueva); setServicio(''); setMantenimiento(''); setTipoOrden(''); setNumeroOrden(''); setTrabajos(new Set());
  };
  const alternarTrabajo = (id) => setTrabajos((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const completo = {
    CORRECTIVO: servicio.trim(),
    PREVENTIVO: mantenimiento && servicio.trim(),
    ORDEN_SERVICIO: tipoOrden && numeroOrden.trim() && servicio.trim(),
    ORDEN_TRABAJO: numeroOrden.trim() && trabajos.size > 0,
  }[categoria];

  async function enviar(e) {
    e.preventDefault();
    const cuerpo = { categoria, ...(variosCentros && { centro: Number(centroElegido) }) };
    if (categoria !== 'ORDEN_TRABAJO') cuerpo.numero_servicio = servicio.trim();
    if (categoria === 'PREVENTIVO') cuerpo.tipo_mantenimiento = Number(mantenimiento);
    if (categoria === 'ORDEN_SERVICIO') { cuerpo.tipo_orden = Number(tipoOrden); cuerpo.numero_orden = numeroOrden.trim(); }
    if (categoria === 'ORDEN_TRABAJO') { cuerpo.numero_orden = numeroOrden.trim(); cuerpo.trabajos = [...trabajos]; }
    const ok = await ejecutar(() => api.post(`/hojas/${hoja.id}/acciones/`, cuerpo));
    if (ok) { setServicio(''); setNumeroOrden(''); setTrabajos(new Set()); }
  }

  return (
    <form className="tarjeta formulario-asignar" onSubmit={enviar} aria-label="Asignar servicio">
      <div className="fila fila-formulario">
        <label>Tipo de acción
          <select value={categoria} onChange={(e) => cambiarCategoria(e.target.value)}>
            {CATEGORIAS.map(([valor, texto]) => <option key={valor} value={valor}>{texto}</option>)}
          </select>
        </label>
        {categoria === 'PREVENTIVO' && (
          <label>Tipo de mantenimiento
            <select value={mantenimiento} onChange={(e) => setMantenimiento(e.target.value)} required>
              <option value="">Seleccione…</option>
              {catalogos.tiposMantenimiento.map((t) => <option key={t.id} value={t.id}>{t.codigo} · {t.nombre}</option>)}
            </select>
          </label>
        )}
        {categoria === 'ORDEN_SERVICIO' && (
          <>
            <label>Tipo de orden
              <select value={tipoOrden} onChange={(e) => setTipoOrden(e.target.value)} required>
                <option value="">Seleccione…</option>
                {catalogos.tiposOrden.map((t) => <option key={t.id} value={t.id}>{t.codigo} · {t.nombre}</option>)}
              </select>
            </label>
            <label>Número de orden
              <input value={numeroOrden} onChange={(e) => setNumeroOrden(e.target.value)} required />
            </label>
          </>
        )}
        {categoria === 'ORDEN_TRABAJO' && (
          <label>Número de la orden de trabajo
            <input value={numeroOrden} onChange={(e) => setNumeroOrden(e.target.value)} required />
          </label>
        )}
        {categoria !== 'ORDEN_TRABAJO' && (
          <label>Número de servicio
            <input value={servicio} onChange={(e) => setServicio(e.target.value)} placeholder="Ej.: 46-326407" required />
          </label>
        )}
        {variosCentros && (
          <label>Centro del servicio
            <select value={centroElegido} onChange={(e) => setCentro(e.target.value)}>
              {centrosDeLaHoja.map((c) => <option key={c.id} value={c.id}>{c.codigo} · {c.nombre}</option>)}
            </select>
          </label>
        )}
      </div>
      {categoria === 'ORDEN_TRABAJO' && (
        <fieldset>
          <legend>Trabajos de la orden ({trabajos.size} seleccionado{trabajos.size === 1 ? '' : 's'})</legend>
          <div className="rejilla-centros">
            {catalogos.tiposTrabajo.length === 0 && <span className="suave">No hay trabajos definidos: el administrador debe crearlos en el catálogo.</span>}
            {catalogos.tiposTrabajo.map((t) => (
              <label key={t.id} className="casilla">
                <input type="checkbox" checked={trabajos.has(t.id)} onChange={() => alternarTrabajo(t.id)} />
                <span>{t.nombre}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <div className="fila">
        <button className="boton boton-principal" disabled={!completo}>Asignar a la hoja</button>
        {categoria !== 'ORDEN_TRABAJO' && (
          <button type="button" className="boton" disabled={!servicio.trim()} onClick={() => verHistorial(servicio.trim())}>Ver historial</button>
        )}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- una acción (un servicio de la hoja)

const ETIQUETA_ESTADO = { EN_CURSO: ['info', 'En curso'], OK: ['ok', 'OK'], SIN_OK: ['mal', 'Cerrada sin OK'], NO_VISITADA: ['aviso', 'No visitada'] };

function TarjetaAccion({ accion, hoja, editable, catalogos, ejecutar, verHistorial }) {
  const [modo, setModo] = useState(null); // 'ok' | 'pasar' | 'sinok'
  const [cliente, setCliente] = useState('');
  const [brigada, setBrigada] = useState('');
  const abierta = accion.estado === 'EN_CURSO';
  const esOT = accion.categoria === 'ORDEN_TRABAJO';
  const sinClaves = esOT ? accion.trabajos.length === 0 : accion.claves.length === 0; // nada registrado todavía
  const otrasBrigadas = catalogos.brigadas.filter((b) => b.id !== hoja.brigada);
  const [tipo, texto] = accion.estado === 'PASADA_A_BRIGADA'
    ? ['aviso', `Pasada a ${accion.pasada_a_nombre}`]
    : ETIQUETA_ESTADO[accion.estado];

  const confirmar = async (fn) => {
    const r = await ejecutar(fn);
    if (r !== null) setModo(null);
  };

  return (
    <article className={`tarjeta accion accion-${accion.estado.toLowerCase()}`} aria-label={`Servicio ${accion.etiqueta}`}>
      <div className="fila">
        <strong>#{accion.numero} · {accion.etiqueta}</strong>
        {accion.categoria !== 'CORRECTIVO' && <Chip tipo="info" titulo="Tipo de acción">{accion.categoria_texto}</Chip>}
        {hoja.centros.length > 1 && accion.centro_codigo && <Chip tipo="info" titulo="Centro del servicio">📍 {accion.centro_codigo}</Chip>}
        <Chip tipo={tipo}>{texto}</Chip>
        {accion.estado_orden === 'PENDIENTE' && abierta && <Chip tipo="aviso">Orden pendiente</Chip>}
        {accion.numero_servicio && <button className="enlace empujar" onClick={() => verHistorial(accion.numero_servicio)}>Ver historial</button>}
      </div>

      {esOT ? (
        <SelectorDeTrabajos catalogo={catalogos.tiposTrabajo} seleccionados={accion.trabajos} deshabilitado={!editable || !abierta}
          alCambiar={(ids) => ejecutar(() => api.patch(`/acciones/${accion.id}/`, { trabajos: ids }))} />
      ) : (
        <SelectorDeClaves catalogo={catalogos.claves} seleccionadas={accion.claves}
          deshabilitado={!editable || !abierta}
          alCambiar={(ids) => ejecutar(() => api.patch(`/acciones/${accion.id}/`, { claves: ids }))} />
      )}

      {abierta && accion.norma_min !== null && (
        <p className="suave">
          Norma de tiempo: <strong>{accion.norma_min} min</strong> ({esOT ? 'trabajo de mayor norma' : 'clave mayor'})
          {accion.sugerencia_ok && !esOT && ' · Sugerencia: las claves son compatibles con OK'}
        </p>
      )}

      {accion.estado === 'NO_VISITADA' && (
        <p className="suave">No se visitó en esta hoja: pasa al siguiente día y se puede traer a una hoja nueva.</p>
      )}

      {!abierta && accion.estado !== 'NO_VISITADA' && (
        <p className="suave">
          Cerrada a las {formatearHora(accion.hora_fin)} · tiempo real {minutosATexto(accion.tiempo_real_min)}
          {accion.norma_min !== null && ` · norma ${accion.norma_min} min`}
          {accion.ok && accion.cliente_contactado && ` · certificada con: ${accion.cliente_contactado}`}
        </p>
      )}

      {editable && abierta && modo === null && (
        <div className="fila botones-accion">
          <button className="boton boton-ok" disabled={sinClaves} onClick={() => setModo('ok')}>✔ Dar OK</button>
          <button className="boton" disabled={sinClaves || otrasBrigadas.length === 0} onClick={() => { setBrigada(otrasBrigadas[0]?.id ?? ''); setModo('pasar'); }}>
            ➜ Pasar a otra brigada
          </button>
          <button className="boton" disabled={sinClaves} onClick={() => setModo('sinok')}>Cerrar sin OK</button>
          {sinClaves && <span className="suave">{esOT ? 'Seleccione al menos un trabajo para cerrar la acción.' : 'Registre al menos una clave para cerrar la acción.'}</span>}
        </div>
      )}

      {modo === 'ok' && (
        <form className="confirmacion" onSubmit={(e) => { e.preventDefault(); confirmar(() => api.post(`/acciones/${accion.id}/ok/`, { cliente_contactado: cliente })); }}>
          <label>{accion.categoria === 'CORRECTIVO' ? 'Cliente con quien se certificó el servicio' : 'Quién certificó (opcional)'}
            <input value={cliente} onChange={(e) => setCliente(e.target.value)} autoFocus required={accion.categoria === 'CORRECTIVO'}
              placeholder={accion.categoria === 'CORRECTIVO' ? 'Nombre del cliente' : 'Nombre (si corresponde)'} />
          </label>
          <button className="boton boton-ok">Confirmar OK</button>
          <button type="button" className="boton" onClick={() => setModo(null)}>Cancelar</button>
        </form>
      )}
      {modo === 'pasar' && (
        <form className="confirmacion" onSubmit={(e) => { e.preventDefault(); confirmar(() => api.post(`/acciones/${accion.id}/pasar-a-brigada/`, { brigada: Number(brigada) })); }}>
          <label>Brigada a la que pasa la afectación
            <select value={brigada} onChange={(e) => setBrigada(e.target.value)}>
              {otrasBrigadas.map((b) => <option key={b.id} value={b.id}>{b.nombre}</option>)}
            </select>
          </label>
          <button className="boton boton-principal">Confirmar pase</button>
          <button type="button" className="boton" onClick={() => setModo(null)}>Cancelar</button>
        </form>
      )}
      {modo === 'sinok' && (
        <div className="confirmacion">
          <span>¿Cerrar sin OK? No contará como acción efectiva.</span>
          <button className="boton boton-peligro" onClick={() => confirmar(() => api.post(`/acciones/${accion.id}/cerrar-sin-ok/`))}>Sí, cerrar sin OK</button>
          <button className="boton" onClick={() => setModo(null)}>Cancelar</button>
        </div>
      )}
    </article>
  );
}

// ---------------------------------------------------------------- incidencias con contador

function PanelIncidencias({ hoja, causas, editable, ejecutar }) {
  const activa = hoja.incidencias.find((i) => i.activa);
  const [causa, setCausa] = useState('');
  const [, refrescar] = useState(0);

  useEffect(() => { // el contador de la incidencia activa se actualiza solo
    if (!activa) return undefined;
    const t = setInterval(() => refrescar((n) => n + 1), 15000);
    return () => clearInterval(t);
  }, [activa]);

  const transcurridos = activa ? Math.max(0, Math.floor((Date.now() - new Date(activa.inicio)) / 60000)) : 0;

  return (
    <section className="tarjeta" aria-label="Incidencias">
      <h2>Incidencias</h2>
      {activa ? (
        <div className="incidencia-activa">
          <div>
            <strong>{activa.causa_codigo} · {activa.causa_nombre}</strong>
            <div className="suave">Contador activo desde las {formatearHora(activa.inicio)} · <strong>{minutosATexto(transcurridos)}</strong></div>
          </div>
          {editable && (
            <button className="boton boton-principal" onClick={() => ejecutar(() => api.post(`/hojas/${hoja.id}/incidencias/finalizar/`))}>
              Finalizar incidencia
            </button>
          )}
        </div>
      ) : (
        editable && (
          <form className="fila" onSubmit={(e) => { e.preventDefault(); ejecutar(() => api.post(`/hojas/${hoja.id}/incidencias/iniciar/`, { causa: Number(causa) })).then(() => setCausa('')); }}>
            <select value={causa} onChange={(e) => setCausa(e.target.value)} aria-label="Causa de la incidencia" required>
              <option value="">Seleccione la causa…</option>
              {causas.map((c) => <option key={c.id} value={c.id}>{c.codigo} · {c.nombre}</option>)}
            </select>
            <button className="boton" disabled={!causa}>Iniciar contador</button>
          </form>
        )
      )}
      {editable && activa && <p className="suave">Para cambiar de causa, inicie otra: la anterior se detiene sola.</p>}
      {hoja.incidencias.filter((i) => !i.activa).length > 0 && (
        <ul className="lista-simple">
          {hoja.incidencias.filter((i) => !i.activa).map((i) => (
            <li key={i.id}>{i.causa_codigo} · {i.causa_nombre} — {formatearHora(i.inicio)} a {formatearHora(i.fin)} ({minutosATexto(i.minutos)})</li>
          ))}
        </ul>
      )}
      {hoja.incidencias.length === 0 && !editable && <p className="suave">Sin incidencias.</p>}
    </section>
  );
}

// ---------------------------------------------------------------- historial de un servicio

function Historial({ numero, alCerrar }) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api.get(`/ordenes/historial/?numero=${encodeURIComponent(numero)}`).then(setDatos).catch((e) => setError(e.message));
  }, [numero]);
  const etiqueta = { OK: 'OK', SIN_OK: 'Sin OK', PASADA_A_BRIGADA: 'Pasada a brigada', EN_CURSO: 'En curso', NO_VISITADA: 'No visitada' };
  return (
    <Modal titulo={`Historial del servicio ${numero}`} alCerrar={alCerrar}>
      <Aviso>{error}</Aviso>
      {!datos && !error && <p className="cargando">Cargando…</p>}
      {datos && (
        <>
          {datos.reincidencia && <Aviso tipo="aviso">Reincidencia: este servicio tiene {datos.ordenes} órdenes registradas.</Aviso>}
          {datos.acciones === 0 && <p className="suave">Este servicio no tiene acciones anteriores.</p>}
          {datos.acciones > 0 && (
            <div className="tabla-envoltura">
              <table>
                <thead><tr><th>Fecha</th><th>Brigada</th><th>Operarios</th><th>Claves</th><th>Resultado</th></tr></thead>
                <tbody>
                  {datos.historial.map((h) => (
                    <tr key={h.id}>
                      <td>{h.fecha}</td><td>{h.brigada}</td><td>{h.operarios.join(', ')}</td>
                      <td>{h.claves.join(', ') || '—'}</td><td>{etiqueta[h.estado]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------- pantalla de la hoja

export default function HojaDetalle({ id, usuario, catalogos, volver }) {
  const [hoja, setHoja] = useState(null);
  const [pendientes, setPendientes] = useState([]);
  const [noVisitadas, setNoVisitadas] = useState([]);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [centroServicio, setCentroServicio] = useState('');
  const [historial, setHistorial] = useState(null);
  const [confirmandoCierre, setConfirmandoCierre] = useState(false);

  const cargar = useCallback(async () => {
    const h = await api.get(`/hojas/${id}/`);
    setHoja(h);
    const centrosUrl = h.centros.map((c) => `centro=${c}`).join('&');
    setPendientes(h.cerrada ? [] : await api.get(`/ordenes/pendientes/?brigada=${h.brigada}&${centrosUrl}`));
    setNoVisitadas(h.cerrada ? [] : await api.get(`/ordenes/no-visitadas/?brigada=${h.brigada}&${centrosUrl}`));
  }, [id]);
  useEffect(() => { cargar().catch((e) => setError(e.message)); }, [cargar]);

  // Ejecuta una operación, vuelve a leer la hoja y muestra el error de negocio si lo hay.
  const ejecutar = useCallback(async (fn) => {
    setError(''); setAviso('');
    try {
      const resultado = await fn();
      await cargar();
      return resultado ?? true;
    } catch (e) {
      setError(e.message);
      return null;
    }
  }, [cargar]);

  if (!hoja) return <><Aviso>{error}</Aviso>{!error && <p className="cargando">Cargando hoja…</p>}<button className="boton" onClick={volver}>← Volver</button></>;

  const editable = !hoja.cerrada && puede(usuario, 'operacion.add_accion');
  const variosCentros = hoja.centros.length > 1;
  const centrosDeLaHoja = catalogos.centros.filter((c) => hoja.centros.includes(c.id));
  const centroElegido = centroServicio || String(hoja.centros[0]);
  // Una orden que ya estuvo en uno de los centros de la hoja vuelve a él; si no, se usa el centro elegido en el formulario.
  const centroPara = (orden) => (!variosCentros || hoja.centros_codigos.includes(orden.ultimo_centro) ? {} : { centro: Number(centroElegido) });
  const r = hoja.resumen;
  const sinNorma = hoja.acciones.filter((a) => a.hora_fin && a.norma_min === null).length;

  async function cerrarHoja() {
    setConfirmandoCierre(false);
    const res = await ejecutar(() => api.post(`/hojas/${id}/cerrar/`));
    if (res && res.no_visitadas.length > 0) setAviso(`Hoja cerrada. ${res.no_visitadas.length} servicio(s) quedaron como no visitados y pasan al siguiente día: ${res.no_visitadas.join(', ')}.`);
  }

  return (
    <section>
      <div className="barra">
        <button className="boton" onClick={volver}>← Hojas del día</button>
        <h1>{hoja.centros_etiqueta} · {hoja.brigada_nombre}</h1>
        {hoja.cerrada ? <Chip>Cerrada</Chip> : <Chip tipo="info">Abierta</Chip>}
        <span className="fila descargas" aria-label="Descargar la hoja">
          <a className="boton" href={`/api/hojas/${id}/informe/?formato=pdf`} target="_blank" rel="noreferrer" title="Hoja de ruta con el formato original, para imprimir o auditar">PDF</a>
          <a className="boton" href={`/api/hojas/${id}/informe/?formato=xlsx`} title="Hoja de ruta con el formato original, en Excel">Excel</a>
        </span>
        {editable && <button className="boton boton-peligro empujar" onClick={() => setConfirmandoCierre(true)}>Cerrar hoja del día</button>}
      </div>
      <p className="suave capitalizar">
        {fechaLarga(hoja.fecha)} · {hoja.operarios_nombres.join(', ')}{hoja.vehiculo_chapa && ` · vehículo ${hoja.vehiculo_chapa}`} · jornada desde las {hoja.hora_inicio?.slice(0, 5)}
      </p>

      <Aviso alCerrar={() => setError('')}>{error}</Aviso>
      <Aviso tipo="aviso" alCerrar={() => setAviso('')}>{aviso}</Aviso>
      {hoja.cerrada && <Aviso tipo="info">Esta hoja está cerrada: solo consulta.</Aviso>}
      {confirmandoCierre && (
        <div className="aviso aviso-aviso">
          <span>¿Cerrar la hoja del día? Se detienen los contadores y los servicios sin cerrar pasan a <strong>no visitados</strong> para el siguiente día. Ya no se podrá modificar.</span>
          <span>
            <button className="boton boton-peligro" onClick={cerrarHoja}>Sí, cerrar hoja</button>{' '}
            <button className="boton" onClick={() => setConfirmandoCierre(false)}>Cancelar</button>
          </span>
        </div>
      )}

      <section className="rejilla-estadisticas" aria-label="Indicadores de la hoja">
        <Estadistica etiqueta="Acciones" valor={r.acciones} />
        <Estadistica etiqueta="Efectivas (con OK)" valor={r.efectivas} />
        <Estadistica etiqueta="Efectividad" valor={porcentaje(r.efectividad_pct)} ayuda="Acciones con OK entre el total de acciones" />
        <Estadistica etiqueta="Productividad" valor={porcentaje(r.productividad_pct)} ayuda="Tiempo normado de las acciones efectivas entre el tiempo real" />
        <Estadistica etiqueta="Tiempo real" valor={minutosATexto(r.tiempo_real_min)} />
        <Estadistica etiqueta="Incidencias" valor={minutosATexto(r.incidencias_min)} ayuda="Se descuentan del tiempo disponible" />
        <Estadistica etiqueta="Tiempo disponible" valor={minutosATexto(r.tiempo_disponible_min)} ayuda="(420 min − incidencias) × operarios" />
        <Estadistica etiqueta="Ocupación" valor={porcentaje(r.ocupacion_pct)} ayuda="Tiempo real entre tiempo disponible" />
      </section>
      {sinNorma > 0 && <Aviso tipo="aviso">{sinNorma} acción(es) cerrada(s) sin norma de tiempo: el administrador debe revisar las normas de sus claves.</Aviso>}

      {hoja.acciones.length > 0 && (
        <section className="tarjeta" aria-label="Resultado de los servicios">
          <h2>Resultado de los servicios</h2>
          <div className="fila fila-chips">
            <Chip tipo="ok">{r.resultados.ok} con OK</Chip>
            <Chip tipo="mal">{r.resultados.sin_ok} sin OK</Chip>
            <Chip tipo="aviso">{r.resultados.pasadas} pasada(s) a otra brigada</Chip>
            <Chip>{r.resultados.no_visitadas} no visitada(s)</Chip>
            {r.resultados.en_curso > 0 && <Chip tipo="info">{r.resultados.en_curso} en curso</Chip>}
          </div>
          {(r.pasadas_a_brigada.length > 0 || r.no_visitadas.length > 0) && (
            <div className="resultados">
              {r.pasadas_a_brigada.length > 0 && (
                <div>
                  <h3>Pasaron a otra brigada</h3>
                  <ul className="lista-simple">{r.pasadas_a_brigada.map((p) => <li key={p.servicio}>{p.servicio} → <strong>{p.brigada}</strong></li>)}</ul>
                </div>
              )}
              {r.no_visitadas.length > 0 && (
                <div>
                  <h3>No visitadas (pasan al siguiente día)</h3>
                  <ul className="lista-simple">{r.no_visitadas.map((n) => <li key={n}>{n}</li>)}</ul>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      <PanelIncidencias hoja={hoja} causas={catalogos.causas} editable={editable} ejecutar={ejecutar} />

      <h2>Servicios de la hoja</h2>
      {editable && <FormularioAsignar catalogos={catalogos} hoja={hoja} centrosDeLaHoja={centrosDeLaHoja} ejecutar={ejecutar} verHistorial={setHistorial} />}

      {editable && noVisitadas.length > 0 && (
        <div className="tarjeta no-visitadas">
          <div className="fila">
            <strong>No visitadas de días anteriores ({hoja.brigada_nombre} · {hoja.centros_etiqueta})</strong>
            <button className="boton boton-principal empujar" onClick={() => ejecutar(() => api.post(`/hojas/${id}/asignar-no-visitadas/`))}>
              Asignar las {noVisitadas.length} a esta hoja
            </button>
          </div>
          <ul className="lista-simple">
            {noVisitadas.map((o) => (
              <li key={o.id} className="fila">
                <span>{o.etiqueta} <small className="suave">no visitada el {o.ultima_fecha?.slice(8, 10)}/{o.ultima_fecha?.slice(5, 7)}</small></span>
                <button className="boton empujar" onClick={() => ejecutar(() => api.post(`/hojas/${id}/asignar-no-visitadas/`, { ordenes: [o.id] }))}>Asignar solo esta</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {editable && pendientes.length > 0 && (
        <div className="tarjeta pendientes">
          <div className="fila">
            <strong>Pendientes para {hoja.brigada_nombre} ({hoja.centros_etiqueta})</strong>
            <button className="boton boton-principal empujar" onClick={() => ejecutar(() => api.post(`/hojas/${id}/asignar-pendientes/`))}>
              Asignar los {pendientes.length} a esta hoja
            </button>
          </div>
          <ul className="lista-simple">
            {pendientes.map((o) => (
              <li key={o.id} className="fila">
                <span>{o.etiqueta} <small className="suave">{o.categoria_texto}</small></span>
                <button className="boton empujar" onClick={() => ejecutar(() => api.post(`/hojas/${id}/acciones/`, { orden: o.id, ...centroPara(o) }))}>Asignar a esta hoja</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {hoja.acciones.length === 0 && <div className="tarjeta vacio"><p>Esta hoja todavía no tiene servicios asignados.</p></div>}
      {hoja.acciones.map((a) => (
        <TarjetaAccion key={a.id} accion={a} hoja={hoja} editable={editable} catalogos={catalogos} ejecutar={ejecutar} verHistorial={setHistorial} />
      ))}

      {historial && <Historial numero={historial} alCerrar={() => setHistorial(null)} />}
    </section>
  );
}
