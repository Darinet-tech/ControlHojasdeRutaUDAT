import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// En desarrollo, la pantalla (puerto 5173) reenvía /api al servidor Django de este proyecto (PUERTO_DESARROLLO, 8001 por defecto).
const api = `http://127.0.0.1:${process.env.PUERTO_DESARROLLO || 8001}`;
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: api, changeOrigin: true },
      '/admin': { target: api, changeOrigin: true },
      '/static': { target: api, changeOrigin: true },
    },
  },
});
