import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { AppLayout } from './components/AppLayout'
import { PublicLayout } from './components/PublicLayout'
import { RequireAuth } from './components/RequireAuth'
import { AuthProvider } from './auth/AuthProvider'
import { ConfirmEmailPage } from './pages/ConfirmEmailPage'
import { CustomerPage } from './pages/CustomerPage'
import { CustomersPage } from './pages/CustomersPage'
import { DelegationAcceptedPage } from './pages/DelegationAcceptedPage'
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
import { SettingsPage } from './pages/SettingsPage'
import { TemplatePage } from './pages/TemplatePage'
import { TemplatesPage } from './pages/TemplatesPage'

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Las pantallas sin sesión comparten layout: la marca arriba y el crédito de
              InSoft abajo. Es también el único lugar de la app donde se muestra la marca a
              alguien que todavía no entró. */}
          <Route element={<PublicLayout />}>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/registro" element={<RegisterPage />} />
            {/* Las rutas que nombran un link de mail. Sus nombres los fijan
                `_CONFIRMATION_PATH` y `_PASSWORD_RESET_PATH` del backend: cambiarlos acá rompe
                los mails que ya se enviaron. */}
            <Route path="/confirmar-email" element={<ConfirmEmailPage />} />
            <Route path="/olvide-password" element={<ForgotPasswordPage />} />
            <Route path="/restablecer-password" element={<ResetPasswordPage />} />
            {/* La única ruta pública que no es para un usuario: donde aterriza el operador
                desde el mail que le pide aceptar una designación en ARCA. Va sin sesión
                porque la identidad fiscal que mira no es suya y nunca podría serlo — lo que
                lo autoriza es el token del link. Su nombre lo fija
                `_DELEGATION_ACCEPTED_PATH` del backend. */}
            <Route path="/delegacion-aceptada" element={<DelegationAcceptedPage />} />
          </Route>

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
              {/* Fuera de las cuatro pestañas y del gesto de deslizar: los ajustes se
                  tocan una vez y no se vuelven a mirar, así que ocupar un quinto lugar en la
                  barra le cobraría ancho a las cuatro que sí se usan todas las semanas. Se
                  llega por el engranaje, que en el celular es lo único de la derecha que se
                  ve — el mail del usuario está oculto abajo de 640px. */}
              <Route path="/ajustes" element={<SettingsPage />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
