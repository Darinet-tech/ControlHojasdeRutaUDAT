import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './estilos.css';
import { fijarTema, temaInicial } from './tema.js';

fijarTema(temaInicial(), false); // por si no se aplicó antes de cargar la página

createRoot(document.getElementById('root')).render(<App />);
