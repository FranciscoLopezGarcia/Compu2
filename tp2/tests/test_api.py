import hashlib

from tests.conftest import crear, esperar_estado


async def test_esperar_se_completa(api):
    id = await crear(api, tipo="esperar", segundos=0.1)
    t = await esperar_estado(api, id, "completada")
    assert t["resultado"] == {"durmio": 0.1}
    assert t["duracion"] >= 0.1


async def test_hashear_da_el_mismo_hash_que_hashlib(api):
    id = await crear(api, tipo="hashear", texto="hola", iteraciones=1000)
    t = await esperar_estado(api, id, "completada")
    datos = b"hola"
    for _ in range(1000):
        datos = hashlib.sha256(datos).digest()
    assert t["resultado"]["hash"] == datos.hex()


async def test_pedido_invalido(api):
    r = await api.post("/tareas", json={"tipo": "esperar", "segundos": -1})
    assert r.status_code == 422
    r = await api.post("/tareas", json={"tipo": "inventada"})
    assert r.status_code == 422
    r = await api.post("/tareas", json={"tipo": "descargar", "urls": []})
    assert r.status_code == 422


async def test_tarea_inexistente(api):
    assert (await api.get("/tareas/nada")).status_code == 404
    assert (await api.delete("/tareas/nada")).status_code == 404


async def test_listar_con_filtro(api):
    id = await crear(api, tipo="esperar", segundos=0)
    await esperar_estado(api, id, "completada")
    todas = (await api.get("/tareas")).json()
    assert len(todas) == 1
    assert (await api.get("/tareas?estado=completada")).json()[0]["id"] == id
    assert (await api.get("/tareas?estado=fallida")).json() == []
    assert (await api.get("/tareas?estado=cualquiera")).status_code == 422


async def test_timeout_marca_fallida(api):
    id = await crear(api, tipo="esperar", segundos=5, timeout=0.2)
    t = await esperar_estado(api, id, "fallida")
    assert "timeout" in t["error"]


async def test_cancelar_terminada_da_409(api):
    id = await crear(api, tipo="esperar", segundos=0)
    await esperar_estado(api, id, "completada")
    r = await api.delete(f"/tareas/{id}")
    assert r.status_code == 409


async def test_cola_llena_da_503(api):
    for _ in range(2):
        await crear(api, tipo="esperar", segundos=2)
    await esperar_estado(api, (await api.get("/tareas")).json()[0]["id"], "ejecutando")
    for _ in range(5):
        await crear(api, tipo="esperar", segundos=2)
    r = await api.post("/tareas", json={"tipo": "esperar", "segundos": 2})
    assert r.status_code == 503


async def test_estadisticas(api):
    id = await crear(api, tipo="esperar", segundos=0)
    await esperar_estado(api, id, "completada")
    e = (await api.get("/estadisticas")).json()
    assert e["total"] == 1
    assert e["por_estado"]["completada"] == 1
    assert e["workers_total"] == 2
    assert e["workers_ocupados"] == 0
