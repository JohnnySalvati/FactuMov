import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { AppLayout } from './components/AppLayout'
import { RequireAuth } from './components/RequireAuth'
import { AuthProvider } from './auth/AuthProvider'
import { ConfirmEmailPage } from './pages/ConfirmEmailPage'
import { CustomerPage } from './pages/CustomerPage'
import { CustomersPage } from './pages/CustomersPage'
import { FiscalIdentitiesPage } from './pages/FiscalIdentitiesPage'
import { EmitPage } from './pages/EmitPage'
import { FiscalIdentityPage } from './pages/FiscalIdentityPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { InvoicePage } from './pages/InvoicePage'
import { InvoicesPage } from './pages/InvoicesPage'
import { LoginPage } from './pages/LoginPage'
import { NewTemplatePage } from './pages/NewTemplatePage'
import { RegisterPage } from './pages/RegisterPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { TemplatePage } from './pages/TemplatePage'
import { TemplatesPage } from './pages/TemplatesPage'

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/registro" element={<RegisterPage />} />
          {/* Las dos rutas que nombran un link de mail. Sus nombres los fijan
              `_CONFIRMATION_PATH` y `_PASSWORD_RESET_PATH` del backend: cambiarlos acá rompe
              los mails que ya se enviaron. */}
          <Route path="/confirmar-email" element={<ConfirmEmailPage />} />
          <Route path="/olvide-password" element={<ForgotPasswordPage />} />
          <Route path="/restablecer-password" element={<ResetPasswordPage />} />

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
              {/* La confirmación de la emisión es su propia ruta y no un diálogo adentro del
                  modelo. Emitir es irreversible: separarlo en una pantalla es lo que impide
                  que un dedo mal apoyado al lado de "Guardar" pida un CAE de verdad. */}
              <Route path="/modelos/:id/emitir" element={<EmitPage />} />
              {/* Las facturas emitidas solo se leen: no hay ruta de alta ni de edición, y esa
                  ausencia es la decisión. Se crean emitiendo un modelo y no se corrigen. */}
              <Route path="/facturas" element={<InvoicesPage />} />
              <Route path="/facturas/:id" element={<InvoicePage />} />
              {/* Identidades y clientes siguen la misma forma que los modelos: la grilla en
                  la ruta pelada y una pantalla por elemento. Que el id vaya en el path y no
                  como `?editar=` es lo que hace que el "mantener apretado" del editor de
                  modelos sea un link común. */}
              <Route path="/identidades" element={<FiscalIdentitiesPage />} />
              <Route path="/identidades/nueva" element={<FiscalIdentityPage />} />
              <Route path="/identidades/:id" element={<FiscalIdentityPage />} />
              <Route path="/clientes" element={<CustomersPage />} />
              <Route path="/clientes/nuevo" element={<CustomerPage />} />
              <Route path="/clientes/:id" element={<CustomerPage />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
