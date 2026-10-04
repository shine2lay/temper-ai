#!/usr/local/bin/python3
"""Temper Pi worker box entry (runs inside the container as the image's Python).

1. Opens an in-container relay on 127.0.0.1:3128. Each accepted TCP connection is piped byte
   for byte to the host's egress proxy through the bind-mounted Unix socket
   /box-sock/egress.sock. The container has --network none, so this relay is the only way
   out, and the host side decides what may pass (the route's provider host, port 443 only).
2. Starts Pi from the pinned runtime with the metadata observer preloaded, inheriting
   stdin/stdout/stderr so Pi's RPC protocol is unchanged, and exits with Pi's exit code.

This file never reads or forwards anything except opaque bytes; it logs nothing.
"""
import signal
import socket
import subprocess
import sys
import threading

EGRESS = "/box-sock/egress.sock"
NODE = "/pi-runtime/node"
CLI = "/pi-runtime/pi/dist/bundle/cli.js"
OBSERVER = "/box/observer.cjs"


def pipe(src, dst):
    try:
        while data := src.recv(65536):
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def serve(listener):
    while True:
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        try:
            up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            up.connect(EGRESS)
        except OSError:
            conn.close()
            continue
        for a, b in ((conn, up), (up, conn)):
            threading.Thread(target=pipe, args=(a, b), daemon=True).start()


def main():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 3128))
    listener.listen(64)
    threading.Thread(target=serve, args=(listener,), daemon=True).start()
    child = subprocess.Popen([NODE, "--require", OBSERVER, CLI, *sys.argv[1:]])
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda s, _f: child.send_signal(s))
    code = child.wait()
    listener.close()
    sys.exit(code if code >= 0 else 128 - code)


if __name__ == "__main__":
    main()
