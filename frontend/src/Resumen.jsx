import { useEffect, useState } from 'react';
import { api, fechaLarga, hoy, minutosATexto, porcentaje } from './api.js';
import { Aviso, Chip, Estadistica } from './componentes.jsx';

const PERIODOS = [['dia', 'Día'], ['mes', 'Mes'], ['anio', 'Año']];
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

function titulo(periodo, fecha) {
  if (periodo === 'dia') return fechaLarga(fecha);
  if (periodo === 'mes') return `${MESES[Number(fecha.slice(5, 7)) - 1]} de ${fecha.slice(0, 4)}`;
  return `Año ${fecha.slice(0, 4)}`;
}

const formatoFecha = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;

function Tabla({ columnas, filas, vacio = 'Sin datos en este período.' }) {
  if (filas.length === 0) return <p className="suave">{vacio}</p>;
  return (
    <div className="tabla-envoltura">
      <table>
        <thead><tr>{columnas.map((c) => <th key={c.titulo}>{c.titulo}</th>)}</tr></thead>
        <tbody>
          {filas.map((f, i) => (
            <tr key={f.clave ?? i}>{columnas.map((c) => <td key={c.titulo}>{c.valor(f)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const columnasDeIndicadores = [
  { titulo: 'Hojas', valor: (f) => f.hojas },
  { titulo: 'Servicios', valor: (f) => f.acciones },
  { titulo: 'Con OK', valor: (f) => f.ok },
  { titulo: 'Efectividad', valor: (f) => porcentaje(f.efectividad_pct) },
  { titulo: 'Productividad', valor: (f) => porcentaje(f.productividad_pct) },
  { titulo: 'Ocupación', valor: (f) => porcentaje(f.ocupacion_pct) },
];

function Barras({ datos, etiqueta }) {
  const maximo = Math.max(100, ...datos.flatMap((d) => [d.efectividad_pct ?? 0, d.productividad_pct ?? 0]));
  const alto = (v) => `${Math.max(2, ((v ?? 0) / maximo) * 100)}%`;
  return (
    <>
      <div className="barras" role="img" aria-label="Efectividad y productividad">
        {datos.map((d) => (
          <div key={d.clave} className="barra-grupo" title={`${d.nombre}: efectividad ${porcentaje(d.efectividad_pct)} · productividad ${porcentaje(d.productividad_pct)} · ${d.hojas} hoja(s)`}>
            <div className="barra-par">
              <div className="barra-v barra-efectividad" style={{ height: alto(d.efectividad_pct) }} />
              <div className="barra-v barra-productividad" style={{ height: alto(d.productividad_pct) }} />
            </div>
            <small>{d.etiqueta}</small>
          </div>
        ))}
      </div>
      <div className="fila fila-chips leyenda">
        <span className="leyenda-efectividad">■ Efectividad</span>
        <span className="leyenda-productividad">■ Productividad</span>
        <span className="suave">{etiqueta}</span>
      </div>
    </>
  );
}

export default function Resumen({ catalogos, abrirHoja }) {
  const [periodo, setPeriodo] = useState('dia');
  const [fecha, setFecha] = useState(hoy());
  const [brigada, setBrigada] = useState('');
  const [centro, setCentro] = useState('');
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let vigente = true;
    setError('');
    const params = new URLSearchParams({ periodo, fecha });
    if (brigada) params.set('brigada', brigada);
    if (centro) params.set('centro', centro);
    api.get(`/resumen/?${params}`).then((r) => vigente && setDatos(r)).catch((e) => vigente && setError(e.message));
    return () => { vigente = false; };
  }, [periodo, fecha, brigada, centro]);

  const t = datos?.totales;
  const serie = datos && (datos.por_dia
    ? datos.por_dia.map((d) => ({ ...d, clave: d.fecha, nombre: formatoFecha(d.fecha), etiqueta: d.fecha.slice(8) }))
    : datos.por_mes
      ? datos.por_mes.map((m) => ({ ...m, clave: m.mes, nombre: `${MESES[Number(m.mes.slice(5)) - 1]} ${m.mes.slice(0, 4)}`, etiqueta: MESES[Number(m.mes.slice(5)) - 1].slice(0, 3) }))
      : null);

  return (
    <section>
      <div className="barra no-imprimir">
        <h1>Resumen</h1>
        <div className="segmentos" role="group" aria-label="Período">
          {PERIODOS.map(([valor, texto]) => (
            <button key={valor} className={`segmento ${periodo === valor ? 'segmento-activo' : ''}`} aria-pressed={periodo === valor} onClick={() => setPeriodo(valor)}>{texto}</button>
          ))}
        </div>
        {periodo === 'dia' && <input type="date" aria-label="Día" value={fecha} onChange={(e) => e.target.value && setFecha(e.target.value)} />}
        {periodo === 'mes' && <input type="month" aria-label="Mes" value={fecha.slice(0, 7)} onChange={(e) => e.target.value && setFecha(`${e.target.value}-01`)} />}
        {periodo === 'anio' && <input type="number" aria-label="Año" min="2000" max="2100" value={fecha.slice(0, 4)} onChange={(e) => /^\d{4}$/.test(e.target.value) && setFecha(`${e.target.value}-01-01`)} />}
        <select aria-label="Brigada" value={brigada} onChange={(e) => setBrigada(e.target.value)}>
          <option value="">Todas las brigadas</option>
          {catalogos.brigadas.map((b) => <option key={b.id} value={b.id}>{b.nombre}</option>)}
        </select>
        <select aria-label="Centro" value={centro} onChange={(e) => setCentro(e.target.value)}>
          <option value="">Todos los centros</option>
          {catalogos.centros.map((c) => <option key={c.id} value={c.id}>{c.codigo} · {c.nombre}</option>)}
        </select>
        {periodo === 'dia' && (
          <span className="fila empujar descargas" aria-label="Informe del día">
            <a className="boton" href={`/api/informe-diario/?${new URLSearchParams({ fecha, ...(brigada && { brigada }), ...(centro && { centro }), formato: 'pdf' })}`} target="_blank" rel="noreferrer" title="Resumen del día y cada hoja de ruta con el formato original">Informe PDF</a>
            <a className="boton" href={`/api/informe-diario/?${new URLSearchParams({ fecha, ...(brigada && { brigada }), ...(centro && { centro }), formato: 'xlsx' })}`} title="Resumen, hojas de ruta con el formato original y hoja de auditoría">Informe Excel</a>
          </span>
        )}
        <button className={`boton ${periodo === 'dia' ? '' : 'empujar'}`} onClick={() => window.print()}>Imprimir</button>
      </div>
      <p className="suave capitalizar">
        {titulo(periodo, fecha)}
        {brigada && ` · ${catalogos.brigadas.find((b) => b.id === Number(brigada))?.nombre}`}
        {centro && ` · ${catalogos.centros.find((c) => c.id === Number(centro))?.nombre}`}
      </p>
      <Aviso>{error}</Aviso>
      {!datos && !error && <p className="cargando">Calculando…</p>}

      {datos && t.hojas === 0 && <div className="tarjeta vacio"><p>No hay hojas de ruta en este período.</p></div>}
      {datos && t.hojas > 0 && (
        <>
          <section className="rejilla-estadisticas" aria-label="Indicadores del período">
            <Estadistica etiqueta="Hojas de ruta" valor={t.hojas} />
            <Estadistica etiqueta="Servicios" valor={t.acciones} ayuda="Servicios asignados, incluidos los no visitados" />
            <Estadistica etiqueta="Efectivas (con OK)" valor={t.ok} />
            <Estadistica etiqueta="Efectividad" valor={porcentaje(t.efectividad_pct)} ayuda="Con OK entre atendidas (las no visitadas no cuentan)" />
            <Estadistica etiqueta="Productividad" valor={porcentaje(t.productividad_pct)} ayuda="Tiempo normado de las acciones efectivas entre el tiempo real" />
            <Estadistica etiqueta="Tiempo real" valor={minutosATexto(t.tiempo_real_min)} />
            <Estadistica etiqueta="Incidencias" valor={minutosATexto(t.incidencias_min)} ayuda="Suma por hoja de ruta" />
            <Estadistica etiqueta="Ocupación" valor={porcentaje(t.ocupacion_pct)} ayuda="Tiempo real entre tiempo disponible (420 min − incidencias) × operarios" />
          </section>
          <div className="fila fila-chips" aria-label="Resultado de los servicios">
            <Chip tipo="ok">{t.ok} con OK</Chip>
            <Chip tipo="mal">{t.sin_ok} sin OK</Chip>
            <Chip tipo="aviso">{t.pasadas} pasada(s) a otra brigada</Chip>
            <Chip>{t.no_visitadas} no visitada(s)</Chip>
            {t.en_curso > 0 && <Chip tipo="info">{t.en_curso} en curso</Chip>}
          </div>

          {serie && serie.length > 0 && (
            <section className="tarjeta">
              <h2>{datos.por_dia ? 'Por día' : 'Por mes'}</h2>
              <Barras datos={serie} etiqueta="Pase el cursor sobre una barra para ver el detalle" />
            </section>
          )}

          {datos.hojas && (
            <section className="tarjeta">
              <h2>Hojas de ruta del día</h2>
              <Tabla filas={datos.hojas.map((h) => ({ ...h, clave: h.id }))} columnas={[
                { titulo: 'Hoja', valor: (h) => <button className="enlace" onClick={() => abrirHoja(h.id)}>{h.centro} · {h.brigada}</button> },
                { titulo: 'Operarios', valor: (h) => h.operarios.join(', ') },
                { titulo: 'Servicios', valor: (h) => h.acciones },
                { titulo: 'OK / sin OK / pasadas / no visit.', valor: (h) => `${h.ok} / ${h.sin_ok} / ${h.pasadas} / ${h.no_visitadas}` },
                { titulo: 'Efectividad', valor: (h) => porcentaje(h.efectividad_pct) },
                { titulo: 'Productividad', valor: (h) => porcentaje(h.productividad_pct) },
                { titulo: 'Estado', valor: (h) => (h.cerrada ? 'Cerrada' : 'Abierta') },
              ]} />
            </section>
          )}

          <section className="tarjeta">
            <h2>Productividad individual</h2>
            <p className="suave">La productividad es de la hoja completa: cada operario recibe la de las hojas en que participó.</p>
            <Tabla filas={datos.por_operario.map((o) => ({ ...o, clave: o.id }))} columnas={[
              { titulo: 'Operario', valor: (o) => o.nombre },
              { titulo: 'Días', valor: (o) => o.dias },
              ...columnasDeIndicadores.filter((c) => c.titulo !== 'Ocupación'),
            ]} />
          </section>

          <section className="tarjeta"><h2>Por brigada</h2>
            <Tabla filas={datos.por_brigada.map((b) => ({ ...b, clave: b.nombre }))} columnas={[{ titulo: 'Brigada', valor: (b) => b.nombre }, ...columnasDeIndicadores]} />
          </section>
          <section className="tarjeta"><h2>Por centro</h2>
            <p className="suave">Según el centro de cada servicio (una hoja puede trabajar en varios centros).</p>
            <Tabla filas={datos.por_centro.map((c) => ({ ...c, clave: c.nombre }))} columnas={[{ titulo: 'Centro', valor: (c) => c.nombre }, ...columnasDeIndicadores.filter((c) => c.titulo !== 'Ocupación')]} />
          </section>

          <section className="tarjeta"><h2>Por tipo de acción</h2>
            <Tabla filas={datos.por_categoria.map((c) => ({ ...c, clave: c.codigo }))} columnas={[{ titulo: 'Tipo', valor: (c) => c.nombre }, ...columnasDeIndicadores.filter((c) => !['Hojas', 'Ocupación'].includes(c.titulo))]} />
          </section>
          {datos.por_vehiculo.length > 0 && (
            <section className="tarjeta"><h2>Por vehículo</h2>
              <Tabla filas={datos.por_vehiculo.map((v) => ({ ...v, clave: v.nombre }))} columnas={[{ titulo: 'Vehículo', valor: (v) => v.nombre }, ...columnasDeIndicadores]} />
            </section>
          )}

          <section className="tarjeta">
            <h2>Pasaron a otra brigada ({datos.pasadas_a_brigada.total})</h2>
            <Tabla vacio="Ningún servicio pasó a otra brigada." filas={datos.pasadas_a_brigada.lista.map((p, i) => ({ ...p, clave: i }))} columnas={[
              { titulo: 'Fecha', valor: (p) => formatoFecha(p.fecha) }, { titulo: 'Servicio', valor: (p) => p.servicio },
              { titulo: 'De', valor: (p) => `${p.centro} · ${p.desde}` }, { titulo: 'Hacia', valor: (p) => <strong>{p.hacia}</strong> },
              { titulo: 'Estado actual', valor: (p) => p.estado_actual },
            ]} />
          </section>

          <section className="tarjeta">
            <h2>No visitadas ({datos.no_visitadas.total})</h2>
            <Tabla vacio="Todos los servicios se visitaron." filas={datos.no_visitadas.lista.map((n, i) => ({ ...n, clave: i }))} columnas={[
              { titulo: 'Fecha', valor: (n) => formatoFecha(n.fecha) }, { titulo: 'Servicio', valor: (n) => n.servicio },
              { titulo: 'Brigada', valor: (n) => `${n.centro} · ${n.brigada}` },
              { titulo: 'Situación', valor: (n) => (n.sigue_sin_visitar ? <Chip tipo="aviso">Sigue sin visitar</Chip> : <Chip tipo="ok">Ya atendida después</Chip>) },
            ]} />
          </section>

          <div className="resultados">
            <section className="tarjeta">
              <h2>Reincidencias ({datos.reincidencias.total})</h2>
              <p className="suave">Servicios con más de una orden en el período.</p>
              <Tabla vacio="Sin reincidencias." filas={datos.reincidencias.lista.map((r) => ({ ...r, clave: r.servicio }))} columnas={[
                { titulo: 'Servicio', valor: (r) => r.servicio }, { titulo: 'Órdenes', valor: (r) => r.ordenes },
                { titulo: 'Operarios que lo trabajaron', valor: (r) => r.operarios.join(', ') },
                { titulo: 'Último', valor: (r) => formatoFecha(r.ultima_fecha) },
              ]} />
            </section>
            <section className="tarjeta">
              <h2>Incidencias por causa</h2>
              <Tabla vacio="Sin incidencias." filas={datos.incidencias.map((i) => ({ ...i, clave: i.codigo }))} columnas={[
                { titulo: 'Causa', valor: (i) => `${i.codigo} · ${i.nombre}` }, { titulo: 'Tiempo', valor: (i) => minutosATexto(i.minutos) },
                { titulo: 'Hojas', valor: (i) => i.hojas },
              ]} />
            </section>
          </div>
        </>
      )}
    </section>
  );
}
