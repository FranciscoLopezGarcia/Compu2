import queue
import signal


def correr_agregador(q_resultados, snapshot, apagando):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while not apagando.is_set():
        try:
            msg = q_resultados.get(timeout=0.3)
        except queue.Empty:
            continue

        seccion = msg["seccion"]
        datos = msg["datos"]

        if seccion == "sistema":
            datos = dict(datos)
            datos["top_cpu"], datos["top_rss"] = _derivar_top3(snapshot)

        snapshot[seccion] = {
            "datos": datos,
            "ts": msg["ts"],
            "duracion_ms": msg.get("duracion_ms"),
        }


def _derivar_top3(snapshot):
    resumen = snapshot.get("resumen")
    if not resumen:
        return [], []
    procesos = list(resumen["datos"].values())
    top_cpu = sorted(procesos, key=lambda p: p["cpu"], reverse=True)[:3]
    top_rss = sorted(procesos, key=lambda p: p["rss_kb"], reverse=True)[:3]
    clave = lambda p: (p["pid"], p["comm"], p["cpu"], p["rss_kb"])
    return [clave(p) for p in top_cpu], [clave(p) for p in top_rss]
