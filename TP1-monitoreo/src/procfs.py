import os

CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")

import signal as _signal
SIG_NAMES = {}
for i in range(1, 65):
    try:
        SIG_NAMES[i] = _signal.Signals(i).name
    except ValueError:
        SIG_NAMES[i] = f"SIG{i}"


def listar_pids():
    return sorted(int(d) for d in os.listdir("/proc") if d.isdigit())


def leer_stat(pid, tid=None):
    path = f"/proc/{pid}/task/{tid}/stat" if tid else f"/proc/{pid}/stat"
    with open(path) as f:
        raw = f.read()

    lparen = raw.index("(")
    rparen = raw.rindex(")")
    comm = raw[lparen + 1 : rparen]
    resto = raw[rparen + 2 :].split()

    return {
        "pid": int(raw[:lparen].strip()),
        "comm": comm,
        "state": resto[0],
        "ppid": int(resto[1]),
        "pgid": int(resto[2]),
        "sid": int(resto[3]),
        "minflt": int(resto[7]),
        "cminflt": int(resto[8]),
        "majflt": int(resto[9]),
        "cmajflt": int(resto[10]),
        "utime": int(resto[11]),
        "stime": int(resto[12]),
        "priority": int(resto[15]),
        "nice": int(resto[16]),
        "num_threads": int(resto[17]),
        "starttime": int(resto[19]),
        "rt_priority": int(resto[37]),
        "policy": int(resto[38]),
    }


def leer_status(pid, tid=None):
    path = f"/proc/{pid}/task/{tid}/status" if tid else f"/proc/{pid}/status"
    datos = {}
    with open(path) as f:
        for linea in f:
            if ":" in linea:
                clave, _, valor = linea.partition(":")
                datos[clave.strip()] = valor.strip()
    return datos


def leer_cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
        if raw:
            return raw.replace(b"\x00", b" ").decode(errors="replace").strip()
    except OSError:
        pass
    try:
        return "[" + leer_stat(pid)["comm"] + "]"
    except OSError:
        return "?"


def kb(valor_status):
    try:
        return int(valor_status.split()[0])
    except (ValueError, IndexError, AttributeError):
        return 0


def decodificar_mascara(hex_str):
    try:
        mask = int(hex_str, 16)
    except (ValueError, TypeError):
        return []
    return [SIG_NAMES[n] for n in range(1, 65) if mask & (1 << (n - 1))]


def listar_fds(pid):
    resultado = []
    base = f"/proc/{pid}/fd"
    try:
        fds = os.listdir(base)
    except OSError:
        return resultado
    for fd in sorted(fds, key=int):
        try:
            destino = os.readlink(f"{base}/{fd}")
        except OSError:
            continue
        if destino.startswith("socket:"):
            tipo = "socket"
        elif destino.startswith("pipe:"):
            tipo = "pipe"
        elif destino.startswith("anon_inode:"):
            tipo = "anon"
        elif destino.startswith("/dev/pts") or destino.startswith("/dev/tty"):
            tipo = "tty"
        elif destino.startswith("/dev/"):
            tipo = "dev"
        else:
            tipo = "file"
        resultado.append((int(fd), destino, tipo))
    return resultado


def listar_tids(pid):
    try:
        return sorted(int(t) for t in os.listdir(f"/proc/{pid}/task"))
    except OSError:
        return []


def leer_maps_agrupado(pid):
    grupos = {"text": 0, "data": 0, "heap": 0, "stack": 0, "shared": 0, "otro": 0}
    try:
        with open(f"/proc/{pid}/maps") as f:
            for linea in f:
                partes = linea.split()
                if len(partes) < 2:
                    continue
                ini, fin = (int(x, 16) for x in partes[0].split("-"))
                tam_kb = (fin - ini) // 1024
                perms = partes[1]
                nombre = partes[5] if len(partes) >= 6 else ""
                if nombre == "[heap]":
                    grupos["heap"] += tam_kb
                elif nombre.startswith("[stack"):
                    grupos["stack"] += tam_kb
                elif "s" in perms:
                    grupos["shared"] += tam_kb
                elif "x" in perms:
                    grupos["text"] += tam_kb
                elif "w" in perms:
                    grupos["data"] += tam_kb
                else:
                    grupos["otro"] += tam_kb
    except OSError:
        pass
    return grupos


def leer_cpu_global():
    with open("/proc/stat") as f:
        campos = f.readline().split()[1:]
    nombres = ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal"]
    return dict(zip(nombres, (int(c) for c in campos)))


def leer_loadavg():
    with open("/proc/loadavg") as f:
        p = f.read().split()
    return {"1min": float(p[0]), "5min": float(p[1]), "15min": float(p[2])}


def leer_meminfo():
    claves = {"MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached",
              "SwapTotal", "SwapFree"}
    datos = {}
    with open("/proc/meminfo") as f:
        for linea in f:
            clave, _, valor = linea.partition(":")
            if clave in claves:
                datos[clave] = kb(valor)
    return datos


def leer_uptime():
    with open("/proc/uptime") as f:
        return float(f.read().split()[0])


def leer_boot_time():
    with open("/proc/stat") as f:
        for linea in f:
            if linea.startswith("btime"):
                return int(linea.split()[1])
    return 0


import pwd

POLICIES = {0: "OTHER", 1: "FIFO", 2: "RR", 3: "BATCH", 5: "IDLE", 6: "DEADLINE"}


def uid_a_usuario(uid):
    try:
        return pwd.getpwuid(int(uid)).pw_name
    except (KeyError, ValueError):
        return str(uid)


def nombre_policy(n):
    return POLICIES.get(n, f"?{n}")
