import os
import signal

_pipe_w = None

BYTES = {
    signal.SIGINT: b"I",
    signal.SIGTERM: b"T",
    signal.SIGHUP: b"H",
    signal.SIGUSR1: b"1",
    signal.SIGUSR2: b"2",
    signal.SIGWINCH: b"W",
}


def _handler(signum, frame):
    try:
        os.write(_pipe_w, BYTES.get(signum, b"?"))
    except (OSError, TypeError):
        pass


def instalar():
    global _pipe_w
    r, w = os.pipe()
    os.set_blocking(r, False)
    os.set_blocking(w, False)
    _pipe_w = w
    for sig in BYTES:
        signal.signal(sig, _handler)
    return r
