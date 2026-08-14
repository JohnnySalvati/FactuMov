from psycopg.errors import Error, ForeignKeyViolation, UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from factumov.exceptions import DuplicateError, InUseError


def db_flush(db: Session, exception_map: dict[str, type[Exception]]) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        orig = exc.orig
        if isinstance(orig, Error):
            constraint_name = orig.diag.constraint_name
            if constraint_name:
                exc_to_raise = exception_map.get(constraint_name)
                if exc_to_raise:
                    raise exc_to_raise(str(exc)) from exc
        if isinstance(exc.orig, UniqueViolation):
            raise DuplicateError(str(exc)) from exc
        elif isinstance(exc.orig, ForeignKeyViolation):
            raise InUseError(str(exc)) from exc
        raise
