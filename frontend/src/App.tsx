import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { AppLayout } from './components/AppLayout'
import { RequireAuth } from './components/RequireAuth'
import { AuthProvider } from './auth/AuthProvider'
import { ConfirmEmailPage } from './pages/ConfirmEmailPage'
import { CustomersPage } from './pages/CustomersPage'
import { FiscalIdentitiesPage } from './pages/FiscalIdentitiesPage'
import { LoginPage } from './pages/LoginPage'
import { NewTemplatePage } from './pages/NewTemplatePage'
import { RegisterPage } from './pages/RegisterPage'
import { TemplatePage } from './pages/TemplatePage'
import { TemplatesPage } from './pages/TemplatesPage'

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
              {/* La raíz es la grilla de modelos: es lo que se abre cien veces por semana.
                  Las identidades fiscales y los clientes son configuración —se tocan al
                  empezar y después casi nunca— así que dejar una de ellas de portada le
                  cobraría un toque a la pantalla principal en cada entrada. */}
              <Route index element={<TemplatesPage />} />
              {/* La literal antes que la dinámica es por costumbre y no por necesidad: el
                  router ordena por especificidad y `nuevo` le gana a `:id` igual. */}
              <Route path="/modelos/nuevo" element={<NewTemplatePage />} />
              <Route path="/modelos/:id" element={<TemplatePage />} />
              <Route path="/identidades" element={<FiscalIdentitiesPage />} />
              <Route path="/clientes" element={<CustomersPage />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
