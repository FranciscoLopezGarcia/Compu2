import asyncio
import hashlib
import signal

TRAMO = 200_000


def hash_iterado(datos, n):
    for _ in range(n):
        datos = hashlib.sha256(datos).digest()
    return datos


def ignorar_sigint():
    signal.signal(signal.SIGINT, signal.SIG_IGN)


async def hashear(pool, texto, iteraciones):
    loop = asyncio.get_running_loop()
    datos = texto.encode()
    hechas = 0
    while hechas < iteraciones:
        n = min(TRAMO, iteraciones - hechas)
        datos = await loop.run_in_executor(pool, hash_iterado, datos, n)
        hechas += n
    return {"hash": datos.hex(), "iteraciones": iteraciones}


async def hashear_bloqueando(texto, iteraciones):
    datos = hash_iterado(texto.encode(), iteraciones)
    return {"hash": datos.hex(), "iteraciones": iteraciones}
