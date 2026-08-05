import time

import procfs
from analizadores.base import AnalizadorBase


class AnalizadorSistema(AnalizadorBase):
    NOMBRE = "sistema"

    def __init__(self, *args):
        super().__init__(*args)
        self._prev_cpu = None

    def extraer(self, pids):
        cpu = procfs.leer_cpu_global()
        pct = {}
        if self._prev_cpu:
            delta = {k: cpu[k] - self._prev_cpu.get(k, 0) for k in cpu}
            total = sum(delta.values()) or 1
            pct = {k: round(v / total * 100, 1) for k, v in delta.items()}
        self._prev_cpu = cpu

        estados = {}
        threads_totales = 0
        for pid in pids:
            try:
                st = procfs.leer_stat(pid)
            except (OSError, ValueError):
                continue
            estados[st["state"]] = estados.get(st["state"], 0) + 1
            threads_totales += st["num_threads"]

        return {
            "cpu_pct": pct,
            "loadavg": procfs.leer_loadavg(),
            "meminfo": procfs.leer_meminfo(),
            "procesos_total": len(pids),
            "por_estado": estados,
            "zombies": estados.get("Z", 0),
            "threads_totales": threads_totales,
            "uptime_s": procfs.leer_uptime(),
            "boot_time": procfs.leer_boot_time(),
            "hora": time.time(),
        }
