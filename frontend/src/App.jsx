import { useEffect, useRef, useState } from 'react';
import { api, fechaLarga, hoy, puede } from './api.js';
import { Aviso, Chip, Modal } from './componentes.jsx';
import HojaDetalle from './HojaDetalle.jsx';
import Inicio from './Inicio.jsx';
import HojasDelDia from './HojasDelDia.jsx';
import Login from './Login.jsx';
import Resumen from './Resumen.jsx';

async function cargarCatalogos() {
  const [brigadas, centros, vehiculos, operarios, tiposOrden, causas, claves, tiposMantenimiento, tiposTrabajo] = await Promise.all([
    api.get('/brigadas/'), api.get('/centros/'), api.get('/vehiculos/'), api.get('/operarios/'),
    api.get('/tipos-orden/'), api.get('/causas-incidencia/'), api.get('/claves/'),
    api.get('/tipos-mantenimiento/'), api.get('/tipos-trabajo/'),
  ]);
  return { brigadas, centros, vehiculos, operarios, tiposOrden, causas, claves, tiposMantenimiento, tiposTrabajo };
}

export default function App() {
  const [usuario, setUsuario] = useState(undefined); // undefined = comprobando, null = sin sesión
  const [catalogos, setCatalogos] = useState(null);
  const [errorCatalogos, setErrorCatalogos] = useState('');
  const [fecha, setFecha] = useState(hoy());
  const [hojaAbierta, setHojaAbierta] = useState(null);
  const [seccion, setSeccion] = useState('inicio'); // 'inicio' | 'hojas' | 'resumen'
  const [crearAlAbrir, setCrearAlAbrir] = useState(false);
  const [alertaSalida, setAlertaSalida] = useState(null); // hojas sin cerrar al intentar salir
  const sinCerrar = useRef(0);
  const puedeCerrar = puede(usuario, 'operacion.add_hojaderuta');

  useEffect(() => {
    api.get('/auth/me/').then(setUsuario).catch(() => setUsuario(null));
  }, []);

  useEffect(() => {
    if (!usuario) return;
    cargarCatalogos().then(setCatalogos).catch((e) => setErrorCatalogos(e.message));
  }, [usuario]);

  // Quien puede cerrar hojas recibe un aviso del navegador si intenta cerrar la pestaña con hojas sin cerrar.
  useEffect(() => {
    if (!usuario || !puedeCerrar) return undefined;
    let activo = true;
    const leer = () => api.get('/hojas/?cerrada=false').then((r) => { if (activo) sinCerrar.current = r.count; }).catch(() => {});
    leer();
    const reloj = setInterval(leer, 60000);
    return () => { activo = false; clearInterval(reloj); };
  }, [usuario, puedeCerrar, seccion, hojaAbierta]);
  useEffect(() => {
    const avisar = (e) => { if (sinCerrar.current > 0) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', avisar);
    return () => window.removeEventListener('beforeunload', avisar);
  }, []);

  // Al pulsar "Salir": si quedan hojas sin cerrar, se avisa antes de cerrar la sesión.
  async function pedirSalida() {
    if (puedeCerrar) {
      try {
        const r = await api.get('/hojas/?cerrada=false');
        if (r.count > 0) { setAlertaSalida(r.results); return; }
      } catch { /* si no se puede comprobar, se deja salir */ }
    }
    await salir();
  }

  async function salir() {
    sinCerrar.current = 0;
    setAlertaSalida(null);
    await api.post('/auth/logout/');
    setUsuario(null);
    setCatalogos(null);
    setHojaAbierta(null);
    setSeccion('inicio');
    setFecha(hoy()); // el siguiente usuario empieza en el día de hoy
  }

  const irA = (destino, opciones = {}) => {
    setSeccion(destino);
    setHojaAbierta(null);
    setCrearAlAbrir(!!opciones.crear);
    if (opciones.crear || opciones.hoy) setFecha(hoy());
  };
  const abrirHoja = (id) => { setSeccion('hojas'); setHojaAbierta(id); };

  if (usuario === undefined) return <p className="cargando">Cargando…</p>;
  if (usuario === null) return <Login alEntrar={setUsuario} />;

  return (
    <>
      <header className="cabecera">
        <button className="marca" onClick={() => irA('inicio')} aria-label="Ir al inicio">
          <img className="logo" src="/logo-etecsa.png" alt="ETECSA" />
          <span className="marca-texto">
            <strong>Unidad de Asistencia Técnica</strong>
            <span className="siglas">UDAT</span>
          </span>
        </button>
        <nav className="navegacion" aria-label="Secciones">
          <button className={`nav-boton ${seccion === 'inicio' ? 'nav-activo' : ''}`} aria-current={seccion === 'inicio' ? 'page' : undefined} onClick={() => irA('inicio')}>Inicio</button>
          <button className={`nav-boton ${seccion === 'hojas' ? 'nav-activo' : ''}`} aria-current={seccion === 'hojas' ? 'page' : undefined} onClick={() => irA('hojas')}>Hojas de ruta</button>
          <button className={`nav-boton ${seccion === 'resumen' ? 'nav-activo' : ''}`} aria-current={seccion === 'resumen' ? 'page' : undefined} onClick={() => irA('resumen')}>Resumen</button>
        </nav>
        <span className="cabecera-usuario">
          {usuario.nombre} <small>({usuario.grupos.join(', ') || (usuario.es_superusuario ? 'Administrador' : 'sin rol')})</small>
        </span>
        {usuario.puede_administrar && (
          <a className="enlace" href="http://127.0.0.1:8000/admin/" target="_blank" rel="noreferrer">Administración</a>
        )}
        <button className="boton" onClick={pedirSalida}>Salir</button>
      </header>
      <main className="contenido">
        <Aviso>{errorCatalogos}</Aviso>
        {!catalogos && !errorCatalogos && <p className="cargando">Cargando catálogos…</p>}
        {catalogos && seccion === 'inicio' && <Inicio usuario={usuario} irA={irA} abrirHoja={abrirHoja} />}
        {catalogos && seccion === 'resumen' && <Resumen catalogos={catalogos} abrirHoja={abrirHoja} />}
        {catalogos && seccion === 'hojas' && hojaAbierta === null && (
          <HojasDelDia usuario={usuario} catalogos={catalogos} fecha={fecha} setFecha={setFecha} abrir={setHojaAbierta} crearInicial={crearAlAbrir} />
        )}
        {catalogos && seccion === 'hojas' && hojaAbierta !== null && (
          <HojaDetalle id={hojaAbierta} usuario={usuario} catalogos={catalogos} volver={() => setHojaAbierta(null)} />
        )}
      </main>
      {alertaSalida && (
        <Modal titulo="Hay hojas de ruta sin cerrar" alCerrar={() => setAlertaSalida(null)}>
          <p>Antes de salir, recuerde cerrar las hojas de ruta: al cerrarlas se detienen los contadores de incidencias y lo que no se atendió pasa a <strong>no visitado</strong> para el siguiente día.</p>
          <ul className="lista-simple">
            {alertaSalida.map((h) => (
              <li key={h.id} className="fila">
                <span>{fechaLarga(h.fecha).replace(/^./, (c) => c.toUpperCase())} · <strong>{h.centros_etiqueta} · {h.brigada_nombre}</strong>{' '}
                  {h.resultados.en_curso > 0 && <Chip tipo="aviso">{h.resultados.en_curso} servicio(s) sin cerrar</Chip>}</span>
                <button className="boton empujar" onClick={() => { setAlertaSalida(null); abrirHoja(h.id); }}>Abrir hoja</button>
              </li>
            ))}
          </ul>
          <div className="acciones-formulario">
            <button className="boton boton-principal" onClick={() => setAlertaSalida(null)}>Volver a la aplicación</button>
            <button className="boton boton-peligro" onClick={salir}>Salir de todos modos</button>
          </div>
        </Modal>
      )}
    </>
  );
}
