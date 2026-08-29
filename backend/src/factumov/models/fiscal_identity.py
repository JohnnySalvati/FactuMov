import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.enums import CondicionIva
from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.invoice_template import InvoiceTemplate


class FiscalIdentity(Base, TimestampMixin):
    __tablename__ = "fiscal_identities"
    __table_args__ = (
        # Unique por usuario, no global. Global rompe el caso del contador que carga el
        # CUIT de su cliente mientras el titular tiene su propia cuenta, y sobre todo
        # convierte el 409 en el oráculo de existencia que el 404 de esta unidad evita.
        UniqueConstraint("user_id", "name", name="uq_fiscal_identities_user_id_name"),
        UniqueConstraint("user_id", "tax_id", name="uq_fiscal_identities_user_id_tax_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Sin ondelete: el NO ACTION por defecto hace fallar el borrado de un usuario que
    # todavía tiene datos. Es lo correcto mientras no exista el endpoint de baja de
    # cuenta, que es la unidad que va a decidir si se borra en cascada o se anonimiza.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    condicion_iva: Mapped[CondicionIva] = mapped_column(Enum(CondicionIva))
    tax_id: Mapped[str] = mapped_column(String(11))
    address: Mapped[str | None] = mapped_column(String(200))
    iibb: Mapped[str | None] = mapped_column(String(50))
    start_date: Mapped[date | None] = mapped_column(Date)
    # Cuándo ARCA confirmó por última vez que FactuMov puede emitir por este CUIT.
    # Timestamp y no booleano, por lo mismo que `User.email_confirmed_at`: el "cuándo" es lo
    # que quiere la UI ("verificada hace 3 meses") y cualquier consulta de soporte. La
    # delegación se puede revocar del lado de ARCA sin avisarnos, así que este campo dice
    # "esto era verdad en esta fecha" y no "esto es verdad".
    #
    # Vive acá y no en `User` porque un usuario puede tener varios CUIT y cada uno se delega
    # por separado.
    delegation_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Cuándo el usuario dijo "ya delegué" sin que ARCA todavía lo confirme. `None` = no avisó.
    #
    # Existe porque delegar tiene **dos** partes y la segunda es nuestra: el contribuyente
    # designa a FactuMov como representante, y después FactuMov tiene que aceptar esa
    # designación en `adminrel/pending.aspx`, a mano y con Clave Fiscal. Hasta que eso pasa,
    # WSFE contesta exactamente lo mismo que si el usuario no hubiera hecho nada — el código
    # 600 no distingue "no delegó" de "delegó y está pendiente de aceptación".
    #
    # Esa es toda la razón de esta columna: es la única información que separa esos dos
    # estados, y no puede salir de ARCA porque ARCA no la publica. Sale del usuario, que es el
    # único que sabe si ya hizo su parte. Sin ella la pantalla le dice a quien ya delegó que
    # vaya a delegar, o sea que le manda a rehacer un trámite que hizo bien.
    #
    # Timestamp y no booleano, como las otras tres del proyecto: el "cuándo" es lo que la
    # pantalla muestra ("nos avisaste hace 2 horas") y lo que acota el reenvío del aviso.
    delegation_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # El token del link que el mail al operador le pone abajo de las instrucciones, para que
    # pueda avisar que ya hizo los dos pasos en ARCA sin esperar al barrido de los 15 minutos.
    #
    # Guardado como SHA-256, igual que el de sesión y el de confirmación de mail — ver
    # `services/security.py`. Va acá y no en una tabla propia, al revés que `email_confirmations`:
    # aquella existe porque el reenvío emite un token nuevo sin invalidar el anterior y hacen
    # falta varios vivos a la vez. Acá el mail sale **una sola vez por identidad**, así que nunca
    # hay más de un link dando vueltas y una fila aparte sería una fila por columna.
    #
    # Vive exactamente lo que vive la espera: se emite con el aviso del usuario y se borra al
    # verificar. Un link que sigue andando después de que la delegación quedó verificada es una
    # credencial sin dueño que puede gastar cuota de ARCA para siempre.
    #
    # `unique` por lo mismo que en las otras tres tablas de tokens: es además el índice por el
    # que se busca. Postgres deja repetir el NULL, que es lo que tienen casi todas las filas.
    delegation_claim_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)

    invoice_templates: Mapped[list["InvoiceTemplate"]] = relationship(
        back_populates="fiscal_identity", passive_deletes="all"
    )
