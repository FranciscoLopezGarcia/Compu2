import procfs
from analizadores.base import AnalizadorBase

MASCARAS = ["SigBlk", "SigIgn", "SigCgt", "SigPnd", "ShdPnd"]


class AnalizadorSenales(AnalizadorBase):
    NOMBRE = "senales"

    def extraer(self, pids):
        procesos = {}
        for pid in pids:
            try:
                status = procfs.leer_status(pid)
            except (OSError, ValueError):
                continue
            procesos[pid] = {
                m: procfs.decodificar_mascara(status.get(m, "0"))
                for m in MASCARAS
            }
        return procesos
