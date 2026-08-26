import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from factumov.models.base import Base, TimestampMixin


class ArcaTicket(Base, TimestampMixin):
    """El ticket de acceso (TA) que WSAA devuelve para un servicio.

    Tabla y no el `ticket_arca.json` de Balance360. Allá es un proceso con un CUIT; acá
    hay un solo certificado —el de FactuMov— compartido por todos los usuarios y por N
    workers, así que el ticket pasa a ser un recurso común. Y WSAA **se niega a emitir uno
    nuevo mientras el anterior siga vigente**: dos workers pidiendo a la vez no obtienen
    dos tickets, obtienen uno y un error. Un archivo en el cwd no coordina eso; una fila
    con un lock, sí.

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
