import asyncio
import json

import httpx

from src.api import crear_app
from src.config import Config
from tests.conftest import crear, esperar_estado


async def vivas(api):
    return (await api.get("/estadisticas")).json()["corrutinas_vivas"]


async def test_cancelar_pendiente(api):
    for _ in range(2):
        await crear(api, tipo="esperar", segundos=2)
    id = await crear(api, tipo="esperar", segundos=2)
    r = await api.delete(f"/tareas/{id}")
    assert r.status_code == 200
    assert r.json()["estado"] == "cancelada"


async def test_cancelar_ejecutando_no_deja_corrutinas(api):
    antes = await vivas(api)
    id = await crear(api, tipo="esperar", segundos=30)
    await esperar_estado(api, id, "ejecutando")
    r = await api.delete(f"/tareas/{id}")
    assert r.json()["estado"] == "cancelada"
    assert await vivas(api) == antes


async def test_cancelar_hashear_en_el_pool(api):
    id = await crear(api, tipo="hashear", texto="x", iteraciones=500_000_000)
    await esperar_estado(api, id, "ejecutando")
    r = await api.delete(f"/tareas/{id}")
    assert r.json()["estado"] == "cancelada"


async def test_el_worker_sigue_vivo_despues_de_cancelar(api):
    id = await crear(api, tipo="esperar", segundos=30)
    await esperar_estado(api, id, "ejecutando")
    await api.delete(f"/tareas/{id}")
    otra = await crear(api, tipo="esperar", segundos=0)
    await esperar_estado(api, otra, "completada")
    assert (await api.get("/estadisticas")).json()["workers_total"] == 2


async def test_cancelar_a_mitad_de_descarga(tmp_path):
    async def lento(request):
        await asyncio.sleep(30)
        return httpx.Response(200, content=b"x")

    cliente_falso = httpx.AsyncClient(transport=httpx.MockTransport(lento))
    config = Config(workers=2, procesos=1, tamano_cola=5, timeout_defecto=10,
                    limite_apagado=1, dir_volcados=tmp_path)
    app = crear_app(config, cliente=cliente_falso)
    async with app.router.lifespan_context(app):
        transporte = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://test") as api:
            antes = await vivas(api)
            urls = [f"http://sitio.com/{i}" for i in range(10)]
            id = await crear(api, tipo="descargar", urls=urls)
            await esperar_estado(api, id, "ejecutando")
            await asyncio.sleep(0.2)
            assert await vivas(api) > antes
            r = await api.delete(f"/tareas/{id}")
            assert r.json()["estado"] == "cancelada"
            assert await vivas(api) == antes
    await cliente_falso.aclose()


async def test_apagado_guarda_el_json(tmp_path):
    config = Config(workers=1, procesos=1, tamano_cola=5, timeout_defecto=10,
                    limite_apagado=0.3, dir_volcados=tmp_path)
    app = crear_app(config)
    async with app.router.lifespan_context(app):
        transporte = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://test") as api:
            largo = await crear(api, tipo="esperar", segundos=30)
            await esperar_estado(api, largo, "ejecutando")
            await crear(api, tipo="esperar", segundos=30)
    archivos = list(tmp_path.glob("estado_*.json"))
    assert len(archivos) == 1
    datos = json.loads(archivos[0].read_text())
    assert datos["total"] == 2
    assert {t["estado"] for t in datos["tareas"]} == {"cancelada"}
