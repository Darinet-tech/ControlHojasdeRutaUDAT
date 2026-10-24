import { useState } from 'react';
import { api } from './api.js';
import { Aviso } from './componentes.jsx';

export default function Login({ alEntrar }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);

  async function enviar(e) {
    e.preventDefault();
    setError('');
    setEnviando(true);
    try {
      alEntrar(await api.post('/auth/login/', { username, password }));
    } catch (err) {
      setError(err.message);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main className="login">
      <form className="tarjeta login-formulario" onSubmit={enviar}>
        <div className="login-banda">
          <img className="logo-etecsa-chico" src="/logo-etecsa.png" alt="ETECSA" />
          <img className="logo-udat" src="/logo-udat.svg" alt="UDAT" />
          <h1>Unidad de Asistencia Técnica</h1>
          <p>UDAT</p>
        </div>
        <div className="login-campos">
          <Aviso>{error}</Aviso>
          <label>
            Usuario
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" required />
          </label>
          <label>
            Contraseña
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </label>
          <button className="boton boton-principal" disabled={enviando}>
            {enviando ? 'Entrando…' : 'Entrar'}
          </button>
        </div>
      </form>
    </main>
  );
}
