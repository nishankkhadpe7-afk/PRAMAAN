import time
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from Pramaan.backend import app as appmod, accounts, security
    monkeypatch.setattr(appmod, "ROOT", tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", tmp_path / "p1.sqlite3")
    monkeypatch.setattr(appmod, "VAULT", tmp_path / "vault")
    monkeypatch.delenv("PRAMAAN_VAULT_KEY", raising=False)
    monkeypatch.delenv("PRAMAAN_VAULT_KEY_FILE", raising=False)
    appmod._LOGIN_ATTEMPTS.clear()
    return accounts, TestClient(appmod.app), security


PW = "Correct-Horse-91!"


def _code(accounts, secret, offset=0):
    return accounts.totp(secret, int(time.time()) // 30 + offset)


def test_login_flow_and_logout(env):
    accounts, client, _ = env
    assert client.get("/auth/methods").json()["accounts"] is False
    secret, uri = accounts.add_user("asha", "auditor", PW)
    assert uri.startswith("otpauth://totp/")
    assert client.get("/auth/methods").json()["accounts"] is True
    r = client.post("/auth/login", json={"username": "asha", "password": PW, "code": _code(accounts, secret)})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/p4/identity", headers=h).status_code == 200
    # same code cannot be replayed
    r2 = client.post("/auth/login", json={"username": "asha", "password": PW, "code": _code(accounts, secret)})
    assert r2.status_code == 401
    assert client.post("/auth/logout", headers=h).status_code == 200
    assert client.get("/p4/identity", headers=h).status_code == 401


def test_generic_errors_lockout_disable(env):
    accounts, client, _ = env
    secret, _ = accounts.add_user("ravi", "client_employee", PW)
    bad = [client.post("/auth/login", json={"username": u, "password": p, "code": "000000"})
           for u, p in (("nobody", PW), ("ravi", "wrong-password-xx"))]
    assert {b.status_code for b in bad} == {401}
    assert bad[0].json() == bad[1].json()
    for _ in range(4):
        client.post("/auth/login", json={"username": "ravi", "password": "nope-nope-nope", "code": "1"})
    r = client.post("/auth/login", json={"username": "ravi", "password": PW, "code": _code(accounts, secret)})
    assert r.status_code == 401  # locked after 5 failures
    accounts.unlock("ravi")
    accounts.disable("ravi")
    r = client.post("/auth/login", json={"username": "ravi", "password": PW, "code": _code(accounts, secret, 1)})
    assert r.status_code == 401


def test_weak_password_and_rate_limit(env):
    accounts, client, _ = env
    with pytest.raises(ValueError):
        accounts.add_user("meera", "client_employee", "short")
    codes = [client.post("/auth/login", json={"username": "x", "password": "y", "code": "1"}).status_code for _ in range(11)]
    assert codes[-1] == 429


def test_launcher_tokens_still_work(env):
    _, client, security = env
    token = security.issue("demo", "auditor", ttl=600)
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/p4/identity", headers=h).status_code == 200
    assert client.post("/auth/logout", headers=h).json()["revoked"] is False
    assert client.get("/p4/identity", headers=h).status_code == 200
