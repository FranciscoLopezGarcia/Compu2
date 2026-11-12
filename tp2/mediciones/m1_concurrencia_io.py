import statistics
import sys
import time

from comun import LENTO, crear, esperar_fin, guardar

N = 20
DEMORA_MS = 500
REPETICIONES = 3


def correr(concurrencia):
    urls = [f"{LENTO}/demora/{DEMORA_MS}?n={i}" for i in range(N)]
    inicio = time.perf_counter()
    t = esperar_fin(crear({"tipo": "descargar", "urls": urls, "concurrencia": concurrencia}))
    cliente = time.perf_counter() - inicio
    errores = len([u for u in t["resultado"]["urls"] if "error" in u])
    return t["resultado"]["tiempo_total"], cliente, errores


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "internet":
        global LENTO
        LENTO = "https://example.com"
    lineas = [f"{N} descargas de {LENTO}/demora/{DEMORA_MS}", ""]
    totales = {1: [], N: []}
    for rep in range(REPETICIONES):
        for concurrencia in (1, N):
            servidor, cliente, errores = correr(concurrencia)
            totales[concurrencia].append(servidor)
            nombre = "secuencial" if concurrencia == 1 else "concurrente"
            lineas.append(f"rep {rep + 1} {nombre:<11} servidor {servidor:.3f} s  cliente {cliente:.3f} s  errores {errores}")
    sec = statistics.mean(totales[1])
    conc = statistics.mean(totales[N])
    lineas += ["", f"promedio secuencial  {sec:.3f} s", f"promedio concurrente {conc:.3f} s", f"speedup {sec / conc:.1f}x"]
    print("\n".join(lineas))
    guardar("m1", lineas)


main()
