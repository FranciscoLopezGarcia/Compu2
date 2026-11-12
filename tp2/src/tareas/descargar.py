import asyncio
import time


async def bajar_una(cliente, url):
    inicio = time.perf_counter()
    try:
        tamano = 0
        async with cliente.stream("GET", url) as respuesta:
            async for bloque in respuesta.aiter_bytes():
                tamano += len(bloque)
        return {
            "url": url,
            "status": respuesta.status_code,
            "tamano": tamano,
            "tiempo": round(time.perf_counter() - inicio, 3),
        }
    except Exception as e:
        return {
            "url": url,
            "error": f"{type(e).__name__}: {e}",
            "tiempo": round(time.perf_counter() - inicio, 3),
        }


async def descargar(cliente, urls, concurrencia):
    semaforo = asyncio.Semaphore(concurrencia)

    async def con_limite(url):
        async with semaforo:
            return await bajar_una(cliente, url)

    inicio = time.perf_counter()
    async with asyncio.TaskGroup() as grupo:
        hijas = [grupo.create_task(con_limite(u)) for u in urls]
    resultados = [h.result() for h in hijas]

    return {
        "tiempo_total": round(time.perf_counter() - inicio, 3),
        "urls": resultados,
    }
