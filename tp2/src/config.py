import os
from pathlib import Path


class Config:
    def __init__(self, workers=None, procesos=None, tamano_cola=None,
                 timeout_defecto=None, limite_apagado=None, dir_volcados=None):
        self.workers = workers or int(os.environ.get("WORKERS", 8))
        self.procesos = procesos or int(os.environ.get("PROCESOS", min(4, os.cpu_count() or 1)))
        self.tamano_cola = tamano_cola or int(os.environ.get("TAMANO_COLA", 1000))
        self.timeout_defecto = timeout_defecto or float(os.environ.get("TIMEOUT_DEFECTO", 60))
        self.limite_apagado = limite_apagado or float(os.environ.get("LIMITE_APAGADO", 10))
        self.dir_volcados = Path(dir_volcados or os.environ.get("DIR_VOLCADOS", "volcados"))
