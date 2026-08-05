import procfs
from analizadores.base import AnalizadorBase


class AnalizadorFds(AnalizadorBase):
    NOMBRE = "fds"

    def extraer(self, pids):
        limite = 100 if self.verbose.value else 15
        procesos = {}
        for pid in pids:
            fds = procfs.listar_fds(pid)
            procesos[pid] = {
                "total": len(fds),
                "fds": fds[:limite],
                "por_tipo": self._contar_tipos(fds),
            }
        return procesos

    @staticmethod
    def _contar_tipos(fds):
        conteo = {}
        for _, _, tipo in fds:
            conteo[tipo] = conteo.get(tipo, 0) + 1
        return conteo
