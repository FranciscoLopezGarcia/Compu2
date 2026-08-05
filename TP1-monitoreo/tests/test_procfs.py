import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import procfs


def test_listar_pids_incluye_este_proceso():
    pids = procfs.listar_pids()
    assert os.getpid() in pids
    assert 1 in pids
    assert all(isinstance(p, int) for p in pids)


def test_leer_stat_campos_coherentes():
    st = procfs.leer_stat(os.getpid())
    assert st["pid"] == os.getpid()
    assert st["ppid"] == os.getppid()
    assert "python" in st["comm"]
    assert st["state"] == "R"
    assert st["num_threads"] >= 1


def test_stat_con_parentesis_en_comm(tmp_path=None):
    import io, unittest.mock
    linea = "123 (mi (raro) proc) S 1 123 123 0 -1 0 5 0 2 0 3 4 0 0 20 0 2 0 99 1000 50 " + "0 " * 30
    with unittest.mock.patch("builtins.open", return_value=io.StringIO(linea)):
        st = procfs.leer_stat(123)
    assert st["comm"] == "mi (raro) proc"
    assert st["state"] == "S"
    assert st["utime"] == 3 and st["stime"] == 4


def test_decodificar_mascara():
    assert procfs.decodificar_mascara("0") == []
    assert procfs.decodificar_mascara("2") == ["SIGINT"]
    assert "SIGTERM" in procfs.decodificar_mascara("4000")
    assert procfs.decodificar_mascara("basura") == []


def test_leer_status_y_kb():
    status = procfs.leer_status(os.getpid())
    assert status["Pid"] == str(os.getpid())
    assert procfs.kb(status["VmRSS"]) > 0
    assert procfs.kb("  1234 kB") == 1234
    assert procfs.kb(None) == 0


def test_cmdline_y_fds():
    assert "python" in procfs.leer_cmdline(os.getpid())
    fds = procfs.listar_fds(os.getpid())
    numeros = [fd for fd, _, _ in fds]
    assert 0 in numeros and 1 in numeros


def test_globales():
    cpu = procfs.leer_cpu_global()
    assert cpu["user"] >= 0 and "idle" in cpu
    mem = procfs.leer_meminfo()
    assert mem["MemTotal"] > 0
    assert procfs.leer_uptime() > 0
    assert procfs.leer_loadavg()["1min"] >= 0


if __name__ == "__main__":
    fallas = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            try:
                fn()
                print(f"OK   {nombre}")
            except AssertionError as e:
                fallas += 1
                print(f"FAIL {nombre}: {e}")
    sys.exit(1 if fallas else 0)
