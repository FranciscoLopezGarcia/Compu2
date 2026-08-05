import os

import procfs
from analizadores.base import AnalizadorBase


class AnalizadorThreads(AnalizadorBase):
    NOMBRE = "threads"

    def __init__(self, *args):
        super().__init__(*args)
        self._prev = {}
        self._prev_total = None
        self._ncpus = os.cpu_count() or 1

    def extraer(self, pids):
        cpu = procfs.leer_cpu_global()
        total = sum(cpu.values())
        delta_total = (total - self._prev_total) if self._prev_total else None
        self._prev_total = total

        procesos = {}
        nuevos = {}
        for pid in pids:
            hilos = []
            for tid in procfs.listar_tids(pid):
                try:
                    st = procfs.leer_stat(pid, tid)
                    status = procfs.leer_status(pid, tid)
                except (OSError, ValueError):
                    continue
                jif = st["utime"] + st["stime"]
                nuevos[(pid, tid)] = jif
                if delta_total and (pid, tid) in self._prev:
                    pct = (jif - self._prev[(pid, tid)]) / delta_total * 100 * self._ncpus
                else:
                    pct = 0.0
                hilos.append({
                    "tid": tid,
                    "nombre": st["comm"],
                    "estado": st["state"],
                    "cpu": round(pct, 1),
                    "ctx_vol": int(status.get("voluntary_ctxt_switches", 0)),
                    "ctx_invol": int(status.get("nonvoluntary_ctxt_switches", 0)),
                })
            if hilos:
                procesos[pid] = hilos
        self._prev = nuevos
        return procesos
