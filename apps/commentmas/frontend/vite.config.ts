import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const localApi = { target: 'http://127.0.0.1:8000', changeOrigin: true };

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { '/api': localApi } },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': mode === 'presentation'
        ? { target: 'https://commentmas.vercel.app', changeOrigin: true }
        : localApi,
    },
  },
}));
