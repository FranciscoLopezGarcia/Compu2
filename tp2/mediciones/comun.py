import json
import os
import time
import urllib.request
from pathlib import Path

API = os.environ.get("API", "http://localhost:8000")
LENTO = os.environ.get("LENTO", "http://lento:8001")
RESULTADOS = Path(__file__).parent / "resultados"


def pedir(metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(API + ruta, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def crear(pedido):
    return pedir("POST", "/tareas", pedido)["id"]


def esperar_fin(id, intervalo=0.05):
    while True:
        t = pedir("GET", f"/tareas/{id}")
        if t["estado"] in ("completada", "fallida", "cancelada"):
            return t
        time.sleep(intervalo)


def esperar_cola_vacia():
    while True:
        e = pedir("GET", "/estadisticas")
        if e["por_estado"]["pendiente"] == 0 and e["por_estado"]["ejecutando"] == 0:
            return
        time.sleep(0.1)


def guardar(nombre, lineas):
    RESULTADOS.mkdir(exist_ok=True)
    texto = "\n".join(lineas) + "\n"
    (RESULTADOS / f"{nombre}.txt").write_text(texto)
    print(f"\nguardado en mediciones/resultados/{nombre}.txt")
