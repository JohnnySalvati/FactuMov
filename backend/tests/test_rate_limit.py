"""Tests de `services/rate_limit.py`.

El reloj se inyecta en vez de dormir: la ventana de los límites reales es de una hora, y un
test que la esperara de verdad no sería un test.
"""

import threading

import pytest

from factumov.services.rate_limit import RateLimiter


@pytest.fixture
def clock():
    """Reloj manual: `clock[0] += n` adelanta n segundos.

    Se le pasa al limitador por el parámetro `clock`. Parchear `time.monotonic` habría
    movido el reloj de todo el proceso, pytest incluido.
    """
    return [1000.0]


def limiter_with(clock, **kwargs):
    return RateLimiter(clock=lambda: clock[0], **kwargs)


def test_allows_up_to_the_limit(clock):
    limiter = limiter_with(clock, limit=3, window_seconds=60)

    assert [limiter.check("ana") for _ in range(3)] == [None, None, None]


def test_blocks_past_the_limit(clock):
    limiter = limiter_with(clock, limit=3, window_seconds=60)
    for _ in range(3):
        limiter.check("ana")

    assert limiter.check("ana") is not None


def test_says_how_long_is_left(clock):
    limiter = limiter_with(clock, limit=1, window_seconds=60)
    limiter.check("ana")
    clock[0] += 20

    assert limiter.check("ana") == pytest.approx(40)


def test_keys_do_not_share_a_counter(clock):
    limiter = limiter_with(clock, limit=1, window_seconds=60)
    limiter.check("ana")

    assert limiter.check("bruno") is None


def test_the_window_reopens(clock):
    limiter = limiter_with(clock, limit=1, window_seconds=60)
    limiter.check("ana")
    assert limiter.check("ana") is not None

    clock[0] += 60

    assert limiter.check("ana") is None


def test_expired_keys_are_dropped(clock):
    """Sin la poda, el dict crece con el tráfico y no se vacía nunca."""
    limiter = limiter_with(clock, limit=1, window_seconds=60)
    limiter.check("ana")
    clock[0] += 60
    limiter.check("bruno")

    assert list(limiter._windows) == ["bruno"]


def test_reset_clears_everything(clock):
    limiter = limiter_with(clock, limit=1, window_seconds=60)
    limiter.check("ana")

    limiter.reset()

    assert limiter.check("ana") is None


def test_the_counter_does_not_lose_hits_under_concurrency():
    """Los endpoints son `def`, así que FastAPI los corre en el threadpool.

    Sin el candado, dos hilos leen el mismo contador y uno pisa el incremento del otro: el
    límite se afloja justo bajo la carga que tendría que frenar. Con 8 hilos × 50 intentos
    tienen que pasar exactamente `limit`.
    """
    limiter = RateLimiter(limit=100, window_seconds=60)
    allowed = []

    def hammer():
        for _ in range(50):
            if limiter.check("ana") is None:
                allowed.append(1)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(allowed) == 100
