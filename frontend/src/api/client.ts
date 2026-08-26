/**
 * El cliente HTTP. Un `fetch` con tres cosas encima: el prefijo, las cookies y los errores.
 *
 * No hay token en ningún lado y no hay nada guardado en `localStorage`: la sesión es una
 * cookie `httpOnly` que el navegador manda solo. Eso es deliberado del lado del backend —el
 * JS no puede leerla, así que un XSS no se la lleva— y la contrapartida acá es que el front
 * **no puede saber si hay sesión sin preguntar**. De ahí que `AuthProvider` arranque con un
 * `GET /auth/me` en vez de leer un flag.
 */

const BASE = '/api'

/** Un error que el backend explicó. `status` es lo que decide qué hacer con él. */
export class ApiError extends Error {
  readonly status: number
  /** El `detail` de FastAPI, ya aplanado a texto. */
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/**
 * FastAPI usa `detail` para todo, pero con dos formas: un string en los `HTTPException` y una
 * lista de objetos en los 422 de validación de Pydantic. Aplanarlas acá evita que cada
 * pantalla tenga que hacer el `typeof` — y evita el clásico "[object Object]" en un cartel.
 */
function readDetail(body: unknown, status: number): string {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          typeof item === 'object' && item !== null && 'msg' in item
            ? String((item as { msg: unknown }).msg)
            : null,
        )
        .filter((message): message is string => message !== null)
      if (messages.length > 0) return messages.join('. ')
    }
  }
  return `Error ${status}`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  // Con `FormData` el `Content-Type` **no** se pone a mano: el navegador tiene que escribirlo
  // él, porque incluye el `boundary` que separa las partes del multipart. Fijarlo acá manda un
  // header sin boundary y el backend contesta 422 sin haber leído un solo byte del archivo.
  const isMultipart = init.body instanceof FormData

  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      // Sin esto el navegador no manda la cookie de sesión y **todo** contesta 401, que es
      // una falla que no se parece en nada a su causa.
      credentials: 'include',
      headers: isMultipart
        ? { ...init.headers }
        : { 'Content-Type': 'application/json', ...init.headers },
    })
  } catch {
    // `fetch` solo rechaza cuando no hubo respuesta: backend apagado, DNS, red cortada. Un
    // 500 no cae acá. Se convierte a `ApiError` igual para que las pantallas tengan un solo
    // tipo de error que atajar.
    throw new ApiError(0, 'No se pudo conectar con el servidor.')
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  const body: unknown = text ? JSON.parse(text) : null

  if (!response.ok) throw new ApiError(response.status, readDetail(body, response.status))
  return body as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  /** Sube un archivo como `multipart/form-data`. El campo se llama `file` porque así se llama
   *  el parámetro `UploadFile` del endpoint: FastAPI lo busca por nombre. */
  upload: <T>(path: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<T>(path, { method: 'POST', body: form })
  },
}
