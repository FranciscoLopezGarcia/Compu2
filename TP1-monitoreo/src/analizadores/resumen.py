import os

import procfs
from analizadores.base import AnalizadorBase


class AnalizadorResumen(AnalizadorBase):
    NOMBRE = "resumen"

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
        nuevos_prev = {}
        for pid in pids:
            try:
                st = procfs.leer_stat(pid)
                status = procfs.leer_status(pid)
            except (OSError, ValueError):
                continue

            jif = st["utime"] + st["stime"]
            nuevos_prev[pid] = jif
            if delta_total and pid in self._prev:
                cpu_pct = (jif - self._prev[pid]) / delta_total * 100 * self._ncpus
            else:
                cpu_pct = 0.0

            uid = status.get("Uid", "0").split()[0]
            gid = status.get("Gid", "0").split()[0]
            procesos[pid] = {
                "pid": pid,
                "ppid": st["ppid"],
                "uid": uid,
                "gid": gid,
                "usuario": procfs.uid_a_usuario(uid),
                "estado": st["state"],
                "comando": procfs.leer_cmdline(pid),
                "comm": st["comm"],
                "cpu": round(cpu_pct, 1),
                "rss_kb": procfs.kb(status.get("VmRSS", "0")),
                "threads": int(status.get("Threads", st["num_threads"])),
            }
        self._prev = nuevos_prev
        return procesos
