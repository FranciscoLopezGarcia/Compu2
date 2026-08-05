import procfs
from analizadores.base import AnalizadorBase


class AnalizadorScheduling(AnalizadorBase):
    NOMBRE = "scheduling"

    def extraer(self, pids):
        procesos = {}
        for pid in pids:
            try:
                st = procfs.leer_stat(pid)
                status = procfs.leer_status(pid)
            except (OSError, ValueError):
                continue
            procesos[pid] = {
                "nice": st["nice"],
                "priority": st["priority"],
                "policy": procfs.nombre_policy(st["policy"]),
                "rt_priority": st["rt_priority"],
                "affinity": status.get("Cpus_allowed_list", "?"),
                "ctx_vol": int(status.get("voluntary_ctxt_switches", 0)),
                "ctx_invol": int(status.get("nonvoluntary_ctxt_switches", 0)),
                "utime": st["utime"],
                "stime": st["stime"],
                "sid": st["sid"],
                "pgid": st["pgid"],
            }
        return procesos
