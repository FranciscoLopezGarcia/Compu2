import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query

from src import persistencia
from src.config import Config
from src.gestor import Apagandose, ColaLlena, Gestor
from src.modelos import Estado, PedidoTarea
from src.tareas.hashear import ignorar_sigint

log = logging.getLogger("api")


def crear_app(config=None, cliente=None):
    config = config or Config()

    @asynccontextmanager
    async def lifespan(app):
        persistencia.avisar_previo(config.dir_volcados)
        http = cliente or httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=500),
        )
        pool = ProcessPoolExecutor(
            max_workers=config.procesos,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=ignorar_sigint,
        )
        gestor = Gestor(config, http, pool)
        gestor.iniciar()
        app.state.gestor = gestor
        yield
        log.info("cerrando el servidor")
        await gestor.apagar()
        await asyncio.to_thread(pool.shutdown, True, cancel_futures=True)
        if cliente is None:
            await http.aclose()
        tareas = [t.a_dict() for t in gestor.tareas.values()]
        await asyncio.to_thread(persistencia.volcar, tareas, config.dir_volcados)

    app = FastAPI(title="Plataforma de tareas", lifespan=lifespan)

    def buscar(id):
        tarea = app.state.gestor.tareas.get(id)
        if tarea is None:
            raise HTTPException(404, "no existe esa tarea")
        return tarea

    @app.post("/tareas", status_code=202)
    async def crear_tarea(pedido: PedidoTarea):
        parametros = pedido.model_dump(mode="json", exclude={"tipo", "timeout"})
        try:
            tarea = app.state.gestor.encolar(pedido.tipo, parametros, pedido.timeout)
        except ColaLlena:
            raise HTTPException(503, "la cola esta llena", headers={"Retry-After": "1"})
        except Apagandose:
            raise HTTPException(503, "el servidor se esta apagando")
        return {"id": tarea.id, "estado": tarea.estado.value}

    @app.get("/tareas")
    async def listar_tareas(estado: Estado | None = None, limite: int = Query(100, ge=1, le=1000)):
        tareas = list(app.state.gestor.tareas.values())
        if estado is not None:
            tareas = [t for t in tareas if t.estado == estado]
        return [t.a_dict(completo=False) for t in tareas[-limite:]]

    @app.get("/tareas/{id}")
    async def ver_tarea(id: str):
        return buscar(id).a_dict()

    @app.delete("/tareas/{id}")
    async def cancelar_tarea(id: str):
        tarea = buscar(id)
        if tarea.final:
            raise HTTPException(409, f"la tarea ya termino ({tarea.estado.value})")
        await app.state.gestor.cancelar(tarea)
        return tarea.a_dict()

    @app.get("/estadisticas")
    async def estadisticas():
        return app.state.gestor.estadisticas()

    return app


app = crear_app()
