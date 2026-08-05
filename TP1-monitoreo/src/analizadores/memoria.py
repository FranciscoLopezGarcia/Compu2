import procfs
from analizadores.base import AnalizadorBase

CAMPOS_VM = ["VmSize", "VmRSS", "VmHWM", "VmData", "VmStk", "VmExe", "VmLib", "VmSwap"]


class AnalizadorMemoria(AnalizadorBase):
    NOMBRE = "memoria"

    def extraer(self, pids):
        procesos = {}
        for pid in pids:
            try:
                status = procfs.leer_status(pid)
                st = procfs.leer_stat(pid)
            except (OSError, ValueError):
                continue
            datos = {c: procfs.kb(status.get(c, "0")) for c in CAMPOS_VM}
            datos.update({
                "minflt": st["minflt"], "majflt": st["majflt"],
                "cminflt": st["cminflt"], "cmajflt": st["cmajflt"],
                "segmentos": procfs.leer_maps_agrupado(pid),
            })
            procesos[pid] = datos
        return procesos
