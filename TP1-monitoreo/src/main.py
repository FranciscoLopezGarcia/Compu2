import json
import os
import select
import sys
import time
from multiprocessing import Event, Manager, Pipe, Process, Queue, Value

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import senales as sen
from agregador import correr_agregador
from recolector import correr_recolector
from analizadores.base import lanzar
from analizadores.resumen import AnalizadorResumen
from analizadores.memoria import AnalizadorMemoria
from analizadores.fds import AnalizadorFds
from analizadores.threads import AnalizadorThreads
from analizadores.senales import AnalizadorSenales
from analizadores.scheduling import AnalizadorScheduling
from analizadores.sistema import AnalizadorSistema

ANALIZADORES = [AnalizadorResumen, AnalizadorMemoria, AnalizadorFds,
                AnalizadorThreads, AnalizadorSenales, AnalizadorScheduling,
                AnalizadorSistema]

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(RAIZ, "config.json")


def cargar_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def main(sin_tui=False, duracion=None):
    config = cargar_config()

    manager = Manager()
    snapshot = manager.dict()
    apagando = Event()
    q_resultados = Queue()
    queues_pids = [Queue(maxsize=10) for _ in ANALIZADORES]

    intervalos = {
        c.NOMBRE: Value("d", config["intervalos"][c.NOMBRE]) for c in ANALIZADORES
    }
    int_recolector = Value("d", config["intervalos"]["recolector"])
    verbose = Value("b", 0)

    lado_main, lado_display = Pipe()

    procesos = [Process(target=correr_recolector, name="recolector",
                        args=(queues_pids, int_recolector, apagando)),
                Process(target=correr_agregador, name="agregador",
                        args=(q_resultados, snapshot, apagando))]
    for clase, q in zip(ANALIZADORES, queues_pids):
        procesos.append(Process(
            target=lanzar, name=f"analizador-{clase.NOMBRE}",
            args=(clase, q, q_resultados, intervalos[clase.NOMBRE],
                  verbose, apagando)))

    if not sin_tui:
        from display import correr_display
        stdin_fd = os.dup(sys.stdin.fileno())
        procesos.append(Process(target=correr_display, name="display",
                                args=(snapshot, intervalos, apagando,
                                      lado_display, config, stdin_fd)))

    for p in procesos:
        p.start()

    pipe_senales = sen.instalar()
    inicio = time.monotonic()
    try:
        while not apagando.is_set():
            listo, _, _ = select.select([pipe_senales], [], [], 0.3)
            if listo:
                for byte in os.read(pipe_senales, 64):
                    atender_senal(bytes([byte]), snapshot, intervalos,
                                  verbose, lado_main, apagando)
            if not sin_tui and not procesos[-1].is_alive():
                apagando.set()
            if duracion and time.monotonic() - inicio > duracion:
                apagando.set()
    finally:
        apagar(procesos, apagando)


def atender_senal(b, snapshot, intervalos, verbose, lado_main, apagando):
    if b in (b"I", b"T"):
        apagando.set()
    elif b == b"H":
        try:
            nueva = cargar_config()
            for nombre, v in intervalos.items():
                v.value = float(nueva["intervalos"][nombre])
            lado_main.send(("aviso", "SIGHUP: config recargada"))
        except (OSError, ValueError, KeyError) as e:
            lado_main.send(("aviso", f"SIGHUP: error leyendo config: {e}"))
    elif b == b"1":
        nombre = f"dump_{int(time.time())}.json"
        with open(os.path.join(RAIZ, nombre), "w") as f:
            json.dump({k: v for k, v in snapshot.items()}, f,
                      indent=2, default=str)
        lado_main.send(("aviso", f"SIGUSR1: snapshot volcado a {nombre}"))
    elif b == b"2":
        verbose.value = 0 if verbose.value else 1
        estado = "ON" if verbose.value else "OFF"
        lado_main.send(("aviso", f"SIGUSR2: verbose {estado}"))
    elif b == b"W":
        lado_main.send(("repaint", None))


def apagar(procesos, apagando):
    apagando.set()
    for p in procesos:
        p.join(timeout=2)
    for p in procesos:
        if p.is_alive():
            p.terminate()
            p.join(timeout=1)


if __name__ == "__main__":
    sin_tui = "--sin-tui" in sys.argv
    duracion = None
    for arg in sys.argv[1:]:
        if arg.startswith("--segundos="):
            duracion = float(arg.split("=")[1])
    main(sin_tui=sin_tui, duracion=duracion)
