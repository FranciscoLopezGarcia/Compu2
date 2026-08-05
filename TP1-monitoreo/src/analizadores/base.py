import queue
import signal
import time


class AnalizadorBase:
    NOMBRE = "base"

    def __init__(self, q_pids, q_resultados, intervalo, verbose, apagando):
        self.q_pids = q_pids
        self.q_resultados = q_resultados
        self.intervalo = intervalo
        self.verbose = verbose
        self.apagando = apagando
        self.pids = []

    def extraer(self, pids):
        raise NotImplementedError

    def correr(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

        while not self.apagando.is_set():
            self._actualizar_pids()
            if not self.pids:
                time.sleep(0.1)
                continue
            if self.pids:
                t0 = time.monotonic()
                try:
                    datos = self.extraer(self.pids)
                except Exception as e:
                    datos = {"_error": repr(e)}
                self.q_resultados.put({
                    "seccion": self.NOMBRE,
                    "datos": datos,
                    "ts": time.time(),
                    "duracion_ms": round((time.monotonic() - t0) * 1000, 1),
                })
            restante = float(self.intervalo.value)
            while restante > 0 and not self.apagando.is_set():
                paso = min(0.2, restante)
                time.sleep(paso)
                restante -= paso

    def _actualizar_pids(self):
        try:
            while True:
                self.pids = self.q_pids.get_nowait()
        except queue.Empty:
            pass


def lanzar(clase, *args):
    clase(*args).correr()
