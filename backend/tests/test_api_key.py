"""
The guard on /ask.

It is the only endpoint that spends money, so it is the only one gated. The
key being optional matters as much as the key working: unset, everything
behaves as it did, which is what keeps local runs and the rest of this suite
free of configuration.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


def client(monkeypatch, key=None):
    if key is None:
        monkeypatch.delenv("READBASE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("READBASE_API_KEY", key)
    from app import main
    importlib.reload(main)
    # a handler that raises should come back as a response rather than escaping
    # the client: these tests care which requests are turned away, not whether
    # the database behind them happens to be current
    return TestClient(main.app, raise_server_exceptions=False), main


def test_no_key_configured_leaves_ask_open(monkeypatch):
    c, main = client(monkeypatch, None)
    assert main.API_KEY == ""
    # an empty question is rejected by the handler, not by the guard: reaching
    # that 400 is what proves the guard let it through
    assert c.post("/ask", json={"question": "  "}).status_code == 400


def test_key_configured_rejects_a_request_without_one(monkeypatch):
    c, _ = client(monkeypatch, "s3cret")
    r = c.post("/ask", json={"question": "anything"})
    assert r.status_code == 401
    assert "key" in r.json()["detail"].lower()


def test_key_configured_rejects_the_wrong_one(monkeypatch):
    c, _ = client(monkeypatch, "s3cret")
    r = c.post("/ask", json={"question": "anything"},
               headers={"X-Readbase-Key": "not-it"})
    assert r.status_code == 401


def test_the_right_key_gets_through_to_the_handler(monkeypatch):
    c, _ = client(monkeypatch, "s3cret")
    r = c.post("/ask", json={"question": "  "},
               headers={"X-Readbase-Key": "s3cret"})
    assert r.status_code == 400  # past the guard, stopped by the empty question


def test_reading_endpoints_stay_open_when_a_key_is_set(monkeypatch):
    c, _ = client(monkeypatch, "s3cret")
    # the guard exists to cap spend, not to hide the corpus. What matters is
    # that a read is never turned away for want of a key, whether it then
    # succeeds depends on the database this happens to run against, which is
    # not what this test is about.
    assert c.get("/stats", headers={}).status_code != 401


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    yield
    monkeypatch.delenv("READBASE_API_KEY", raising=False)
    from app import main
    importlib.reload(main)
