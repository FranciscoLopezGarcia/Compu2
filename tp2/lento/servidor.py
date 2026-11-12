import asyncio

from fastapi import FastAPI, Response

app = FastAPI()


@app.get("/demora/{ms}")
async def demora(ms: int):
    await asyncio.sleep(ms / 1000)
    return Response(b"x" * 50000, media_type="application/octet-stream")
