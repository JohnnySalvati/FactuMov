import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// El backend se sirve bajo `/api` a través del proxy del dev server, y no directo contra
// `http://localhost:8000`.
//
// Con el proxy el navegador ve **un solo origen**, así que no hace falta CORS. La
// alternativa —pegarle directo al 8000 y agregarle `CORSMiddleware` a FastAPI— obligaría a
// `allow_credentials=True` con una lista de orígenes, que es una superficie real: la cookie
// de sesión es `httpOnly` justamente para que ningún JS la toque, y abrir CORS con
// credenciales es la forma más común de arruinar esa decisión sin darse cuenta.
//
// En producción no cambia nada: la SPA y la API van detrás del mismo nginx, que es lo que
// este proxy imita. Por eso el cliente pega siempre a rutas relativas y no hay ninguna
// variable de entorno con la URL del backend.
export default defineConfig({
  plugins: [react()],
  server: {
    // Fijo y no "el primero que esté libre": `APP_BASE_URL` del backend apunta acá, y de esa
    // variable cuelga el link de confirmación que sale por mail. Si Vite se corre a 5174
    // porque 5173 estaba ocupado, el link llega roto.
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // El backend no sabe nada del prefijo `/api`: sus rutas son `/auth/login`,
        // `/customers`, etc. El prefijo existe solo para que el proxy sepa qué reenviar y
        // qué servir como parte de la SPA.
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
