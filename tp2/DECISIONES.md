# Decisiones de diseño tomadas durante el desarrollo

Registro corto de decisiones chicas. Las justificaciones largas están en el README.

1. **`config.py` aparte.** Las variables de entorno (`WORKERS`, `PROCESOS`, `TAMANO_COLA`,
   `TIMEOUT_DEFECTO`, `LIMITE_APAGADO`, `DIR_VOLCADOS`) se leen en una clase `Config`. Los
   tests arman su propia config sin tocar el entorno.
2. **`crear_app(config, cliente)`.** La app se arma con una función. `api.py` expone además
   `app = crear_app()` para uvicorn. El parámetro `cliente` permite que un test use un
   transporte falso de httpx.
3. **Cola con `maxsize`.** El `POST` usa `put_nowait`: si la cola está llena responde 503 y
   no se queda esperando.
4. **IDs con `uuid4().hex`.**
5. **Estados en español** (`pendiente`, `ejecutando`, `completada`, `fallida`, `cancelada`).
6. **`concurrencia` en `descargar`** en vez de un modo secuencial/concurrente. Con
   `concurrencia: 1` es secuencial, y lo usa la medición 1.
7. **`bloqueante` en `hashear`** existe solo para la medición 2. Corre el hash dentro del
   loop a propósito.
8. **El `DELETE` espera a que la tarea termine de cancelarse** (un `asyncio.Event`) para
   devolver el estado final.
9. **Si la tarea ya terminó, el `DELETE` responde 409.**
10. **Al apagar, las pendientes se cancelan enseguida** y no se ejecutan durante el
    `LIMITE_APAGADO`. Ese tiempo es solo para las que ya estaban corriendo.
11. **Los volcados van a un volumen con nombre de Docker** y no a una carpeta del host, para
    no llenar el repo de archivos de root. Se ven con `docker compose exec api ls volcados`.
12. **El pool usa `spawn`** y cada proceso ignora SIGINT, para que Ctrl+C lo maneje solo el
    proceso principal.
13. **`pool.shutdown` y el volcado van en `asyncio.to_thread`** para no frenar el loop.
14. **`GET /tareas` tiene `limite` (100 por defecto, 1000 como máximo)** y no devuelve el
    resultado ni los parámetros de cada tarea, para que el listado sea liviano.
15. **El timeout del cliente httpx es de 30 s.** El que manda es el timeout de la tarea.
16. **Los tests de `descargar` usan `httpx.MockTransport`,** así no dependen de la red.
17. **Los scripts de medición usan solo la biblioteca estándar** y corren desde el host sin
    instalar nada.
