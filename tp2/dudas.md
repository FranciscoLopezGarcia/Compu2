# Dudas durante el desarrollo

Cada duda quedó con la respuesta a la que llegué y cómo la verifiqué.

---

## 1. ¿Se puede cancelar un hash que ya está corriendo en el pool de procesos?

**Resuelto: no, y por eso el hash va en tramos.** `Future.cancel()` solo cancela si el
trabajo no arrancó. Un tramo que ya está en un proceso del pool termina igual. Lo que sí
puedo hacer es no mandar el tramo siguiente: la cancelación entra en el `await` que hay
entre un tramo y otro.

Lo comprobé lanzando un `hashear` de 2.000 millones de iteraciones y sumando el tiempo de
CPU de los procesos hijos del servidor, leyendo `/proc/<pid>/stat`:

- mientras corre: 3,00 s de CPU en 3 s de reloj;
- después del `DELETE`: 0,00 s de CPU en 3 s.

El `DELETE` respondió `cancelada` en 3 ms. Lo que se desperdicia es, como mucho, un tramo
(200.000 iteraciones).

---

## 2. ¿Quién atrapa SIGTERM: yo o uvicorn?

**Resuelto: uvicorn, y el `lifespan` hace el resto.** Primero pensé en instalar mi propio
manejador con `loop.add_signal_handler`, pero uvicorn ya lo hace: al recibir SIGTERM o
SIGINT deja de aceptar conexiones y corre la parte final del `lifespan`, que es donde
llamo a `Gestor.apagar()` y guardo el JSON.

Lo verifiqué mandando `kill -TERM` al servidor con dos tareas `esperar` de 30 s (una en
curso, una pendiente) y `LIMITE_APAGADO=2`: salió a los 2,24 s, la pendiente quedó
`cancelada` por el apagado, la que corría quedó `cancelada` con el motivo "se acabo el
tiempo", y el archivo `estado_*.json` se escribió con las dos.

Detalle: el proceso termina con código 143 (-15 en Python), porque uvicorn vuelve a
lanzar la señal al terminar el cierre. Es normal, y el volcado ya está escrito.

---

## 3. ¿Cómo hago para que el `DELETE` devuelva el estado final de la tarea?

**Resuelto con un `asyncio.Event`, razonando el orden de ejecución (no vi el fallo en
la práctica).** Si el `DELETE` solo hace `hija.cancel()` y espera a la hija, tanto él como
el worker se despiertan cuando la hija termina, y el orden en que corren no está
garantizado. Si el `DELETE` va primero, devolvería la tarea todavía como `ejecutando`,
porque el worker no alcanzó a registrar el final.

Por eso cada tarea tiene un evento `terminada` que se activa dentro de `finalizar()`, y el
`DELETE` espera ese evento y no a la hija. Los tests de cancelación comprueban que la
respuesta del `DELETE` ya trae `cancelada`.

---

## 4. ¿Por qué mis tiempos de CPU son más lentos que los de los otros TPs?

**Resuelto: es el hardware.** Mi máquina es un portátil i7-10510U de 4 núcleos físicos con
el gobernador en `powersave` (900 MHz en reposo). Dos millones de hashes en un solo núcleo
tardan 4,15 s, contra cerca de 1 s en un Ryzen 7 de escritorio. El speedup máximo de unas
3,5 veces con 8 tareas es coherente con 4 núcleos físicos.

Lo que dicen las mediciones no depende de eso: el `GET` queda congelado con el hash en el
loop y responde en milisegundos con el executor, en cualquier hardware.
