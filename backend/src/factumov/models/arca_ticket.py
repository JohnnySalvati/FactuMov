import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from factumov.models.base import Base, TimestampMixin


class ArcaTicket(Base, TimestampMixin):
    """El ticket de acceso (TA) que WSAA devuelve para un servicio.

    Tabla y no el `ticket_arca.json` de Balance360. Allá es un proceso con un CUIT; acá
    hay un solo certificado —el de FactuMov— compartido por todos los usuarios y por N
    workers, así que el ticket pasa a ser un recurso común: dos que piden a la vez gastan
    dos veces la cuota de WSAA para quedarse con un solo ticket útil. Un archivo en el cwd
    no coordina eso; una fila con un lock, sí.

    Acá decía además que WSAA se niega a emitir un TA nuevo mientras el anterior siga
    vigente. El 2026-08-29, en producción, emitió uno — ver docs/arca.md → *El ticket viejo
    miente*. Todo lo demás de este docstring era independiente de aquello y sigue igual.

    No lleva `user_id`: el ticket es del certificado, no del contribuyente. A quién
    representa se decide después, en el `Auth.Cuit` de cada llamada a WSFE — y esa brecha
    entre el CUIT del certificado y el CUIT representado es exactamente lo que la
    delegación habilita.
    """

    __tablename__ = "arca_tickets"
    __table_args__ = (UniqueConstraint("env", "service", name="uq_arca_tickets_env_service"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # "homo" o "prod". Los dos entornos tienen certificados distintos y tickets distintos;
    # sin esta columna, cambiar de entorno reusaría un ticket que el otro no reconoce.
    env: Mapped[str] = mapped_column(String(4))
    service: Mapped[str] = mapped_column(String(50))
    # Text y no String(n): el token es un blob base64 de largo no documentado (~3 KB hoy) y
    # ARCA no promete un techo. Un varchar corto se rompería en producción y de golpe.
    token: Mapped[str] = mapped_column(Text)
    sign: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Cuándo lo emitió WSAA. No se deriva de `expires_at`: cuánto dura un TA lo decide ARCA y
    # no lo promete en ningún lado, así que restarle doce horas sería inventar un dato. Existe
    # para contestar la única pregunta que `expires_at` no contesta y de la que depende
    # `get_access_ticket(max_age=...)`: **de cuándo es la foto de las relaciones que este
    # ticket lleva adentro**. Un TA vigente puede ser, a la vez, viejo — ver *El ticket viejo
    # miente* en docs/arca.md.
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
