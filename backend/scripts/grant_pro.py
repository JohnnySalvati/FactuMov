"""Deja una cuenta de FactuMov en Pro anual, sin pasar por Mercado Pago.

Es la puerta de `BillingProvider.MANUAL`: el anual pagado por transferencia, o una cuenta a la
que se le regala el plan. No hay endpoint para esto a propósito —un endpoint que escribe el
plan es un endpoint para hacerse Pro gratis—, así que lo corre quien tiene acceso a la base.
Qué escribe y qué rechaza está en `subscription.grant_manual`.

En producción, desde `~/FactuMov` en la VM:

    docker compose -f docker-compose.prod.yml exec app \\
        python scripts/grant_pro.py miguelsalvati@gmail.com

En desarrollo, desde `backend/`:

    uv run python scripts/grant_pro.py miguelsalvati@gmail.com

`--days` cambia el largo (365 por default, contados desde ahora) y `--dry-run` muestra cómo
quedaría la cuenta sin guardar nada.
"""

import argparse
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from factumov.crud import subscription as subscription_crud
from factumov.crud import user as user_crud
from factumov.database import SessionLocal
from factumov.exceptions import ManualGrantError
from factumov.models.subscription import Subscription
from factumov.services import subscription as subscription_service

_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")


def describe(subscription: Subscription | None) -> str:
    if subscription is None:
        return "sin fila de suscripción (Free)"
    plan = "Pro" if subscription_service.is_pro(subscription) else "Free"
    end = subscription.current_period_end.astimezone(_ARGENTINA).strftime("%d/%m/%Y %H:%M")
    provider = subscription.provider.value if subscription.provider else "sin proveedor"
    return f"{plan} · {subscription.status.value} · {provider} · hasta el {end}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("email", help="el mail con el que la cuenta entra a FactuMov")
    parser.add_argument("--days", type=int, default=365, help="cuántos días de Pro, desde ahora")
    parser.add_argument("--dry-run", action="store_true", help="mostrar sin guardar")
    args = parser.parse_args()

    if args.days <= 0:
        raise SystemExit("--days tiene que ser mayor que cero.")
    # Igual que el registro (`schemas/auth.py`), que guarda el mail en minúsculas.
    email = args.email.strip().lower()
    until = datetime.now(UTC) + timedelta(days=args.days)

    with SessionLocal() as db:
        user = user_crud.get_by_email(db, email)
        if user is None:
            raise SystemExit(f"No hay ninguna cuenta con el mail {email}.")

        print(f"Cuenta:  {user.email}")
        print(f"Antes:   {describe(subscription_crud.get_for_user(db, user.id))}")
        try:
            subscription = subscription_service.grant_manual(db, user.id, until)
        except ManualGrantError as error:
            raise SystemExit(f"No se cambió nada: {error}") from None
        print(f"Después: {describe(subscription)}")

        if args.dry_run:
            db.rollback()
            print("--dry-run: no se guardó nada.")
            return
        db.commit()
        print("Listo.")


if __name__ == "__main__":
    main()
