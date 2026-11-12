import asyncio
import logging
import uuid
from collections import Counter
from statistics import mean

from src.modelos import Estado, Tarea, ahora
from src.tareas import descargar, esperar, hashear

log = logging.getLogger("gestor")


class ColaLlena(Exception):
    pass


class Apagandose(Exception):
    pass


class Gestor:
    def __init__(self, config, cliente, pool):
        self.config = config
        self.cliente = cliente
        self.pool = pool
        self.tareas = {}
        self.cola = asyncio.Queue(maxsize=config.tamano_cola)
        self.workers = []
        self.en_curso = {}
        self.aceptando = True

    def iniciar(self):
        for n in range(self.config.workers):
            self.workers.append(asyncio.create_task(self.worker(n)))
        log.info("%d workers listos", self.config.workers)

    def encolar(self, tipo, parametros, timeout):
        if not self.aceptando:
            raise Apagandose()
        tarea = Tarea(uuid.uuid4().hex, tipo, parametros, timeout or self.config.timeout_defecto)
        try:
            self.cola.put_nowait(tarea)
        except asyncio.QueueFull:
            raise ColaLlena()
        self.tareas[tarea.id] = tarea
        return tarea

    async def cancelar(self, tarea, motivo="cancelada por el usuario"):
        if tarea.estado == Estado.PENDIENTE:
            self.finalizar(tarea, Estado.CANCELADA, error=motivo)
        elif tarea.estado == Estado.EJECUTANDO:
            tarea.error = motivo
            self.en_curso[tarea.id].cancel()
            await tarea.terminada.wait()

    def estadisticas(self):
        tareas = list(self.tareas.values())
        por_estado = Counter(t.estado for t in tareas)
        ejecutadas = [t for t in tareas if t.duracion is not None]
        por_tipo = {}
        for t in ejecutadas:
            por_tipo.setdefault(t.tipo, []).append(t.duracion)
        esperas = [t.espera for t in tareas if t.espera is not None]
        return {
            "total": len(tareas),
            "por_estado": {e.value: por_estado[e] for e in Estado},
            "espera_promedio": mean(esperas) if esperas else None,
            "duracion_promedio": mean(t.duracion for t in ejecutadas) if ejecutadas else None,
            "duracion_promedio_por_tipo": {k: mean(v) for k, v in por_tipo.items()},
            "workers_total": len(self.workers),
            "workers_ocupados": len(self.en_curso),
            "cola_en_espera": self.cola.qsize(),
            "cola_capacidad": self.cola.maxsize,
            "corrutinas_vivas": len(asyncio.all_tasks()),
            "aceptando_tareas": self.aceptando,
        }

    async def worker(self, n):
        while True:
            tarea = await self.cola.get()
            try:
                if tarea.estado == Estado.PENDIENTE:
                    await self.ejecutar(tarea, n)
            except Exception:
                log.exception("error inesperado en el worker %d", n)
                if not tarea.final:
                    self.finalizar(tarea, Estado.FALLIDA, error="error interno del worker")
            finally:
                self.cola.task_done()

    async def ejecutar(self, tarea, n):
        tarea.estado = Estado.EJECUTANDO
        tarea.iniciada = ahora()
        tarea.worker = n
        hija = asyncio.create_task(self.correr(tarea))
        self.en_curso[tarea.id] = hija
        await asyncio.wait({hija})
        del self.en_curso[tarea.id]

        if hija.cancelled():
            self.finalizar(tarea, Estado.CANCELADA, error=tarea.error or "cancelada")
        elif isinstance(hija.exception(), TimeoutError):
            self.finalizar(tarea, Estado.FALLIDA, error=f"timeout: paso de los {tarea.timeout} s")
        elif hija.exception() is not None:
            e = hija.exception()
            self.finalizar(tarea, Estado.FALLIDA, error=f"{type(e).__name__}: {e}")
        else:
            self.finalizar(tarea, Estado.COMPLETADA, resultado=hija.result())

    async def correr(self, tarea):
        async with asyncio.timeout(tarea.timeout):
            p = tarea.parametros
            if tarea.tipo == "esperar":
                return await esperar.esperar(p["segundos"])
            if tarea.tipo == "descargar":
                return await descargar.descargar(self.cliente, p["urls"], p["concurrencia"])
            if p["bloqueante"]:
                return await hashear.hashear_bloqueando(p["texto"], p["iteraciones"])
            return await hashear.hashear(self.pool, p["texto"], p["iteraciones"])

    def finalizar(self, tarea, estado, resultado=None, error=None):
        tarea.estado = estado
        tarea.resultado = resultado
        tarea.error = error
        tarea.finalizada = ahora()
        tarea.terminada.set()

    async def apagar(self):
        self.aceptando = False
        pendientes = 0
        for t in self.tareas.values():
            if t.estado == Estado.PENDIENTE:
                self.finalizar(t, Estado.CANCELADA, error="cancelada por el apagado del servidor")
                pendientes += 1

        en_curso = dict(self.en_curso)
        log.info("apagando: %d pendientes canceladas, esperando %d en curso", pendientes, len(en_curso))
        if en_curso:
            _, sobran = await asyncio.wait(en_curso.values(), timeout=self.config.limite_apagado)
            for id, hija in en_curso.items():
                if hija in sobran:
                    self.tareas[id].error = "cancelada por el apagado del servidor (se acabo el tiempo)"
                    hija.cancel()
            if sobran:
                await asyncio.wait(sobran)

        for w in self.workers:
            w.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
