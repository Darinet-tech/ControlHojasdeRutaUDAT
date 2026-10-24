import { useCallback, useEffect, useState } from 'react';
import { api, fechaLarga, puede } from './api.js';
import { Aviso, Chip } from './componentes.jsx';

function NuevaHoja({ catalogos, fecha, hojasDelDia, alCrear, alCancelar }) {
  const { brigadas, centros, vehiculos, operarios } = catalogos;
  const [brigada, setBrigada] = useState(brigadas[0]?.id ?? '');
  const [centrosElegidos, setCentrosElegidos] = useState(new Set());
  const [vehiculo, setVehiculo] = useState('');
  const [horaInicio, setHoraInicio] = useState('08:00');
  const [elegidos, setElegidos] = useState(new Set());
  const [filtro, setFiltro] = useState('');
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [noVisitadas, setNoVisitadas] = useState([]);
  const [traer, setTraer] = useState(true);
  const [pendientes, setPendientes] = useState([]);
  const [traerPendientes, setTraerPendientes] = useState(true);

  // Un operario no puede estar en más de una hoja el mismo día: los que ya están en otra hoja se bloquean.
  const ocupados = new Map();
  hojasDelDia.forEach((h) => h.operarios.forEach((id) => ocupados.set(id, `${h.centros_etiqueta} · ${h.brigada_nombre}`)));

  // Servicios que esta brigada no visitó en días anteriores (en cualquiera de los centros elegidos): se pueden traer solos.
  const idsCentros = [...centrosElegidos].sort().join(',');
  useEffect(() => {
    if (!brigada || !idsCentros) { setNoVisitadas([]); setPendientes([]); return undefined; }
    let vigente = true;
    const centrosUrl = idsCentros.split(',').map((c) => `centro=${c}`).join('&');
    api.get(`/ordenes/no-visitadas/?brigada=${brigada}&${centrosUrl}`).then((r) => vigente && setNoVisitadas(r)).catch(() => vigente && setNoVisitadas([]));
    api.get(`/ordenes/pendientes/?brigada=${brigada}&${centrosUrl}`).then((r) => vigente && setPendientes(r)).catch(() => vigente && setPendientes([]));
    return () => { vigente = false; };
  }, [brigada, idsCentros]);

  const alternarCentro = (id) =>
    setCentrosElegidos((prev) => {
      const nuevo = new Set(prev);
      nuevo.has(id) ? nuevo.delete(id) : nuevo.add(id);
      return nuevo;
    });

  // Los operarios de la brigada elegida aparecen primero (una hoja puede mezclar operarios de varias brigadas).
  const lista = operarios
    .filter((o) => `${o.nombre} ${o.clave}`.toLowerCase().includes(filtro.toLowerCase()))
    .sort((a, b) => ocupados.has(a.id) - ocupados.has(b.id) || (b.brigada === Number(brigada)) - (a.brigada === Number(brigada)) || a.nombre.localeCompare(b.nombre));

  const alternar = (id) =>
    setElegidos((prev) => {
      const nuevo = new Set(prev);
      nuevo.has(id) ? nuevo.delete(id) : nuevo.add(id);
      return nuevo;
    });

  async function enviar(e) {
    e.preventDefault();
    setError('');
    setEnviando(true);
    try {
      const hoja = await api.post('/hojas/', {
        fecha, brigada: Number(brigada), centros: [...centrosElegidos], vehiculo: vehiculo ? Number(vehiculo) : null,
        hora_inicio: horaInicio, operarios: [...elegidos],
      });
      if (traer && noVisitadas.length > 0) {
        try { await api.post(`/hojas/${hoja.id}/asignar-no-visitadas/`); } catch { /* la hoja ya existe: se pueden traer desde ella */ }
      }
      if (traerPendientes && pendientes.length > 0) {
        try { await api.post(`/hojas/${hoja.id}/asignar-pendientes/`); } catch { /* la hoja ya existe: se pueden traer desde ella */ }
      }
      alCrear(hoja.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form className="tarjeta" onSubmit={enviar} aria-label="Nueva hoja de ruta">
      <h2>Nueva hoja de ruta · {fechaLarga(fecha)}</h2>
      <Aviso>{error}</Aviso>
      <div className="rejilla-formulario">
        <label>Brigada
          <select value={brigada} onChange={(e) => setBrigada(e.target.value)}>
            {brigadas.map((b) => <option key={b.id} value={b.id}>{b.nombre}</option>)}
          </select>
        </label>
        <label>Vehículo (chapa)
          <select value={vehiculo} onChange={(e) => setVehiculo(e.target.value)}>
            <option value="">Sin vehículo</option>
            {vehiculos.map((v) => <option key={v.id} value={v.id}>{v.chapa}</option>)}
          </select>
        </label>
        <label>Inicio de jornada
          <input type="time" value={horaInicio} onChange={(e) => setHoraInicio(e.target.value)} required />
        </label>
      </div>

      <fieldset>
        <legend>Centros donde trabajará la hoja ({centrosElegidos.size} seleccionado{centrosElegidos.size === 1 ? '' : 's'})</legend>
        <div className="rejilla-centros">
          {centros.map((c) => (
            <label key={c.id} className="casilla">
              <input type="checkbox" checked={centrosElegidos.has(c.id)} onChange={() => alternarCentro(c.id)} />
              <span>{c.codigo} · {c.nombre}</span>
            </label>
          ))}
        </div>
        <small className="suave">Un vehículo puede trabajar en varios centros en la misma hoja; cada servicio indica el suyo.</small>
      </fieldset>

      <fieldset>
        <legend>Operarios de la hoja ({elegidos.size} seleccionado{elegidos.size === 1 ? '' : 's'})</legend>
        <input placeholder="Buscar por nombre o clave…" value={filtro} onChange={(e) => setFiltro(e.target.value)} />
        <div className="lista-operarios">
          {lista.length === 0 && <p className="suave">No hay operarios. El administrador debe crearlos en el catálogo.</p>}
          {lista.map((o) => (
            <label key={o.id} className={`casilla ${ocupados.has(o.id) ? 'casilla-ocupada' : ''}`}>
              <input type="checkbox" checked={elegidos.has(o.id)} disabled={ocupados.has(o.id)} onChange={() => alternar(o.id)} />
              <span>{o.nombre} <small className="suave">
                {ocupados.has(o.id) ? `ya está en la hoja ${ocupados.get(o.id)}` : `${o.clave} · ${o.brigada_nombre}`}
              </small></span>
            </label>
          ))}
        </div>
      </fieldset>

      {noVisitadas.length > 0 && (
        <div className="opcion-traer">
          <label className="casilla">
            <input type="checkbox" checked={traer} onChange={(e) => setTraer(e.target.checked)} />
            <span>Traer a la hoja los <strong>{noVisitadas.length} servicio(s) no visitado(s)</strong> de días anteriores</span>
          </label>
          <small className="suave">{noVisitadas.map((o) => `${o.numero_servicio} (${o.ultima_fecha?.slice(8, 10)}/${o.ultima_fecha?.slice(5, 7)})`).join(' · ')}</small>
        </div>
      )}

      {pendientes.length > 0 && (
        <div className="opcion-traer opcion-pendientes">
          <label className="casilla">
            <input type="checkbox" checked={traerPendientes} onChange={(e) => setTraerPendientes(e.target.checked)} />
            <span>Traer a la hoja los <strong>{pendientes.length} servicio(s) pendiente(s)</strong> que otras brigadas pasaron a esta</span>
          </label>
          <small className="suave">{pendientes.map((o) => o.etiqueta).join(' · ')}</small>
        </div>
      )}

      <div className="acciones-formulario">
        <button type="button" className="boton" onClick={alCancelar}>Cancelar</button>
        <button className="boton boton-principal" disabled={enviando || elegidos.size === 0 || centrosElegidos.size === 0}>
          {enviando ? 'Creando…' : 'Crear hoja de ruta'}
        </button>
      </div>
    </form>
  );
}

export default function HojasDelDia({ usuario, catalogos, fecha, setFecha, abrir, crearInicial = false }) {
  const [hojas, setHojas] = useState(null);
  const [error, setError] = useState('');
  const [creando, setCreando] = useState(crearInicial && puede(usuario, 'operacion.add_hojaderuta'));

  const cargar = useCallback(() => {
    setError('');
    api.get(`/hojas/?fecha=${fecha}`).then((r) => setHojas(r.results)).catch((e) => setError(e.message));
  }, [fecha]);
  useEffect(() => { setHojas(null); cargar(); }, [cargar]);

  const suma = (campo) => hojas.reduce((t, h) => t + h.resultados[campo], 0);
  const resumen = hojas && {
    hojas: hojas.length,
    acciones: hojas.reduce((t, h) => t + h.cantidad_acciones, 0),
    cerradas: hojas.filter((h) => h.cerrada).length,
    ok: suma('ok'), sinOk: suma('sin_ok'), pasadas: suma('pasadas'), noVisitadas: suma('no_visitadas'), enCurso: suma('en_curso'),
  };

  return (
    <section>
      <div className="barra">
        <h1>Hojas de ruta</h1>
        <label className="en-linea">Fecha
          <input type="date" value={fecha} onChange={(e) => e.target.value && setFecha(e.target.value)} />
        </label>
        {puede(usuario, 'operacion.add_hojaderuta') && !creando && (
          <button className="boton boton-principal" onClick={() => setCreando(true)}>＋ Nueva hoja de ruta</button>
        )}
      </div>
      <p className="suave capitalizar">{fechaLarga(fecha)}</p>
      <Aviso>{error}</Aviso>

      {creando && (
        <NuevaHoja catalogos={catalogos} fecha={fecha} hojasDelDia={hojas || []} alCancelar={() => setCreando(false)}
          alCrear={(id) => { setCreando(false); abrir(id); }} />
      )}

      {hojas === null && !error && <p className="cargando">Cargando hojas…</p>}
      {resumen && hojas.length > 0 && (
        <div className="fila fila-chips" aria-label="Resumen del día">
          <span className="suave">{resumen.hojas} hoja(s) · {resumen.cerradas} cerrada(s) · {resumen.acciones} servicio(s):</span>
          <Chip tipo="ok">{resumen.ok} con OK</Chip>
          <Chip tipo="mal">{resumen.sinOk} sin OK</Chip>
          <Chip tipo="aviso">{resumen.pasadas} pasada(s) a otra brigada</Chip>
          <Chip>{resumen.noVisitadas} no visitada(s)</Chip>
          {resumen.enCurso > 0 && <Chip tipo="info">{resumen.enCurso} en curso</Chip>}
        </div>
      )}
      {hojas && hojas.length === 0 && !creando && (
        <div className="tarjeta vacio">
          <p>No hay hojas de ruta para este día.</p>
          <p className="suave">Una hoja se crea cuando se definen los operarios y los servicios que deben reparar.</p>
        </div>
      )}

      <div className="rejilla-tarjetas">
        {hojas && hojas.map((h) => (
          <button key={h.id} className="tarjeta tarjeta-hoja" onClick={() => abrir(h.id)}>
            <div className="fila">
              <strong>{h.centros_etiqueta} · {h.brigada_nombre}</strong>
              {h.cerrada ? <Chip>Cerrada</Chip> : <Chip tipo="info">Abierta</Chip>}
            </div>
            <div className="suave">{h.operarios_nombres.join(', ')}</div>
            <div className="fila fila-chips">
              {h.vehiculo_chapa && <Chip titulo="Chapa del vehículo">🚚 {h.vehiculo_chapa}</Chip>}
              <Chip>{h.cantidad_acciones} servicio(s)</Chip>
              {h.resultados.ok > 0 && <Chip tipo="ok">{h.resultados.ok} OK</Chip>}
              {h.resultados.pasadas > 0 && <Chip tipo="aviso">{h.resultados.pasadas} a otra brigada</Chip>}
              {h.resultados.no_visitadas > 0 && <Chip>{h.resultados.no_visitadas} no visitada(s)</Chip>}
              {h.incidencia_activa && <Chip tipo="aviso">⏱ {h.incidencia_activa}</Chip>}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
