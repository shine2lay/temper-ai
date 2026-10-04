#!/usr/local/bin/python3
"""Worker side of the login handoff (runs inside the worker box).

Pi runs this as the models.json apiKey command
("!/usr/local/bin/python3 -B /box/handoff_client.py <provider>") before a model request. It
asks the host, over the bind-mounted Unix socket /box-sock/handoff.sock, for the current
access token. The host checks the turn's allowance and asks the host Pi installation, the
single owner of the login and its refresh:
    pi auth print-bearer-token --provider <provider> --min-expiry 30m
The token is written to stdout for Pi and never stored. An empty answer exits 1, so the
request fails before any provider call. This file logs nothing.
"""
import socket
import sys


def main():
    provider = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(60)
        s.connect("/box-sock/handoff.sock")
        s.sendall(provider.encode() + b"\n")
        chunks = []
        while data := s.recv(65536):
            chunks.append(data)
        s.close()
    except OSError:
        return 2
    token = b"".join(chunks).strip()
    if not token:
        return 1
    sys.stdout.buffer.write(token)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
