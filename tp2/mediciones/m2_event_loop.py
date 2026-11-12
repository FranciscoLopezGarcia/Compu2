import statistics
import sys
import threading
import time

from comun import crear, esperar_fin, guardar, pedir

ITERACIONES = int(sys.argv[1]) if len(sys.argv) > 1 else 15_000_000


def sondear(latencias, parar):
    while not parar.is_set():
        inicio = time.perf_counter()
        pedir("GET", "/tareas")
        latencias.append((inicio, time.perf_counter() - inicio))
        time.sleep(0.1)


def fase(nombre, bloqueante):
    latencias = []
    parar = threading.Event()
    hilo = threading.Thread(target=sondear, args=(latencias, parar))
    hilo.start()
    time.sleep(1)
    desde = time.perf_counter()
    pedido = {"tipo": "hashear", "texto": "medicion", "iteraciones": ITERACIONES, "bloqueante": bloqueante}
    t = esperar_fin(crear(pedido), intervalo=0.2)
    hasta = time.perf_counter()
    time.sleep(0.5)
    parar.set()
    hilo.join()

    durante = [lat * 1000 for inicio, lat in latencias if desde <= inicio <= hasta]
    antes = [lat * 1000 for inicio, lat in latencias if inicio < desde]
    return (f"{nombre:<14} hash de {t['duracion']:.2f} s | GET /tareas durante: {len(durante)} muestras, "
            f"promedio {statistics.mean(durante):.1f} ms, maximo {max(durante):.1f} ms "
            f"(sin carga: {statistics.mean(antes):.1f} ms)")


def main():
    lineas = [f"hashear de {ITERACIONES} iteraciones", ""]
    lineas.append(fase("en el loop", True))
    lineas.append(fase("con executor", False))
    print("\n".join(lineas))
    guardar("m2", lineas)


main()
