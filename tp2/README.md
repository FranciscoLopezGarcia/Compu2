# TP2: Plataforma de tareas distribuidas

Servicio HTTP donde un cliente manda trabajos, el servidor los pone en una cola y un
pool de workers los ejecuta en paralelo. El cliente puede consultar el estado y el
resultado, y cancelar lo que no terminó. Está hecho con FastAPI, `asyncio` y
`ProcessPoolExecutor`, sin ningún framework de colas.

**Contenido:** 1. [Uso](#1-uso) · 2. [Arquitectura](#2-arquitectura) · 3. [Estructura del código](#3-estructura-del-código) · 4. [Decisiones de diseño](#4-decisiones-de-diseño) · 5. [Mediciones](#5-mediciones) · 6. [Conceptos del curso](#6-conceptos-del-curso-aplicados) · 7. [Limitaciones](#7-limitaciones-conocidas) · 8. [Lo que aprendí](#8-lo-que-aprendí)

## 1. Uso

### Levantar

```bash
docker compose up --build
```

Eso levanta dos servicios:

- `api` en `http://localhost:8000` (documentación interactiva en `/docs`).
- `lento` en `http://localhost:8001`, un servidor de prueba que responde después de una
  demora. Sirve para las mediciones sin depender de internet.

Para apagarlo con orden (guarda el estado en un JSON): `Ctrl+C` o `docker compose stop`.

### Tipos de tarea

| Tipo | Naturaleza | Parámetros | Qué hace |
|---|---|---|---|
| `descargar` | I/O | `urls`, `concurrencia` (opcional, 20 por defecto) | Baja las URLs a la vez y devuelve status, tamaño y tiempo de cada una. Con `concurrencia: 1` es secuencial |
| `hashear` | CPU | `texto`, `iteraciones` | SHA-256 aplicado N veces, en otro proceso |
| `esperar` | I/O simulado | `segundos` | Duerme con `asyncio.sleep`. Sirve para probar cancelación y timeouts |

Todos aceptan un `timeout` opcional en segundos. `hashear` acepta además
`bloqueante: true`, que corre el hash dentro del event loop. Existe solo para la
medición 2 y congela la API a propósito.

### Ejemplos con curl

```bash
curl -X POST localhost:8000/tareas -H "Content-Type: application/json" \
  -d '{"tipo": "esperar", "segundos": 5}'

curl -X POST localhost:8000/tareas -H "Content-Type: application/json" \
  -d '{"tipo": "hashear", "texto": "hola", "iteraciones": 1000000}'

curl -X POST localhost:8000/tareas -H "Content-Type: application/json" \
  -d '{"tipo": "descargar", "urls": ["https://example.com", "https://www.python.org"]}'

curl -X POST localhost:8000/tareas -H "Content-Type: application/json" \
  -d '{"tipo": "esperar", "segundos": 30, "timeout": 2}'

curl localhost:8000/tareas
curl "localhost:8000/tareas?estado=ejecutando"
curl localhost:8000/tareas/<id>
curl -X DELETE localhost:8000/tareas/<id>
curl localhost:8000/estadisticas
```

El `POST` responde enseguida con el id y el estado inicial:

```json
{"id": "9f2c0b7e1a4d4c0e8b6f5a2d3c1e7a90", "estado": "pendiente"}
```

### Códigos de respuesta

| Endpoint | Códigos |
|---|---|
| `POST /tareas` | `202` aceptada, `422` pedido inválido, `503` cola llena o servidor apagándose |
| `GET /tareas` | `200`, `422` si el estado no existe |
| `GET /tareas/{id}` | `200`, `404` |
| `DELETE /tareas/{id}` | `200` con la tarea ya cancelada, `404`, `409` si ya había terminado |
| `GET /estadisticas` | `200` |

### Estados

`pendiente` -> `ejecutando` -> `completada`, `fallida` o `cancelada`. Una tarea pasa a
`fallida` cuando lanza una excepción o cuando vence su timeout (el motivo queda en el
campo `error`).

### Configuración

Variables de entorno, con estos valores por defecto en `docker-compose.yml`:

| Variable | Defecto | Qué controla |
|---|---|---|
| `WORKERS` | 8 | Corrutinas que consumen de la cola |
| `PROCESOS` | 4 | Procesos del pool para `hashear` |
| `TAMANO_COLA` | 1000 | Tareas que pueden esperar. Si se llena, el `POST` da 503 |
| `TIMEOUT_DEFECTO` | 60 | Segundos, si el pedido no trae `timeout` |
| `LIMITE_APAGADO` | 10 | Segundos que se espera a las tareas en curso al apagar |

Ejemplo: `WORKERS=20 docker compose up --build`.

### Tests

```bash
docker compose run --rm --no-deps api pytest
```

Son 15 tests: endpoints, estados, timeout, cola llena, cancelación de una tarea
pendiente, de una `esperar`, de un `hashear` y de una descarga a mitad de camino (con
un transporte falso que nunca responde), y el volcado al apagar. Los de cancelación
comprueban que `corrutinas_vivas` vuelve al valor de antes, o sea que no queda ninguna
corrutina huérfana.

### Mediciones

Con la API levantada, desde la raíz del proyecto:

```bash
python3 mediciones/m1_concurrencia_io.py
python3 mediciones/m2_event_loop.py
python3 mediciones/m3_techo_pool.py io 10,50,100,500
python3 mediciones/m3_techo_pool.py esperar 10,100,1000
python3 mediciones/m3_techo_pool.py cpu 1,2,4,8,16,32
```

Usan solo la biblioteca estándar, así que no hace falta instalar nada en el host. Cada
una guarda su salida en `mediciones/resultados/`.

### Volcados del apagado

Al recibir SIGTERM o SIGINT se guarda `estado_<fecha>_<hora>.json` en el volumen
`volcados`:

```bash
docker compose exec api ls volcados
docker compose exec api cat volcados/estado_<fecha>_<hora>.json
```

## 2. Arquitectura

```
                          +-------------------------------------------+
 cliente --HTTP--> uvicorn |  FastAPI (src/api.py)                     |
                          |   POST /tareas -> Gestor.encolar()        |
                          |   GET, DELETE  -> Gestor (diccionario)    |
                          +---------------------+---------------------+
                                                | put_nowait
                                                v
                                     asyncio.Queue (maxsize)
                                                | get
              +---------------+-----------------+-----------------+
              v               v                                   v
          worker 0        worker 1          ...               worker N-1
              |  cada uno crea una Task hija por tarea
              v
         asyncio.timeout( tarea )
              |
     +--------+-----------------+----------------------+
     v                          v                      v
  esperar                   descargar               hashear
  asyncio.sleep             httpx + TaskGroup       run_in_executor
                            + Semaphore                  |
                                                         v
                                              ProcessPoolExecutor
                                              (procesos aparte, spawn)
```

Todo menos el pool vive en un solo proceso y un solo hilo: el del event loop.

### El viaje de una tarea

1. `POST /tareas`: pydantic valida el pedido (unión discriminada por `tipo`). Si es
   inválido, `422` y no entra a nada.
2. `Gestor.encolar()` crea la `Tarea`, la mete con `put_nowait` y responde `202` con el
   id. No espera a que se ejecute. Si la cola está llena, `503`.
3. Un worker libre saca la tarea con `await cola.get()`. Si la cancelaron mientras
   esperaba, la saltea.
4. El worker la pasa a `ejecutando` y arranca una `Task` hija con
   `asyncio.timeout(tarea.timeout)`. Espera a la hija con `asyncio.wait`.
5. Según el tipo: `esperar` duerme, `descargar` baja las URLs, `hashear` manda tramos al
   pool de procesos.
6. Cuando la hija termina, el worker mira cómo terminó y marca `completada`, `fallida`
   (excepción o timeout) o `cancelada`, y avisa con un `asyncio.Event`.
7. `GET /tareas/{id}` devuelve el estado y el resultado.

## 3. Estructura del código

```
src/
  main.py          arranque de uvicorn (con el guard de __main__)
  api.py           FastAPI: endpoints y ciclo de vida (lifespan)
  config.py        variables de entorno
  modelos.py       Estado, pedidos validados con pydantic, Tarea
  gestor.py        cola, workers, cancelación, estadísticas, apagado
  persistencia.py  volcado a JSON y aviso del volcado previo
  tareas/
    esperar.py     asyncio.sleep
    descargar.py   descargas concurrentes con httpx
    hashear.py     SHA-256 iterado en el pool de procesos
lento/servidor.py  servidor de prueba con demora, para las mediciones
mediciones/        m1, m2, m3 y sus resultados
tests/             pytest-asyncio
```

## 4. Decisiones de diseño

### ¿Por qué `asyncio.Queue` y no `queue.Queue`?

Porque los workers son corrutinas y todo corre en un solo hilo. Con
`asyncio.Queue`, `await cola.get()` suspende a la corrutina y le deja el hilo al event
loop, que mientras tanto atiende otros pedidos. `queue.Queue.get()` en cambio bloquea el
hilo entero, y como ese hilo es el del loop, se congelaría toda la API. Además
`queue.Queue` usa locks de threading pensados para varios hilos, que acá no hacen falta.

El `POST` usa `put_nowait` y no `await put`: nunca espera. Con `maxsize` la cola tiene un
tope, y si se llena el cliente recibe `503` con `Retry-After` en lugar de quedarse
colgado.

### ¿Cómo evito que una tarea CPU-bound congele la API?

El event loop tiene un solo hilo, y una corrutina solo le devuelve el control en un
`await`. Un `for` de millones de hashes no tiene ningún `await`, así que mientras corre
no se atiende a nadie: ni siquiera un `GET /tareas`. Con el flag `bloqueante` lo medí:
la API quedó muda durante todo el hash (medición 2).

La solución es `loop.run_in_executor` con un `ProcessPoolExecutor`: el cálculo corre en
otro proceso, y la corrutina que lo pidió queda suspendida en un `await` mientras el
loop sigue atendiendo. Uso procesos y no hilos por el GIL: dos hilos de Python no
ejecutan bytecode a la vez, así que un hilo no aceleraría el cálculo ni dejaría de
competir con el loop.

Cada `hashear` se parte en tramos de 200.000 iteraciones y se manda un tramo por vez.
Eso permite cancelar (ver abajo).

### ¿Cómo implementé la cancelación, y qué pasa con los recursos a medio usar?

- **Una Task hija por tarea.** `task.cancel()` corta una Task entera. Si la tarea
  corriera directo dentro del worker, un `DELETE` mataría al worker. Con una hija, se
  corta solo la hija y el worker sigue vivo. El worker espera con `asyncio.wait`, que no
  relanza lo que le pase a la hija.
- **`cancel()` inyecta un `CancelledError` en el `await` donde está suspendida la
  corrutina.** En ese `await` se libera lo que haya abierto. Por eso funciona sobre una
  tarea en ejecución y no solo sobre una pendiente.
- **`descargar`.** Usa `asyncio.TaskGroup`: si cancelan la tarea, el grupo cancela todas
  las descargas y no sale del bloque hasta que terminaron. Cada descarga usa
  `async with cliente.stream(...)`, que cierra la conexión al cancelarse. Los errores de
  red se atrapan con `except Exception`, y `CancelledError` hereda de `BaseException`,
  así que no queda tragado.
- **`hashear`.** Un proceso que ya está calculando no se puede interrumpir.
  Cancelar el `await` solo hace que dejemos de esperar el resultado. Por eso los tramos:
  entre uno y otro hay un `await` donde la cancelación entra, y lo máximo que se
  desperdicia es el tramo en curso. Lo verifiqué: después de cancelar un `hashear` de
  2.000 millones de iteraciones, los procesos del pool pasaron de 3 s de CPU cada 3 s a
  0 s.
- **Sin huérfanas.** `GET /estadisticas` devuelve `corrutinas_vivas`
  (`len(asyncio.all_tasks())`). Los tests cancelan una tarea en ejecución y una descarga
  a mitad de camino, y comprueban que ese número vuelve al de antes.
- **El `DELETE` responde con la tarea ya cancelada.** Espera un `asyncio.Event` que el
  worker activa al registrar el final.

El timeout usa `asyncio.timeout`, que cancela lo que esté adentro al vencer y lo convierte
en `TimeoutError`. Una cancelación de afuera sigue siendo `CancelledError`, así se
distinguen. El timeout cuenta desde que la tarea arranca, no desde que se encola.

### ¿Qué pasa si un worker lanza una excepción no capturada?

Lo que falla dentro de una tarea no llega al worker: queda dentro de la Task hija, y el
worker la lee después con `hija.exception()` y marca la tarea `fallida` con el tipo y el
mensaje del error. Además el cuerpo del worker tiene un `try/except Exception` que atrapa
cualquier error propio del código, lo registra con `log.exception` y marca la tarea como
fallida. Sin eso, la excepción terminaría la corrutina del worker en silencio, y el pool
quedaría con uno menos para siempre. `task_done()` va en `finally`.

### ¿Por qué no hace falta un Lock?

Todo el estado (el diccionario de tareas, `en_curso`, la cola) se toca desde corrutinas
que corren en el mismo hilo, y el event loop solo cambia de corrutina en un `await`. Un
bloque de código sin `await` es atómico para las demás. Por ejemplo, en `ejecutar()` las
líneas que pasan la tarea a `ejecutando` y la guardan en `en_curso` no pueden ser
interrumpidas a la mitad. Con threads el sistema operativo podría cortar entre dos
instrucciones cualesquiera y ahí sí haría falta un lock. Los procesos del pool no
comparten esta memoria: reciben una copia de los argumentos y devuelven una copia del
resultado.

### ¿Por qué `httpx` y no `requests` o `aiohttp`?

`requests` es bloqueante: dentro de una corrutina congelaría el loop. `httpx` tiene
cliente asíncrono con una interfaz casi igual a la de `requests` y soporta streaming. Se crea un solo `AsyncClient` para todo
el servicio, así se reutilizan las conexiones.

### Apagado ordenado

Uvicorn atrapa SIGTERM y SIGINT, deja de aceptar conexiones y ejecuta el cierre del
`lifespan`. Ahí:

1. `Gestor.apagar()` deja de aceptar tareas, cancela las pendientes y espera hasta
   `LIMITE_APAGADO` segundos a las que están corriendo. Las que no terminan se cancelan.
2. Se cancelan los workers y se espera a que terminen.
3. Se cierra el pool de procesos, en un thread (`asyncio.to_thread`), porque
   `shutdown(wait=True)` bloquea.
4. Se cierra el cliente HTTP y se escribe `estado_<fecha>_<hora>.json`.

Al arrancar se loguea el último volcado que haya. `stop_grace_period: 30s` en el
compose es mayor que `LIMITE_APAGADO`, para que Docker no mate el proceso antes de
guardar.

### El pool usa `spawn` y `main.py` tiene el guard

Con `spawn` cada proceso del pool nace limpio y vuelve a importar el módulo principal.
Sin `if __name__ == "__main__":` cada hijo levantaría otro servidor. Es lo que pide la
consigna para macOS y Windows, y acá lo uso también en Linux para que se comporte igual
en todos lados.

## 5. Mediciones

### Hardware

| | |
|-|-|
| CPU | Intel Core i7-10510U, 4 núcleos físicos / 8 hilos |
| RAM | 8 GB |
| Gobernador | `powersave`, frecuencia en reposo cerca de 900 MHz |
| SO | Linux 7.0, Python 3.12 |

Las mediciones se corrieron con la API levantada directamente con
`python -m src.main` y no dentro de Docker. Es un portátil con el procesador ahorrando
energía y con el navegador abierto, así que el cálculo de CPU sale varias veces más lento
que en las máquinas de escritorio (en un solo núcleo, 2 millones de hashes tardan unos
4 s). Los valores absolutos de CPU no son representativos. Lo que sí vale es la
comparación entre casos. Las salidas completas están en `mediciones/resultados/`.

### Medición 1: 20 descargas, secuencial contra concurrente

20 descargas al servidor `lento`, cada una con una demora de 500 ms. Tres corridas.

| | Tiempo del servidor |
|---|---|
| Secuencial (`concurrencia: 1`) | 10,18 s |
| Concurrente (`concurrencia: 20`) | 0,63 s |
| Speedup | 16,2x |

Secuencial es 20 x 0,5 s = 10 s: cada `await` espera a que termine el anterior.
Concurrente tarda poco más que la descarga más lenta (0,5 s), porque las 20 esperas
ocurren a la vez y el hilo se la pasa libre. El resto (0,13 s) es el costo de abrir las
conexiones y atender las respuestas en un solo hilo. No hay hilos ni procesos de por
medio: casi todo el tiempo era espera, no cálculo.

### Medición 2: el event loop bloqueado

Un `hashear` de 15.000.000 de iteraciones mientras un hilo del cliente hace
`GET /tareas` cada 0,1 s.

| Modo | Duración del hash | `GET /tareas` durante el hash | Sin carga |
|---|---|---|---|
| En el event loop (`bloqueante: true`) | 18,9 s | 1 respuesta, tardó 18.897 ms | 12,9 ms |
| Con `ProcessPoolExecutor` | 19,7 s | 193 respuestas, 2,7 ms de promedio, 6,4 ms de máximo | 6,5 ms |

Con el hash dentro del loop, un solo `GET` tardó lo que dura el cálculo, porque el loop
no pudo atender a nadie hasta que terminó. Con el executor, la API siguió respondiendo
en milisegundos. El hash en sí tarda lo mismo (o un poco más, por el costo de ir y venir
al otro proceso); lo que cambia es que ya no tapa a los demás.

### Medición 3: techo del pool

Se mandan N tareas juntas y se mide cuánto tardan en total. Cada fila es una corrida
independiente.

**I/O con 8 workers: `descargar` de una URL que tarda 1 s**

| N | Total (s) | Tareas/s | Espera promedio en cola (s) |
|---|---|---|---|
| 8 | 1,08 | 7,4 | 0,00 |
| 16 | 2,18 | 7,4 | 0,51 |
| 64 | 8,32 | 7,7 | 3,52 |
| 200 | 25,53 | 7,8 | 12,01 |

`esperar` de 1 s da lo mismo (8 tareas en 1,11 s; 200 en 25,11 s). Con 8 workers,
entran 8 tareas por segundo. El techo es la cantidad de workers: más tareas esperan en
la cola, y el tiempo total sube de a escalones (con 200 tareas, 25 x 1 s).

**I/O con 1000 workers**

`esperar` de 1 s:

| N | Total (s) | Tareas/s | Duración de cada tarea (s) |
|---|---|---|---|
| 100 | 1,20 | 83 | 1,00 |
| 1000 | 2,80 | 357 | 1,02 |
| 5000 | 9,51 | 526 | 1,02 |
| 10000 | 17,57 | 569 | 1,04 |

`descargar` de una URL de 1 s:

| N | Total (s) | Tareas/s | Duración de cada tarea (s) |
|---|---|---|---|
| 100 | 2,06 | 48,5 | 1,54 |
| 500 | 15,88 | 31,5 | 8,37 |
| 1000 | 29,99 | 33,3 | 11,40 |

Con un worker por tarea, `esperar` casi no se degrada: cada tarea sigue durando 1 s
aunque haya 10.000 en vuelo, porque una corrutina dormida cuesta casi nada. Lo que sube
es el tiempo de recibirlas: cada `POST` gasta CPU en parsear HTTP, validar y armar el
JSON, y todo eso pasa en un solo hilo. Con 10.000 tareas el servidor atendió unas 570 por
segundo.

Con `descargar` pasa algo más: con 500 o 1000 descargas a la vez, cada una de 1 s pasa a
tardar 8 y 11 s, y el rendimiento se queda en unas 30 tareas por segundo. El servidor
`lento` las atiende todas a la vez, así que el límite no es la demora. No investigué la
causa exacta; lo más probable es que sea CPU: el mismo hilo del loop maneja cientos de
conexiones abiertas con `httpx`, y además el servidor `lento` corre en la misma máquina y
le compite por los núcleos. Lo importante es que es lo primero que se degrada al subir la
concurrencia de I/O real, mucho antes que con `esperar`.

**CPU: `hashear` de 2.000.000 de iteraciones, 8 workers y 4 procesos**

| N | Total (s) | Tareas/s | Duración de cada tarea (s) | Espera promedio (s) |
|---|---|---|---|---|
| 1 | 4,02 | 0,2 | 3,96 | 0,00 |
| 2 | 4,75 | 0,4 | 4,61 | 0,00 |
| 4 | 6,89 | 0,6 | 6,51 | 0,00 |
| 8 | 9,17 | 0,9 | 8,67 | 0,00 |
| 16 | 15,31 | 1,0 | 7,45 | 3,68 |
| 32 | 32,86 | 1,0 | 8,02 | 12,31 |

Con CPU el techo son los núcleos, no los workers. Con 8 tareas se hicieron en 9 s lo que
una sola hace en 4 s, un speedup de unas 3,5 veces, razonable para 4 núcleos físicos con
el procesador ahorrando energía. A partir de ahí el rendimiento se queda en 1 tarea por
segundo y el tiempo total crece linealmente con N: más tareas simultáneas ya no ayudan,
porque no hay procesadores libres.

**10.000 `POST` de golpe** (8 workers, cola de 1000, tareas `esperar` de 1 s): se
aceptaron 1136 y se rechazaron 8864 con `503`, sin ningún otro código de error. Lo
primero que se agota es la cola, a propósito: es el mecanismo de protección, y el
servidor no se cayó.

## 6. Conceptos del curso aplicados

- **Docker y Compose (clases 1 y 2).** `Dockerfile` por capas, dos servicios, un volumen
  con nombre para los volcados y `stop_grace_period`.
- **Señales (clase 6).** SIGTERM y SIGINT disparan el apagado ordenado. Los procesos del
  pool ignoran SIGINT (`ignorar_sigint`), porque Ctrl+C le llega a todo el grupo de
  procesos y no quiero que mueran antes que el padre.
- **fork, spawn y el guard (clase 8).** El pool usa `spawn`, y por eso `main.py` tiene
  `if __name__ == "__main__":`.
- **Procesos para CPU (clase 9) y el GIL (clase 10).** Es el motivo de que `hashear`
  vaya a un `ProcessPoolExecutor` y no a hilos.
- **Productor-consumidor (clase 11).** El endpoint `POST` produce y los workers
  consumen, unidos por una `asyncio.Queue`. Es el mismo patrón que con threads, pero con
  corrutinas, y sin Lock porque el loop solo cambia de corrutina en un `await`.
- **Sockets y servidores concurrentes (clases 13 y 14).** Uvicorn es un servidor TCP que
  atiende a todos los clientes desde un solo hilo, en vez de un proceso o hilo por
  cliente.
- **`select` y `epoll` (clase 17).** El event loop de asyncio duerme en `epoll` hasta que
  algún socket tiene datos o vence un timer. Por eso miles de `esperar` casi no gastan
  CPU.
- **De `yield` a corrutinas (clase 18).** Una corrutina es una función que se suspende en
  el `await`. `cancel()` le inyecta un `CancelledError` en ese punto. Por eso
  `time.sleep` dentro de una corrutina es un error y `asyncio.sleep` no.
- **HTTP y FastAPI (clase 19).** Rutas `async def`, validación con pydantic (unión
  discriminada por `tipo`), códigos con significado (`202`, `404`, `409`, `422`, `503`) y
  `lifespan` para crear y liberar el pool y el cliente HTTP.
- **asyncio en red (clase 20).** Cliente HTTP asíncrono con streaming, `Semaphore`
  para acotar descargas, `asyncio.timeout` y `CancelledError` que no se traga.
- **asyncio avanzado (clase 21).** `Queue` con `maxsize` como contrapresión,
  `create_task`, `asyncio.wait`, `TaskGroup`, `Event` y `task_done` en `finally`.
- **`concurrent.futures` (clase 22).** `ProcessPoolExecutor` con `run_in_executor`, que
  convierte un `Future` en algo que se puede esperar con `await`. `Future.cancel()` no
  detiene un trabajo que ya arrancó, y por eso el hash va en tramos. Las funciones que
  van al pool son de nivel módulo porque viajan con pickle.

## 7. Limitaciones conocidas

- **El estado vive en memoria.** Al arrancar se informa el último volcado, pero las tareas
  no se reanudan.
- **El diccionario de tareas crece sin límite.** No se borran las terminadas.
- **`GET /tareas` y `/estadisticas` recorren todas las tareas.** Tienen un tope de 1000
  resultados, pero con muchas tareas guardadas igual cuestan tiempo del event loop.
- **Una tarea pendiente cancelada sigue ocupando su lugar en la cola** hasta que un
  worker la saca.
- **Al cancelar un `hashear`, el tramo en curso termina igual** en el proceso y se
  descarta su resultado.
- **Si un proceso del pool muere** (por ejemplo, por falta de memoria), el pool queda roto
  y los `hashear` siguientes fallan hasta reiniciar el servicio.
- **El timeout cuenta desde que la tarea arranca,** no desde que entra a la cola. No
  protege de una espera larga en la cola.
- **Con mucha concurrencia de descargas el rendimiento cae** (medición 3). Se podría
  acotar con un `Semaphore` global compartido por todas las tareas.
- **`descargar` acepta cualquier URL** (incluidas direcciones de la red interna) y no
  limita el tamaño de lo que baja.
- **Hay un solo proceso atendiendo HTTP,** así que la recepción de pedidos está limitada a
  un núcleo.
- **Sin autenticación ni límite de pedidos por cliente.**
- **El estado de las tareas que se cancelan por el apagado** queda como `cancelada`, no
  se reintentan al volver a arrancar.

## 8. Lo que aprendí

Lo que más me quedó es la diferencia entre esperar y calcular. Con 20 descargas pasé de
10 s a menos de 1 s sin agregar hilos ni procesos, porque casi todo ese tiempo era
espera. En cambio, un hash dentro del event loop dejó la API sin responder durante todo
el cálculo: un solo `GET /tareas` tardó casi 19 s. Verlo medido hace concreta la regla
de no bloquear el loop, porque hay un solo hilo y mientras calcula no atiende a nadie.

También aprendí que cancelar tiene más detalle del que parece. `cancel()` no mata nada:
inyecta una excepción en el próximo `await`. Por eso cada tarea corre en una Task hija,
para no llevarse puesto al worker, y por eso el hash va de a tramos, ya que un proceso
que arrancó no se puede interrumpir. Comprobar que los procesos del pool bajaban a 0 de
CPU después de cancelar me mostró que la cancelación era real y no solo un cambio de
estado.

Por último, medir me mostró cosas que no se ven en el código. La máquina que usé es lenta
para CPU y el speedup no llegó a 4, algo que no habría sabido sin correr la serie. Y al
mandar 10.000 tareas de golpe el sistema no se cayó porque la cola rechazó casi 9.000
con `503`. Ahí entendí que poner un límite también es parte del diseño.
