import { useEffect, useState } from 'react';
import { api, fechaLarga, minutosATexto, porcentaje, puede } from './api.js';
import { Aviso, Chip, Estadistica } from './componentes.jsx';

const saludo = () => { const h = new Date().getHours(); return h < 12 ? 'Buenos días' : h < 19 ? 'Buenas tardes' : 'Buenas noches'; };
const mayuscula = (t) => t.charAt(0).toUpperCase() + t.slice(1);
const diaMes = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

const PERIODOS = [['anterior', 'Jornada anterior'], ['mes', 'Este mes'], ['anio', 'Este año']];

function TablaSimple({ columnas, filas, vacio }) {
  if (filas.length === 0) return <p className="suave">{vacio}</p>;
  return (
    <div className="tabla-envoltura">
      <table>
        <thead><tr>{columnas.map((c) => <th key={c.titulo}>{c.titulo}</th>)}</tr></thead>
        <tbody>{filas.map((f, i) => <tr key={i}>{columnas.map((c) => <td key={c.titulo}>{c.valor(f)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

// Para jefes y especialistas: tiempo perdido por causa de incidencia y quiénes fueron los más productivos.
function Analisis() {
  const [periodo, setPeriodo] = useState('anterior');
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let vigente = true;
    setDatos(null); setError('');
    api.get(`/analisis/?periodo=${periodo}`).then((r) => vigente && setDatos(r)).catch((e) => vigente && setError(e.message));
    return () => { vigente = false; };
  }, [periodo]);
  const mejores = [
    { titulo: 'Más productivo', valor: (f) => f.nombre },
    { titulo: 'Productividad', valor: (f) => porcentaje(f.productividad_pct) },
    { titulo: 'Efectividad', valor: (f) => porcentaje(f.efectividad_pct) },
    { titulo: 'Servicios', valor: (f) => f.acciones },
  ];
  return (
    <section className="tarjeta" aria-label="Análisis">
      <div className="fila">
        <h2>Análisis</h2>
        <div className="segmentos empujar" role="group" aria-label="Período del análisis">
          {PERIODOS.map(([valor, texto]) => (
            <button key={valor} className={`segmento ${periodo === valor ? 'segmento-activo' : ''}`} aria-pressed={periodo === valor} onClick={() => setPeriodo(valor)}>{texto}</button>
          ))}
        </div>
      </div>
      <Aviso>{error}</Aviso>
      {!datos && !error && <p className="cargando">Calculando…</p>}
      {datos && datos.hojas === 0 && <p className="suave">{periodo === 'anterior' ? 'No hay una jornada anterior con hojas de ruta.' : 'Sin hojas de ruta en este período.'}</p>}
      {datos && datos.hojas > 0 && (
        <>
          <p className="suave">
            {periodo === 'anterior' ? `Jornada del ${datos.fecha.slice(8, 10)}/${datos.fecha.slice(5, 7)}/${datos.fecha.slice(0, 4)}` : periodo === 'mes' ? 'Mes en curso' : 'Año en curso'} · {datos.hojas} hoja(s) de ruta.
            La productividad de un operario es la de las hojas en que participó.
          </p>
          <div className="resultados">
            <div>
              <h3>Tiempo perdido por incidencias · {minutosATexto(datos.incidencias_min)}</h3>
              <TablaSimple vacio="Sin incidencias en este período." filas={datos.incidencias} columnas={[
                { titulo: 'Causa', valor: (i) => `${i.codigo} · ${i.nombre}` }, { titulo: 'Tiempo', valor: (i) => minutosATexto(i.minutos) }, { titulo: 'Hojas', valor: (i) => i.hojas },
              ]} />
            </div>
            <div>
              <h3>Operarios más productivos</h3>
              <TablaSimple vacio="Aún no hay tiempo real registrado." filas={datos.operarios} columnas={mejores} />
            </div>
            <div>
              <h3>Vehículos más productivos</h3>
              <TablaSimple vacio="Sin vehículos registrados en las hojas." filas={datos.vehiculos} columnas={mejores.map((c) => (c.titulo === 'Más productivo' ? { ...c, titulo: 'Vehículo' } : c))} />
            </div>
          </div>
        </>
      )}
    </section>
  );
}

export default function Inicio({ usuario, irA, abrirHoja }) {
  // el análisis es para quien consulta (jefes, especialistas, administración), no para quien registra las hojas
  const veAnalisis = usuario.es_superusuario || !usuario.permisos.includes('operacion.add_hojaderuta');
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { api.get('/inicio/').then(setDatos).catch((e) => setError(e.message)); }, []);

  // Lo que requiere atención, de lo más urgente a lo informativo.
  const atencion = [];
  if (datos) {
    datos.hojas_abiertas_anteriores.forEach((h) => atencion.push({
      clave: `ha${h.id}`, tipo: 'mal',
      texto: `La hoja ${h.etiqueta} del ${diaMes(h.fecha)} sigue abierta${h.en_curso ? ` con ${h.en_curso} servicio(s) sin cerrar` : ''}. Hay que cerrarla para que lo no atendido pase a "no visitado".`,
      boton: ['Abrir hoja', () => abrirHoja(h.id)],
    }));
    datos.incidencias_activas.forEach((i) => atencion.push({
      clave: `in${i.hoja}`, tipo: 'aviso',
      texto: `Contador activo: ${i.causa} en la hoja ${i.etiqueta} (${minutosATexto(i.minutos)}).`,
      boton: ['Abrir hoja', () => abrirHoja(i.hoja)],
    }));
    datos.no_visitadas.forEach((n) => atencion.push({
      clave: `nv${n.brigada_id}`, tipo: 'info',
      texto: `${n.brigada}: ${n.cantidad} servicio(s) quedaron sin visitar y se pueden traer a la próxima hoja.`,
      boton: puede(usuario, 'operacion.add_hojaderuta') ? ['Crear hoja de ruta', () => irA('hojas', { crear: true })] : null,
    }));
    datos.pendientes.forEach((n) => atencion.push({
      clave: `pe${n.brigada_id}`, tipo: 'info',
      texto: `${n.brigada}: ${n.cantidad} servicio(s) pendiente(s) que otras brigadas pasaron a la suya.`,
      boton: puede(usuario, 'operacion.add_hojaderuta') ? ['Crear hoja de ruta', () => irA('hojas', { crear: true })] : null,
    }));
    if (datos.catalogos?.claves_por_revisar > 0) atencion.push({
      clave: 'cr', tipo: 'aviso', texto: `${datos.catalogos.claves_por_revisar} clave(s) de cierre marcadas "por revisar" en el catálogo.`,
      boton: ['Abrir catálogo', () => window.open('http://127.0.0.1:8000/admin/catalogos/clave/?revisar__exact=1', '_blank')],
    });
    if (datos.catalogos?.claves_sin_norma > 0) atencion.push({
      clave: 'sn', tipo: 'aviso', texto: `${datos.catalogos.claves_sin_norma} clave(s) activas sin norma de tiempo: no se podrá calcular su productividad.`,
      boton: ['Abrir catálogo', () => window.open('http://127.0.0.1:8000/admin/catalogos/clave/', '_blank')],
    });
  }
  const t = datos?.hoy;

  return (
    <section>
      <div className="barra">
        <h1>Inicio</h1>
        {datos && puede(usuario, 'operacion.add_hojaderuta') && (
          <button className="boton boton-principal empujar" onClick={() => irA('hojas', { crear: true })}>＋ Nueva hoja de ruta</button>
        )}
      </div>
      <p className="suave">{saludo()}, {usuario.nombre}{datos ? ` · ${mayuscula(fechaLarga(datos.fecha))}` : ''}</p>
      <Aviso>{error}</Aviso>
      {!datos && !error && <p className="cargando">Cargando…</p>}

      {datos && (
        <>
          <section className="tarjeta" aria-label="Requiere su atención">
            <h2>Requiere su atención</h2>
            {atencion.length === 0 && <p className="todo-bien">✔ Inicio de jornada sin tareas pendientes.</p>}
            <ul className="lista-atencion">
              {atencion.map((a) => (
                <li key={a.clave} className={`atencion atencion-${a.tipo}`}>
                  <span>{a.texto}</span>
                  {a.boton && <button className="boton" onClick={a.boton[1]}>{a.boton[0]}</button>}
                </li>
              ))}
            </ul>
          </section>

          {veAnalisis && <Analisis />}

          <h2>Hoy</h2>
          <section className="rejilla-estadisticas" aria-label="Situación de hoy">
            <Estadistica etiqueta="Hojas de ruta" valor={t.hojas} />
            <Estadistica etiqueta="Servicios" valor={t.acciones} />
            <Estadistica etiqueta="Efectividad" valor={porcentaje(t.efectividad_pct)} ayuda="Con OK entre atendidas" />
            <Estadistica etiqueta="Productividad" valor={porcentaje(t.productividad_pct)} />
          </section>
          <div className="fila fila-chips">
            <Chip tipo="ok">{t.ok} con OK</Chip>
            <Chip tipo="mal">{t.sin_ok} sin OK</Chip>
            <Chip tipo="aviso">{t.pasadas} pasada(s) a otra brigada</Chip>
            <Chip>{t.no_visitadas} no visitada(s)</Chip>
            {t.en_curso > 0 && <Chip tipo="info">{t.en_curso} en curso</Chip>}
            <span className="suave">Este mes: {datos.mes.hojas} hoja(s) · efectividad {porcentaje(datos.mes.efectividad_pct)} · productividad {porcentaje(datos.mes.productividad_pct)}</span>
          </div>

          {datos.hojas_hoy.length > 0 && (
            <>
              <h2>Hojas de ruta de hoy</h2>
              <div className="rejilla-tarjetas">
                {datos.hojas_hoy.map((h) => (
                  <button key={h.id} className="tarjeta tarjeta-hoja" onClick={() => abrirHoja(h.id)}>
                    <div className="fila">
                      <strong>{h.centro} · {h.brigada}</strong>
                      {h.cerrada ? <Chip>Cerrada</Chip> : <Chip tipo="info">Abierta</Chip>}
                    </div>
                    <div className="suave">{h.operarios.join(', ')}</div>
                    <div className="fila fila-chips">
                      <Chip>{h.acciones} servicio(s)</Chip>
                      {h.ok > 0 && <Chip tipo="ok">{h.ok} OK</Chip>}
                      {h.pasadas > 0 && <Chip tipo="aviso">{h.pasadas} a otra brigada</Chip>}
                      {h.no_visitadas > 0 && <Chip>{h.no_visitadas} no visitada(s)</Chip>}
                    </div>
                  </button>
                ))}
              </div>
            </>
          )}

          <div className="fila accesos">
            <button className="boton" onClick={() => irA('hojas', { hoy: true })}>Ver las hojas de ruta</button>
            <button className="boton" onClick={() => irA('resumen')}>Ver el resumen</button>
            <a className="boton" href={`/api/informe-diario/?fecha=${datos.fecha}&formato=pdf`} target="_blank" rel="noreferrer">Informe de hoy (PDF)</a>
            <a className="boton" href={`/api/informe-diario/?fecha=${datos.fecha}&formato=xlsx`}>Informe de hoy (Excel)</a>
          </div>
        </>
      )}
    </section>
  );
}
