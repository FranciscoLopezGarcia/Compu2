import asyncio


async def esperar(segundos):
    await asyncio.sleep(segundos)
    return {"durmio": segundos}
