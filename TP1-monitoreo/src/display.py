import os
import queue
import signal
import sys
import termios
import threading
import time
import tty

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

VISTAS = {
    "1": "resumen", "r": "resumen",
    "2": "memoria", "m": "memoria",
    "3": "fds", "f": "fds",
    "4": "threads", "t": "threads",
    "5": "senales", "s": "senales",
    "6": "scheduling", "p": "scheduling",
    "7": "sistema", "g": "sistema",
}
ORDENES = ["cpu", "rss", "pid"]

AYUDA = """\
[bold]Teclas[/bold]
 1-7 / r m f t s p g  cambiar de vista      ↑ ↓  navegar procesos
 Enter  fijar (pin) el proceso seleccionado  c    orden: CPU% → RSS → PID
 /  filtrar por comando    u  filtrar por usuario    (Esc/Enter termina)
 + -  ajustar intervalo de la vista activa
 h/?  esta ayuda    q  salir limpiamente

[bold]Señales que atiende el monitor[/bold] (kill -SEÑAL <pid del main>)
 SIGINT/SIGTERM shutdown · SIGHUP recarga config · SIGUSR1 dump json
 SIGUSR2 verbose · SIGWINCH repintar\
"""


def leer_teclado(fd, cola, apagando):
    try:
        viejo = termios.tcgetattr(fd)
    except termios.error:
        return
    try:
        tty.setcbreak(fd)
        while not apagando.is_set():
            ch = os.read(fd, 1).decode(errors="ignore")
            if ch == "":
                break
            if ch == "\x1b":
                ch += os.read(fd, 2).decode(errors="ignore")
            cola.put(ch)
    except OSError:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, viejo)


class Display:
    def __init__(self, snapshot, intervalos, apagando, pipe_eventos, config):
        self.snapshot = snapshot
        self.intervalos = intervalos
        self.apagando = apagando
        self.pipe = pipe_eventos
        self.minimos = config.get("intervalos_minimos", {})
        self.vista = "resumen"
        self.seleccion = 0
        self.pin = None
        self.filtro = config.get("filtro_default", "")
        self.filtro_usuario = ""
        self.orden = config.get("orden_default", "cpu")
        self.capturando = None
        self.buffer = ""
        self.aviso = ""
        self.aviso_hasta = 0
        self.ayuda = False
        self.consola = Console()

    def procesos_visibles(self):
        sec = self.snapshot.get("resumen")
        if not sec:
            return []
        procs = list(sec["datos"].values())
        if self.filtro:
            procs = [p for p in procs if self.filtro.lower() in p["comando"].lower()]
        if self.filtro_usuario:
            procs = [p for p in procs if p["usuario"] == self.filtro_usuario]
        clave = {"cpu": lambda p: -p["cpu"],
                 "rss": lambda p: -p["rss_kb"],
                 "pid": lambda p: p["pid"]}[self.orden]
        return sorted(procs, key=clave)

    def pid_actual(self, visibles):
        if self.pin is not None:
            return self.pin
        if visibles:
            self.seleccion = max(0, min(self.seleccion, len(visibles) - 1))
            return visibles[self.seleccion]["pid"]
        return None

    def tecla(self, ch):
        if self.capturando:
            if ch in ("\r", "\n", "\x1b"):
                self.capturando = None
            elif ch in ("\x7f", "\x08"):
                self.buffer = self.buffer[:-1]
                self._aplicar_filtro()
            elif ch.isprintable() and len(ch) == 1:
                self.buffer += ch
                self._aplicar_filtro()
            return
        if ch == "q":
            self.apagando.set()
        elif ch in VISTAS:
            self.vista = VISTAS[ch]
        elif ch == "\x1b[A":
            self.seleccion -= 1
        elif ch == "\x1b[B":
            self.seleccion += 1
        elif ch in ("\r", "\n"):
            visibles = self.procesos_visibles()
            actual = self.pid_actual(visibles)
            self.pin = None if self.pin == actual else actual
        elif ch == "/":
            self.capturando, self.buffer = "cmd", ""
        elif ch == "u":
            self.capturando, self.buffer = "usr", ""
        elif ch == "c":
            self.orden = ORDENES[(ORDENES.index(self.orden) + 1) % len(ORDENES)]
        elif ch in ("+", "-"):
            self._ajustar_intervalo(-0.5 if ch == "+" else 0.5)
        elif ch in ("h", "?"):
            self.ayuda = not self.ayuda

    def _aplicar_filtro(self):
        if self.capturando == "cmd":
            self.filtro = self.buffer
        else:
            self.filtro_usuario = self.buffer

    def _ajustar_intervalo(self, delta):
        if self.vista not in self.intervalos:
            return
        v = self.intervalos[self.vista]
        minimo = float(self.minimos.get(self.vista, 0.5))
        v.value = max(minimo, round(v.value + delta, 1))
        self.mostrar_aviso(f"intervalo de {self.vista}: {v.value:.1f}s")

    def mostrar_aviso(self, texto):
        self.aviso, self.aviso_hasta = texto, time.time() + 3

    def render(self):
        visibles = self.procesos_visibles()
        pid = self.pid_actual(visibles)

        layout = Layout()
        layout.split_column(
            Layout(self._tabla_procesos(visibles), name="lista", ratio=3),
            Layout(self._panel_detalle(pid), name="detalle", ratio=2),
            Layout(self._barra_estado(), name="estado", size=3),
        )
        return layout

    def _tabla_procesos(self, visibles):
        t = Table(expand=True, box=None, header_style="bold cyan", pad_edge=False)
        for col in ("PID", "USUARIO", "S", "CPU%", "RSS(MB)", "THR", "COMANDO"):
            t.add_column(col, no_wrap=(col != "COMANDO"))
        alto = max(5, self.consola.size.height * 3 // 5 - 4)
        base = max(0, min(self.seleccion - alto // 2, len(visibles) - alto))
        for i, p in enumerate(visibles[base:base + alto], start=base):
            marca = "📌" if p["pid"] == self.pin else ""
            estilo = "reverse" if i == self.seleccion else (
                "red" if p["estado"] == "Z" else "")
            t.add_row(f'{p["pid"]}{marca}', p["usuario"], p["estado"],
                      f'{p["cpu"]:.1f}', f'{p["rss_kb"] / 1024:.1f}',
                      str(p["threads"]), p["comando"][:80], style=estilo)
        titulo = f"Procesos ({len(visibles)})"
        if self.filtro:
            titulo += f" · filtro:{self.filtro!r}"
        if self.filtro_usuario:
            titulo += f" · usuario:{self.filtro_usuario!r}"
        return Panel(t, title=titulo, border_style="cyan")

    def _panel_detalle(self, pid):
        if self.ayuda:
            return Panel(Text.from_markup(AYUDA), title="Ayuda", border_style="yellow")
        sec = self.snapshot.get(self.vista)
        if not sec:
            return Panel("cargando…", title=self.vista)
        edad = time.time() - sec["ts"]
        titulo = (f"{self.vista} · intervalo "
                  f"{self.intervalos[self.vista].value:.1f}s · hace {edad:.1f}s")
        cuerpo = self._render_vista(sec["datos"], pid)
        return Panel(cuerpo, title=titulo, border_style="green")

    def _render_vista(self, datos, pid):
        if self.vista == "sistema":
            return self._vista_sistema(datos)
        if pid is None or pid not in datos:
            return Text("sin datos para el proceso seleccionado "
                        "(puede haber terminado, o faltan permisos)")
        d = datos[pid]
        if self.vista == "memoria":
            filas = [f"[bold]{c}[/bold]: {d[c]:,} kB" for c in
                     ("VmSize", "VmRSS", "VmHWM", "VmData", "VmStk",
                      "VmExe", "VmLib", "VmSwap")]
            filas.append(f"faults menores/mayores: {d['minflt']:,}/{d['majflt']:,}"
                         f"  (hijos: {d['cminflt']:,}/{d['cmajflt']:,})")
            seg = " · ".join(f"{k}:{v:,}kB" for k, v in d["segmentos"].items())
            filas.append(f"segmentos: {seg}")
            return Text.from_markup("\n".join(filas))
        if self.vista == "fds":
            t = Table(box=None, header_style="bold")
            for c in ("FD", "TIPO", "DESTINO"):
                t.add_column(c)
            for fd, destino, tipo in d["fds"]:
                t.add_row(str(fd), tipo, destino[:70])
            tipos = " · ".join(f"{k}:{v}" for k, v in d["por_tipo"].items())
            extra = "" if d["total"] <= len(d["fds"]) else \
                f"  (mostrando {len(d['fds'])} de {d['total']}; SIGUSR2 muestra más)"
            return Group(Text(f"total: {d['total']}  {tipos}{extra}"), t)
        if self.vista == "threads":
            t = Table(box=None, header_style="bold")
            for c in ("TID", "NOMBRE", "S", "CPU%", "CTX vol", "CTX invol"):
                t.add_column(c)
            for h in d:
                t.add_row(str(h["tid"]), h["nombre"][:20], h["estado"],
                          f'{h["cpu"]:.1f}', str(h["ctx_vol"]), str(h["ctx_invol"]))
            return t
        if self.vista == "senales":
            filas = []
            for m, nombres in d.items():
                lista = ", ".join(nombres) if nombres else "—"
                filas.append(f"[bold]{m}[/bold]: {lista}")
            return Text.from_markup("\n".join(filas))
        if self.vista == "scheduling":
            return Text.from_markup(
                f"[bold]policy[/bold]: {d['policy']}   [bold]nice[/bold]: {d['nice']}"
                f"   [bold]priority[/bold]: {d['priority']}"
                f"   [bold]rt_priority[/bold]: {d['rt_priority']}\n"
                f"[bold]afinidad CPU[/bold]: {d['affinity']}\n"
                f"[bold]ctx switches[/bold] voluntarios: {d['ctx_vol']:,}"
                f" · involuntarios: {d['ctx_invol']:,}\n"
                f"[bold]utime/stime[/bold] (jiffies): {d['utime']:,}/{d['stime']:,}\n"
                f"[bold]SID[/bold]: {d['sid']}   [bold]PGID[/bold]: {d['pgid']}")
        d0 = datos[pid]
        return Text.from_markup(
            f"[bold]PID[/bold] {d0['pid']}  [bold]PPID[/bold] {d0['ppid']}"
            f"  [bold]usuario[/bold] {d0['usuario']} (uid={d0['uid']} gid={d0['gid']})"
            f"  [bold]estado[/bold] {d0['estado']}"
            f"  [bold]threads[/bold] {d0['threads']}\n"
            f"[bold]CPU[/bold] {d0['cpu']}%   [bold]RSS[/bold] {d0['rss_kb']:,} kB\n"
            f"[bold]cmd[/bold] {d0['comando'][:200]}")

    def _vista_sistema(self, d):
        cpu = d.get("cpu_pct", {})
        mem = d.get("meminfo", {})
        la = d.get("loadavg", {})
        usada = mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)
        filas = [
            "[bold]CPU[/bold]  " + "  ".join(f"{k}:{v}%" for k, v in cpu.items()),
            f"[bold]load[/bold] {la.get('1min')} / {la.get('5min')} / {la.get('15min')}"
            f"   [bold]uptime[/bold] {d.get('uptime_s', 0)/3600:.1f}h",
            f"[bold]mem[/bold] usada {usada//1024:,}MB de "
            f"{mem.get('MemTotal', 0)//1024:,}MB"
            f" · buffers {mem.get('Buffers', 0)//1024:,}MB"
            f" · cached {mem.get('Cached', 0)//1024:,}MB"
            f" · swap libre {mem.get('SwapFree', 0)//1024:,}MB",
            f"[bold]procesos[/bold] {d.get('procesos_total')}"
            f" · por estado {d.get('por_estado')}"
            f" · [red]zombies {d.get('zombies')}[/red]"
            f" · threads totales {d.get('threads_totales')}",
            "[bold]top CPU[/bold]  " + "   ".join(
                f"{pid} {comm} {cpu_}%" for pid, comm, cpu_, _ in d.get("top_cpu", [])),
            "[bold]top RSS[/bold]  " + "   ".join(
                f"{pid} {comm} {rss//1024}MB" for pid, comm, _, rss in d.get("top_rss", [])),
        ]
        return Text.from_markup("\n".join(filas))

    def _barra_estado(self):
        if self.capturando:
            texto = f"filtro {'comando' if self.capturando == 'cmd' else 'usuario'}: {self.buffer}▏"
        elif time.time() < self.aviso_hasta:
            texto = f"⚡ {self.aviso}"
        else:
            texto = ("vista: " + self.vista +
                     " · orden: " + self.orden +
                     " · [1-7] vistas  [↑↓] navegar  [Enter] pin  [/u] filtros"
                     "  [+-] intervalo  [h] ayuda  [q] salir")
        return Panel(Text(texto), border_style="dim")


def correr_display(snapshot, intervalos, apagando, pipe_eventos, config, stdin_fd):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    d = Display(snapshot, intervalos, apagando, pipe_eventos, config)

    cola = queue.Queue()
    hilo = threading.Thread(target=leer_teclado, args=(stdin_fd, cola, apagando),
                            daemon=True)
    hilo.start()

    with Live(d.render(), screen=True, auto_refresh=False) as live:
        while not apagando.is_set():
            try:
                d.tecla(cola.get(timeout=0.25))
            except queue.Empty:
                pass
            while pipe_eventos.poll():
                tipo, dato = pipe_eventos.recv()
                if tipo == "aviso":
                    d.mostrar_aviso(dato)
            live.update(d.render(), refresh=True)
