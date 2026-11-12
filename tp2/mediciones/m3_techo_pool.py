import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from comun import LENTO, crear, esperar_cola_vacia, guardar, pedir

SERIE = sys.argv[1] if len(sys.argv) > 1 else "io"
NS = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "10,50,100,500,1000").split(",")]


def pedido():
    if SERIE == "io":
        return {"tipo": "descargar", "urls": [f"{LENTO}/demora/1000"], "timeout": 600}
    if SERIE == "esperar":
        return {"tipo": "esperar", "segundos": 1, "timeout": 600}
    return {"tipo": "hashear", "texto": "techo", "iteraciones": 2_000_000, "timeout": 600}


def paso(n):
    p = pedido()
    inicio = time.perf_counter()
    with ThreadPoolExecutor(32) as hilos:
        ids = set(hilos.map(lambda _: crear(p), range(n)))
    esperar_cola_vacia()
    total = time.perf_counter() - inicio
    tareas = [t for t in pedir("GET", "/tareas?limite=1000") if t["id"] in ids]
    espera = [t["espera"] for t in tareas]
    duracion = [t["duracion"] for t in tareas]
    estados = sorted({t["estado"] for t in tareas})
    return n, total, n / total, statistics.mean(espera), max(espera), statistics.mean(duracion), estados


def main():
    est = pedir("GET", "/estadisticas")
    lineas = [f"serie {SERIE}, workers {est['workers_total']}", ""]
    lineas.append(f"{'N':>6} {'total s':>8} {'tareas/s':>9} {'espera prom':>12} {'espera max':>11} {'ejec prom':>10}  estados")
    for n in NS:
        n, total, por_s, esp_prom, esp_max, ejec, estados = paso(n)
        lineas.append(f"{n:>6} {total:>8.2f} {por_s:>9.1f} {esp_prom:>12.2f} {esp_max:>11.2f} {ejec:>10.2f}  {','.join(estados)}")
        print(lineas[-1])
        time.sleep(1)
    guardar(f"m3_{SERIE}_w{est['workers_total']}", lineas)


main()
