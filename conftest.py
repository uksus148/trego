"""Keep Python tests offline apart from explicitly configured loopback services."""

import ipaddress
import socket

import pytest


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo
    gethostbyname, gethostbyname_ex = socket.gethostbyname, socket.gethostbyname_ex

    def check_host(host):
        if isinstance(host, bytes):
            host = host.decode("ascii")
        if host is None or host == "localhost":
            return
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if not local:
            pytest.fail("External network access is disabled in Python tests.")

    def guard_connect(operation):
        def guarded(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                check_host(address[0])
            return operation(sock, address)
        return guarded

    def guard_lookup(operation):
        def guarded(host, *args, **kwargs):
            check_host(host)
            return operation(host, *args, **kwargs)
        return guarded

    monkeypatch.setattr(socket.socket, "connect", guard_connect(connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard_connect(connect_ex))
    monkeypatch.setattr(socket, "getaddrinfo", guard_lookup(getaddrinfo))
    monkeypatch.setattr(socket, "gethostbyname", guard_lookup(gethostbyname))
    monkeypatch.setattr(socket, "gethostbyname_ex", guard_lookup(gethostbyname_ex))
