import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, HttpUrl


class Estado(str, Enum):
    PENDIENTE = "pendiente"
    EJECUTANDO = "ejecutando"
    COMPLETADA = "completada"
    FALLIDA = "fallida"
    CANCELADA = "cancelada"


FINALES = (Estado.COMPLETADA, Estado.FALLIDA, Estado.CANCELADA)


def ahora():
    return datetime.now(timezone.utc)


class PedidoBase(BaseModel):
    timeout: float | None = Field(default=None, gt=0, le=86400)


class PedidoDescargar(PedidoBase):
    tipo: Literal["descargar"]
    urls: list[HttpUrl] = Field(min_length=1, max_length=500)
    concurrencia: int = Field(default=20, ge=1, le=500)


class PedidoHashear(PedidoBase):
    tipo: Literal["hashear"]
    texto: str = Field(max_length=10000)
    iteraciones: int = Field(gt=0, le=2_000_000_000)
    bloqueante: bool = False


class PedidoEsperar(PedidoBase):
    tipo: Literal["esperar"]
    segundos: float = Field(ge=0, le=86400)


PedidoTarea = Annotated[
    Union[PedidoDescargar, PedidoHashear, PedidoEsperar],
    Field(discriminator="tipo"),
]


class Tarea:
    def __init__(self, id, tipo, parametros, timeout):
        self.id = id
        self.tipo = tipo
        self.parametros = parametros
        self.timeout = timeout
        self.estado = Estado.PENDIENTE
        self.resultado = None
        self.error = None
        self.worker = None
        self.creada = ahora()
        self.iniciada = None
        self.finalizada = None
        self.terminada = asyncio.Event()

    @property
    def final(self):
        return self.estado in FINALES

    @property
    def espera(self):
        if self.iniciada is None:
            return None
        return (self.iniciada - self.creada).total_seconds()

    @property
    def duracion(self):
        if self.iniciada is None or self.finalizada is None:
            return None
        return (self.finalizada - self.iniciada).total_seconds()

    def a_dict(self, completo=True):
        datos = {
            "id": self.id,
            "tipo": self.tipo,
            "estado": self.estado.value,
            "timeout": self.timeout,
            "error": self.error,
            "worker": self.worker,
            "creada": self.creada.isoformat(),
            "iniciada": self.iniciada.isoformat() if self.iniciada else None,
            "finalizada": self.finalizada.isoformat() if self.finalizada else None,
            "espera": self.espera,
            "duracion": self.duracion,
        }
        if completo:
            datos["parametros"] = self.parametros
            datos["resultado"] = self.resultado
        return datos
