import json
import logging
from collections import Counter
from datetime import datetime

log = logging.getLogger("persistencia")


def volcar(tareas, directorio):
    directorio.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = directorio / f"estado_{marca}.json"
    with open(ruta, "w") as f:
        json.dump({"volcado": marca, "total": len(tareas), "tareas": tareas}, f, indent=2, ensure_ascii=False)
    log.info("estado guardado en %s (%d tareas)", ruta, len(tareas))
    return ruta


def avisar_previo(directorio):
    archivos = sorted(directorio.glob("estado_*.json"))
    if not archivos:
        log.info("no hay volcados previos en %s", directorio)
        return
    ultimo = archivos[-1]
    try:
        with open(ultimo) as f:
            datos = json.load(f)
        estados = Counter(t["estado"] for t in datos["tareas"])
        log.info("volcado previo: %s con %d tareas %s", ultimo.name, datos["total"], dict(estados))
    except (OSError, ValueError, KeyError) as e:
        log.warning("no pude leer el volcado %s: %s", ultimo.name, e)
