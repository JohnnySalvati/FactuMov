# FactuMov — Ownership scoping y tests

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

## Ownership scoping (2026-08-26)
`user_id` en `fiscal_identities` y `customers`, todas las queries de esas dos tablas
scopeadas al usuario de la sesión, y las de `invoice_templates` scopeadas por join.
Migración `2c2b5ddd2d8d`.

- **`invoice_templates` no lleva `user_id`.** Cuelga de `fiscal_identity_id`, que ya está
  indexado, así que el scoping sale de un join. Denormalizar la columna acortaría las
  queries a cambio de una tercera fuente de verdad capaz de contradecir a sus padres —un
  modelo cuyo `user_id` dice A y cuya identidad fiscal es de B— y no ahorraría ninguna
  validación: chequear que los dos padres son del usuario hace falta igual al escribir.
  Con esa validación puesta, alcanza con joinear una sola de las dos relaciones, porque
  ambas apuntan siempre al mismo dueño.
- **Todos los uniques de esas dos tablas pasaron de globales a por-usuario:**
  `fiscal_identities.name` y `.tax_id` a `(user_id, name)` y `(user_id, tax_id)`, y
  `(doc_type, doc_number)` de `customers` a `(user_id, doc_type, doc_number)`. Global
  rompía casos normales —dos usuarios le facturan al mismo cliente; el contador carga el
  CUIT de su cliente mientras el titular tiene su propia cuenta— y sobre todo reintroducía
  por la puerta del 409 el oráculo de existencia que el 404 cierra en la lectura: "CUIT
  duplicado" sobre una fila ajena confirma que esa fila existe. Aflojar el unique del CUIT
  no afloja el control de titularidad, que lo da la verificación de la delegación en ARCA.
  `uq_invoice_templates_fiscal_identity_id_name` no cambió: ya queda scopeado
  transitivamente.
- **El 404 sale del filtro, no de una comparación.** Ningún `get_*_or_404` compara dueños:
  los getters filtran por `user_id` en la query, así que la fila ajena y la fila
  inexistente son el mismo caso y no hay rama que pueda contestar 403 por descuido. Por
  eso también `get_by_id` dejó de usar `db.get()`, que busca por PK y no admite filtro.
- **Escribir apuntando a un padre ajeno da 422, con el mismo mensaje que un id
  inexistente.** Es el caso que la base no puede atajar sola: la FK apunta a una fila que
  sí existe. Lo valida el CRUD de `invoice_template` en create y en update —el PATCH
  también, o el modelo se reapunta después de creado— levantando las `Unknown*Error` que
  ya existían, así que el router no cambió. El `exception_map` sigue mapeando las
  violaciones de FK como backstop para dos requests concurrentes.
- **Los dos lookups de `/import` van scopeados.** Era el bug más silencioso de la unidad:
  nadie escribía nada mal, pero el draft volvía con el `customer_id` de una fila ajena, el
  usuario lo confirmaba en el editor y el modelo guardado terminaba apuntando al cliente
  de otro.
- **`user_id` no entra por el body ni sale en los schemas `Read`.** Sale de la sesión y es
  argumento del CRUD, no campo del schema: aceptarlo por el body dejaría al cliente elegir
  a nombre de quién escribe, y devolverlo sugiere que es un campo del recurso cuando su
  valor es siempre el que consulta.
- **Sin `ondelete` en las dos FK a `users`.** El NO ACTION por defecto hace fallar el
  borrado de un usuario que todavía tiene datos, que es lo correcto mientras no exista el
  endpoint de baja de cuenta — esa unidad es la que va a elegir entre cascada y
  anonimizar. Por lo mismo no se declararon `User.customers` ni `User.fiscal_identities`:
  nada necesita navegar en esa dirección, y declararlas obliga a decidir hoy ese cascade.
- **La migración se niega a inventar un dueño.** Si hay filas huérfanas y no hay
  exactamente un usuario al cual atribuirlas, corta con `RuntimeError` en vez de adivinar
  — mismo criterio que `cf79c4f7610c`. El `downgrade` corta también, porque devolver los
  uniques a globales puede chocar con datos que el esquema nuevo permite legalmente (dos
  usuarios con el mismo CUIT o el mismo cliente).
- **Las factories piden `user_id` obligatorio** en `make_fiscal_identity` y
  `make_customer`. Con default hubieran sido más cortas de llamar y le habrían dado a la
  identidad fiscal y al cliente de un mismo test dos dueños distintos; la falla que sigue
  —`UnknownCustomerError` saliendo de un create de modelo— no se parece en nada a la
  causa. `make_invoice_template` no necesita dueño propio: lo lee de la identidad fiscal.

## Tests
- **Los tests de CRUD no pasan por HTTP; los de router sí**, con el fixture `client` de
  `conftest.py`. Ese fixture depende de `db` y sobreescribe `get_db` con
  `app.dependency_overrides`: sin eso el request abriría su propia sesión contra la base
  real y no vería nada de lo que el test armó. El override no commitea a propósito —
  revertir es trabajo del fixture `db`. La limpieza final no es opcional: `app` es un
  singleton de módulo y un override olvidado se filtra a todos los tests siguientes.
- **`Decimal` viaja como string en JSON** (`"1.00"`, no `1.0`): Pydantic lo serializa así
  para no perder la escala. Los asserts sobre importes comparan strings.
- **Desde la unidad de autenticación, `client` va autenticado y el anónimo es
  `anonymous_client`** — el porqué, y los detalles de la cookie `Secure` y del costo de
  argon2 en los fixtures, están en *Autenticación → Tests de autenticación*.
- **`other_user` es el segundo usuario, para los tests de scoping.** Va activo y confirmado
  a propósito: si estuviera dado de baja, un test que espera 404 podría estar pasando por
  el 401 de `get_current_user` y no por el scoping. Los fixtures `fiscal_identity` y
  `customer` son del usuario de `client`; las filas de `other_user` se arman con la factory
  en el propio test, que es donde se lee de quién es cada cosa.
- **El cliente de test es `httpx2`.** Starlette 1.5 importa `httpx2` primero y solo cae a
  `httpx` con un `StarletteDeprecationWarning`; la rama de fallback ya tiene un
  `RuntimeError` para cuando no esté ninguno. `httpx` igual sigue instalado porque
  `fastapi[standard]` lo requiere: es esperable, no un resto sin limpiar.

