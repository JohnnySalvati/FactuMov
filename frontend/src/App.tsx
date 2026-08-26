import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { AppLayout } from './components/AppLayout'
import { RequireAuth } from './components/RequireAuth'
import { AuthProvider } from './auth/AuthProvider'
import { ConfirmEmailPage } from './pages/ConfirmEmailPage'
import { CustomersPage } from './pages/CustomersPage'
import { FiscalIdentitiesPage } from './pages/FiscalIdentitiesPage'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/registro" element={<RegisterPage />} />
          {/* La ruta que nombra el link del mail. Su nombre lo fija `_CONFIRMATION_PATH` del
              backend: cambiarlo acá rompe los mails que ya se enviaron. */}
          <Route path="/confirmar-email" element={<ConfirmEmailPage />} />

          <Route element={<RequireAuth />}>
            <Route element={<AppLayout />}>
              <Route path="/identidades" element={<FiscalIdentitiesPage />} />
              <Route path="/clientes" element={<CustomersPage />} />
            </Route>
          </Route>

          {/* Cualquier otra cosa cae en identidades, que es la primera pantalla del flujo:
              sin un CUIT verificado no se puede hacer nada más. */}
          <Route path="*" element={<Navigate to="/identidades" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
