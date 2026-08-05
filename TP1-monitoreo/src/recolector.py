import signal
import time

import procfs


def correr_recolector(queues_pids, intervalo, apagando):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while not apagando.is_set():
        pids = procfs.listar_pids()
        for q in queues_pids:
            q.put(pids)
        restante = float(intervalo.value)
        while restante > 0 and not apagando.is_set():
            time.sleep(min(0.2, restante))
            restante -= 0.2
