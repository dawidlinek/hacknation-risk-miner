"""LLM tests: fake mode (recorded cassettes), llm_call rows in memory, and a guard that fails any test opening a
connection to a model provider (Gemini or the vLLM tunnel ports)."""
from __future__ import annotations

import os
import socket

import pytest

os.environ["RISKMINER_LLM_FAKE"] = "1"
os.environ["RISKMINER_LLM_LOG"] = "memory"
os.environ.pop("RISKMINER_LLM_RECORD", None)

_BLOCKED_PORTS = {8001, 8002}
_BLOCKED_HOSTS = ("googleapis.com", "generativelanguage")
_real_connect = socket.socket.connect
_real_getaddrinfo = socket.getaddrinfo


def _guard_connect(self, address):
    if isinstance(address, tuple) and len(address) >= 2 and address[1] in _BLOCKED_PORTS:
        raise AssertionError(f"test tried to reach a model port {address}")
    return _real_connect(self, address)


def _guard_getaddrinfo(host, *a, **kw):
    if isinstance(host, str) and any(h in host for h in _BLOCKED_HOSTS):
        raise AssertionError(f"test tried to resolve a model host {host}")
    return _real_getaddrinfo(host, *a, **kw)


@pytest.fixture(autouse=True)
def _no_model_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _guard_connect)
    monkeypatch.setattr(socket, "getaddrinfo", _guard_getaddrinfo)
    from riskminer.llm import calllog, gateway, routing

    async def _public_refs(doc_ids, codes):          # unit tests never read the DB; tests override when needed
        return []
    monkeypatch.setattr(gateway, "_ref_labels", _public_refs)
    calllog.MEMORY.clear()
    calllog._spent_cache.clear()
    routing.HEALTH.clear()
    yield
