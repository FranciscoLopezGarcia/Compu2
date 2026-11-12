import asyncio
import time

import httpx
import pytest

from src.api import crear_app
from src.config import Config


@pytest.fixture
async def api(tmp_path):
    config = Config(workers=2, procesos=2, tamano_cola=5, timeout_defecto=10,
                    limite_apagado=1, dir_volcados=tmp_path)
    app = crear_app(config)
    async with app.router.lifespan_context(app):
        transporte = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://test") as cliente:
            cliente.app = app
            yield cliente


async def crear(cliente, **pedido):
    r = await cliente.post("/tareas", json=pedido)
    assert r.status_code == 202, r.text
    return r.json()["id"]


async def esperar_estado(cliente, id, *estados, limite=5):
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        t = (await cliente.get(f"/tareas/{id}")).json()
        if t["estado"] in estados:
            return t
        await asyncio.sleep(0.02)
    raise AssertionError(f"la tarea {id} no llego a {estados}: {t['estado']}")
