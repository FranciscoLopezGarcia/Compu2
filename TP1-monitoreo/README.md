# TP1 — Monitor de Procesos y Threads

**Computación II — Universidad de Mendoza — 2026**
Autor: Francisco López García

Monitor del sistema en tiempo real, estilo `htop`, que lee `/proc` a mano
(sin `psutil`) y muestra la anatomía interna de cada proceso: memoria,
file descriptors, threads, máscaras de señales y datos de scheduling.
Arquitectura multiproceso: un recolector, 7 analizadores en paralelo,
un agregador y una TUI hecha con `rich`.

## Cómo correr

```bash
docker compose up --build
```

El compose usa `pid: host`, así el contenedor comparte el PID namespace
del host y el monitor ve todos los procesos de la máquina (sin eso vería
solo los ~2 del contenedor). `tty: true` + `stdin_open: true` son
necesarios para que la TUI dibuje y reciba teclado.

También corre nativo en cualquier Linux con Python 3.11+:

```bash
pip install -r requirements.txt
python3 src/main.py               # TUI completa
python3 src/main.py --sin-tui     # sin interfaz (útil con SIGUSR1 para dumps)
python3 -m pytest tests/ -v       # tests del parseo (o python3 tests/test_procfs.py)
```

### Teclas

`1-7` o `r m f t s p g` cambian de vista · `↑ ↓` navegan · `Enter` fija
(pin) un proceso · `/` filtra por comando · `u` filtra por usuario · `c`
rota el orden (CPU% → RSS → PID) · `+ -` ajustan el intervalo de la vista
activa · `h` ayuda · `q` sale.

### Señales que atiende el monitor

Con el monitor corriendo, desde otra terminal (`pgrep -f src/main.py`
para conocer el PID del proceso principal):

| Señal | Efecto |
|---|---|
| `SIGINT` / `SIGTERM` | shutdown limpio (termina hijos en orden) |
| `SIGHUP` | recarga `config.json` (intervalos por vista) en caliente |
| `SIGUSR1` | vuelca el snapshot completo a `dump_<timestamp>.json` |
| `SIGUSR2` | toggle verbose (ej.: la vista FDs pasa de 15 a 100 fds) |
| `SIGWINCH` | repinta (la manda la terminal sola al redimensionar) |

## Arquitectura

```
                 ┌─────────────────────────────────────────┐
                 │       SNAPSHOT GLOBAL (Manager.dict)     │
                 │  resumen · memoria · fds · threads ·     │
                 │  senales · scheduling · sistema  (+ts)   │
                 └───────▲──────────────────────────┬───────┘
                escribe  │ (único escritor)         │ lee (solo lectura)
                 ┌───────┴────────┐          ┌──────▼───────┐
                 │   AGREGADOR    │          │ DISPLAY (TUI)│◄── teclado
                 └───────▲────────┘          │  rich + thread│    (thread
                         │ Queue resultados  └──────┬───────┘     interno)
        ┌────────┬───────┴┬─────────┬─── ... ───┐   │ ajusta Value
   ┌────┴───┐┌───┴────┐┌──┴─────┐┌──┴────┐ ┌────┴───┴┐
   │resumen ││memoria ││  fds   ││threads│ │ etc (7) │  ◄─ cada uno con su
   │  2s    ││  3s    ││  5s    ││  2s   │ │         │     intervalo (Value)
   └────▲───┘└───▲────┘└──▲─────┘└──▲────┘ └────▲────┘
        └────────┴───── Queues de pids (una c/u) ┴──────┐
                                              ┌─────────┴─┐
   señales → self-pipe → select() en main ←───│ RECOLECTOR│ lista /proc c/2s
             main ──Pipe──► display (avisos)  └───────────┘
```

- **Recolector** (proceso): cada 2s lista las carpetas numéricas de
  `/proc` y manda la lista de PIDs a cada analizador por su `Queue`.
- **7 analizadores** (un proceso cada uno, NO threads): leen `/proc` por
  su cuenta según su dimensión y su propio intervalo, y mandan el
  resultado a una `Queue` común de resultados.
- **Agregador** (proceso): único que escribe el snapshot (`Manager.dict`).
  También deriva el top-3 por CPU/RSS a partir de la sección `resumen`.
- **Display** (proceso): renderiza con `rich` leyendo el snapshot. El
  teclado corre en un thread interno del display (permitido por la
  consigna para entrada), que pone la terminal en modo raw con `termios`.
- **Main**: instala los handlers de señales con self-pipe, supervisa, y
  coordina el shutdown con un `Event`.

## Decisiones de diseño

### ¿Por qué cada mecanismo de IPC?

| Canal | Mecanismo | Por qué |
|---|---|---|
| recolector → analizadores | una `Queue` por analizador | Una Queue es punto-a-punto: si los 7 leyeran de la misma, cada lista la consumiría uno solo. Con una por analizador se logra broadcast. `maxsize=10` evita acumulación si un analizador se atrasa; cada uno drena y usa solo la lista más reciente. |
| analizadores → agregador | una `Queue` común | Acá el patrón es el inverso (muchos productores, un consumidor) y es exactamente lo que una Queue resuelve: serializa los mensajes en orden de llegada. |
| snapshot compartido | `Manager.dict` | El snapshot es una estructura anidada de tamaño variable (dicts de dicts por pid). `Value`/`Array` son para datos de tamaño fijo y tipo simple; serializar todo a mano en un `Array` sería reinventar el Manager. El costo (un proceso servidor y proxies) se paga una sola vez por escritura de sección. |
| display → analizadores | `Value('d')` por intervalo | Es un único double que dos procesos comparten: exactamente el caso de uso de `Value` (memoria compartida real, sin serialización). El toggle verbose es un `Value('b')` por el mismo motivo. |
| main → display | `Pipe` | Canal 1-a-1 para eventos esporádicos (avisos de señales, repaint). Más liviano que una Queue: no necesita el thread alimentador que la Queue crea por debajo. |
| señales → main loop | self-pipe (`os.pipe`) | Ver sección de señales. |
| apagado | `Event` | Un booleano compartido que todos consultan; la forma canónica de coordinar un shutdown cooperativo. |

### Race conditions: dónde podrían estar y cómo se previenen

1. **Escrituras concurrentes al snapshot**: si los 7 analizadores
   escribieran directo al `Manager.dict`, habría interleaving en
   operaciones compuestas (p. ej. derivar el top-3 leyendo `resumen`
   mientras otro lo pisa). Solución de diseño: **único escritor** (el
   agregador). La Queue de resultados ya serializa; no hacen falta Locks
   porque se eliminó la concurrencia de escritura en la raíz.
2. **Lecturas del display a mitad de escritura**: el agregador asigna
   cada sección completa con un solo `snapshot[seccion] = {...}`
   (una operación sobre el proxy = un round-trip al proceso Manager, que
   atiende de a un pedido). El display ve la sección vieja o la nueva,
   nunca una mezcla. Jamás se muta una sección "por partes".
3. **Los `Value` de intervalos**: display escribe, analizador lee. Son
   lecturas/escrituras simples de un double con lock interno del Value;
   no hay read-modify-write concurrente (solo el display modifica).
4. **stdin compartido**: solo el display lee teclado, y main le pasa un
   `os.dup()` del stdin real (multiprocessing pone `/dev/null` como
   stdin de los hijos justamente para evitar que compitan por él).

### ¿Por qué esos intervalos default?

Los de la consigna: 2s para lo "vivo" (resumen, threads, sistema), 3-5s
para lo costoso de leer (memoria recorre `maps`; fds hace un `readlink`
por descriptor), 10s para lo casi estático (máscaras de señales y
scheduling cambian poco). Cada vista muestra la edad de sus datos
(`hace X.Xs`) para que el desfasaje sea visible y honesto. `+`/`-`
respetan los mínimos de la consigna (en `config.json`).

### Señales: patrón self-pipe

Un handler puede interrumpir al proceso en cualquier instrucción; dentro
de él solo es seguro lo async-signal-safe (nada de prints, locks, ni
tocar el Manager: riesgo de deadlock o corrupción). Por eso el handler
hace **una sola cosa**: `os.write()` de un byte identificatorio a un
pipe propio (os.write es async-signal-safe). El loop principal espera
ese pipe con `select()` y hace el trabajo real (dump, reload, toggle) en
contexto normal. Es el patrón self-pipe de la clase 6; el pipe se abre
no-bloqueante para que el handler nunca se quede trabado si se llena.

Los hijos ignoran SIGINT (`SIG_IGN`): el Ctrl+C en la terminal se lo
manda al grupo entero, pero el shutdown lo coordina main solo, vía el
`Event` — si cada hijo muriera por su cuenta a mitad de una escritura,
el estado quedaría inconsistente.

## Conceptos del curso aplicados

- **Clase 3 (procesos, /proc)**: todo `procfs.py`. Detalle no trivial:
  el campo `comm` de `/proc/<pid>/stat` va entre paréntesis y puede
  contener espacios y paréntesis, así que el parser corta en el último
  `)` con `rindex` en vez de un `split()` ingenuo (hay un test de eso).
- **Clase 4 (fork/wait, zombies)**: la vista Sistema cuenta los procesos
  en estado `Z`: terminaron pero su padre aún no llamó a `wait()`. Se ve
  en vivo: si se mata un analizador con `kill -9`, queda como zombie
  hijo de main (que recién lo cosecha en el shutdown) y el propio
  monitor lo muestra. `p.join()` del shutdown es el `wait()` de la
  familia multiprocessing.
- **Clase 5 (pipes/FDs)**: la vista FDs lee `/proc/<pid>/fd` e infiere
  el tipo por el destino del symlink (`pipe:[inode]`, `socket:[...]`,
  `/dev/pts/N`). El self-pipe de señales y el `Pipe` main→display son
  pipes usados como IPC.
- **Clase 6 (señales)**: decodificación de las máscaras hex de 64 bits
  (`SigBlk/SigIgn/SigCgt/SigPnd/ShdPnd`: bit N-1 = señal N) y el patrón
  self-pipe para handlers async-signal-safe.
- **Clase 7 (memoria compartida)**: `Manager.dict` para el snapshot y
  `Value` para intervalos/verbose. La vista Memoria agrupa
  `/proc/<pid>/maps` en text/data/heap/stack/shared por permisos.
- **Clases 8-9 (multiprocessing)**: `Process`, `Queue`, `Pipe`,
  `Manager`, `Value`, `Event`; patrón productor-consumidor
  (analizadores→agregador) y broadcast (recolector→analizadores).
- **Clase 10 (threading, GIL)**: la vista Threads muestra que en Linux
  un thread es un LWP con entrada propia en `/proc/<pid>/task/<tid>`.
  Los context switches voluntarios (cedió la CPU esperando I/O) vs
  involuntarios (lo desalojó el scheduler; típico de CPU-bound) salen de
  `status`. El único thread del proyecto es el de teclado del display,
  permitido por consigna: threading alcanza ahí porque es I/O-bound
  (el GIL se libera en el read bloqueante).
- **Clase 11 (sincronización)**: la estrategia general fue *eliminar* la
  concurrencia de escritura por diseño (único escritor + colas) en vez
  de administrarla con Locks.

## Sobre la TUI

Elegí `rich` sobre `curses` porque el layout declarativo
(Layout/Panel/Table) deja el código de render legible, maneja resize y
unicode solo, y permitió testear el render sin terminal (renderizando a
una `Console` de tamaño fijo en los tests manuales). El costo es una
dependencia externa (curses viene en la stdlib) y menos control fino
del refresco.

## Limitaciones conocidas

- **CPU% de la primera lectura es 0.0** para todo proceso: no hay delta
  anterior contra el cual calcular. Se corrige solo al segundo ciclo.
- **Permisos**: sin root, `/proc/<pid>/fd` de procesos ajenos no es
  legible (se muestra total 0); corriendo en Docker como root se ve todo.
- **Procesos que mueren entre el listado y la lectura**: se salta el pid
  (except OSError). Puede haber un pid en la lista de arriba sin datos
  en el detalle durante un ciclo.
- **Si un analizador muere, su vista queda congelada** (con la edad
  `hace X.Xs` creciendo, lo que al menos lo hace visible). No hay
  reinicio automático de hijos.
- **El dump de SIGUSR1 serializa con `default=str`**: tuplas del top-3
  quedan como strings en el JSON.
- **Escala**: el costo por ciclo es O(procesos); con miles de procesos
  las vistas fds/memoria convendría bajarlas de frecuencia (con `-`) o
  limitar a los pids visibles.

## Lo que aprendí

Que `/proc` no es un directorio sino una API del kernel disfrazada de
archivos, y que leerla a mano obliga a entender qué es cada número (un
jiffy, una máscara de bits, un kB de RSS). Que la forma más simple de
"resolver" una race condition es rediseñar para que no exista (un solo
escritor) en lugar de llenarla de locks. Y que multiprocessing tiene
detalles nada obvios, como que reemplaza el stdin de los hijos por
/dev/null: el teclado de la TUI no andaba hasta duplicar el fd del
stdin real y pasárselo al display.
