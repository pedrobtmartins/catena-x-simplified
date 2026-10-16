import pytest
import scenario
from fakes import FakeReader, FakeRegistry
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from catenax_simplified.admin import AdminAuth, SecretBox, hash_password, verify_password
from catenax_simplified.admin import security as security_module
from catenax_simplified.api import create_app
from catenax_simplified.config import Settings

PASSWORD = "correct horse battery"
HASH = hash_password(PASSWORD)
KEY = "k" * 40
OTHER_KEY = "o" * 40
NEW = "BPNL0000000NEW1A"


def test_password_hash():
    assert HASH.startswith("scrypt:") and "$" not in HASH
    assert verify_password(PASSWORD, HASH)
    assert not verify_password("wrong", HASH)
    assert not verify_password(PASSWORD, "garbage")
    assert hash_password(PASSWORD) != HASH  # salted


def test_session_tokens(monkeypatch):
    auth = AdminAuth("admin", HASH, KEY, session_hours=8)
    token = auth.login("1.2.3.4", "admin", PASSWORD)
    assert auth.user(token) == "admin"
    assert auth.user(token[:-2] + "xx") is None  # tampered
    assert AdminAuth("admin", HASH, OTHER_KEY, 8).user(token) is None  # another key
    assert auth.user(None) is None
    now = security_module.time.time()
    monkeypatch.setattr(security_module.time, "time", lambda: now + 8 * 3600 + 1)
    assert auth.user(token) is None  # expired


def test_lockout_after_failed_sign_ins():
    auth = AdminAuth("admin", HASH, KEY, session_hours=8)
    for _ in range(AdminAuth.MAX_FAILURES):
        assert auth.login("1.2.3.4", "admin", "wrong") is None
    assert auth.locked_out("1.2.3.4")
    assert not auth.locked_out("5.6.7.8")
    assert auth.login("1.2.3.4", "someone", PASSWORD) is None  # right password, wrong user


def test_secret_box():
    box = SecretBox(KEY)
    token = box.encrypt("s3cret")
    assert "s3cret" not in token
    assert box.decrypt(token) == "s3cret"
    assert SecretBox(OTHER_KEY).decrypt(token) is None


def _app(tmp_path, **overrides):
    values = {
        "own_bpnl": scenario.TIER1,
        "database_url": f"sqlite:///{tmp_path}/app.db",
        "admin_password_hash": HASH,
        "secret_key": KEY,
    }
    settings = Settings(**{**values, **overrides})
    return create_app(
        settings, registry=FakeRegistry(scenario.shells()), reader=FakeReader(scenario.payloads())
    )


def _login(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200
    return response


def test_without_admin_login_everything_stays_as_before(tmp_path):
    with TestClient(_app(tmp_path, admin_password_hash=None, secret_key=None)) as client:
        assert client.get("/api/auth/me").json() == {
            "login_enabled": False,
            "admin": None,
            "config_editable": False,
        }
        assert client.put(f"/api/partners/{NEW}", json={"name": "x"}).status_code == 200
        assert client.get("/api/setup/config").status_code == 503
        response = client.post("/api/auth/login", json={"username": "admin", "password": "x"})
        assert response.status_code == 503


def test_partners_need_an_admin_once_login_is_set_up(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert client.put(f"/api/partners/{NEW}", json={"name": "x"}).status_code == 401
        assert client.delete(f"/api/partners/{NEW}").status_code == 401
        assert client.get("/api/partners").status_code == 200  # reading stays open

        response = client.post("/api/auth/login", json={"username": "admin", "password": "no"})
        assert response.status_code == 401
        cookie = _login(client).headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert client.get("/api/auth/me").json()["admin"] == "admin"
        assert client.put(f"/api/partners/{NEW}", json={"name": "x"}).status_code == 200

        client.post("/api/auth/logout")
        assert client.get("/api/auth/me").json()["admin"] is None
        assert client.put(f"/api/partners/{NEW}", json={"name": "y"}).status_code == 401


def test_sign_in_is_locked_after_repeated_failures(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        for _ in range(AdminAuth.MAX_FAILURES):
            client.post("/api/auth/login", json={"username": "admin", "password": "no"})
        response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        assert response.status_code == 429


def _fields(client):
    return {f["key"]: f for f in client.get("/api/setup/config").json()}


def test_configuration_entered_in_the_ui_applies_at_once(tmp_path):
    management = "https://edc.example.com"
    with TestClient(_app(tmp_path, dtr_base_url="https://dtr.from-deploy")) as client:
        assert client.get("/api/setup/config").status_code == 401
        _login(client)
        assert client.get("/api/auth/me").json()["config_editable"] is True
        fields = _fields(client)
        assert (fields["dtr_base_url"]["source"], fields["dtr_base_url"]["locked"]) == (
            "deploy",
            True,
        )
        assert fields["dtr_base_url"]["value"] == "https://dtr.from-deploy"
        assert client.get("/api/health").json()["edc_configured"] is False

        saved = client.put(
            "/api/setup/config",
            json={"values": {"edc_management_url": management, "edc_api_key": " s3cret "}},
        ).json()
        assert {c["key"] for c in saved["checks"]} >= {"dtr", "edc"}
        fields = {f["key"]: f for f in saved["fields"]}
        assert fields["edc_management_url"] | {"updated_at": None} == fields[
            "edc_management_url"
        ] | {
            "source": "app",
            "value": management,
            "is_set": True,
            "updated_by": "admin",
            "updated_at": None,
        }
        # Secrets are never returned.
        assert (fields["edc_api_key"]["value"], fields["edc_api_key"]["is_set"]) == (None, True)
        health = client.get("/api/health").json()
        assert (health["edc_configured"], health["edc_auth"]) == (True, ["api_key"])
        # The sync still uses the injected registry after the rebuild.
        assert client.post("/api/sync").json()["complete"] is True

        # Removing a value takes effect at once too.
        client.put("/api/setup/config", json={"values": {"edc_management_url": None}})
        assert client.get("/api/health").json()["edc_configured"] is False

    raw = create_engine(f"sqlite:///{tmp_path}/app.db").connect()
    stored = dict(raw.execute(text("select key, value from config_values")).all())
    assert "edc_management_url" not in stored
    assert stored["edc_api_key"] != "s3cret" and "s3cret" not in stored["edc_api_key"]


def test_invalid_changes_are_refused(tmp_path):
    with TestClient(_app(tmp_path, dtr_base_url="https://dtr.from-deploy")) as client:
        _login(client)
        for values, message in (
            ({"dtr_base_url": "https://other"}, "set by the deployment (CXS_DTR_BASE_URL)"),
            ({"own_bpnl": "BPNL000000000XXX"}, "not a setting that can be entered here"),
            ({"edc_management_url": "edc.example.com"}, "must start with http"),
            ({"bp_explorer_bpnl": "BPNLCOFINITY"}, "must be a BPNL"),
        ):
            response = client.put("/api/setup/config", json={"values": values})
            assert response.status_code == 422
            assert message in response.json()["detail"]
        assert all(f["source"] != "app" for f in _fields(client).values())


def test_keycloak_from_the_deployment_locks_the_token_url(tmp_path):
    with TestClient(_app(tmp_path, oauth_url="https://kc.example/auth/")) as client:
        _login(client)
        assert _fields(client)["oauth_token_url"]["locked"] is True


def test_stored_settings_survive_a_restart_but_not_a_new_key(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _login(client)
        client.put(
            "/api/setup/config",
            json={
                "values": {
                    "edc_management_url": "https://edc.example.com",
                    "edc_api_key": "s3cret",
                }
            },
        )
    with TestClient(_app(tmp_path)) as client:
        assert client.get("/api/health").json()["edc_auth"] == ["api_key"]
    with TestClient(_app(tmp_path, secret_key=OTHER_KEY)) as client:
        health = client.get("/api/health").json()
        assert (health["edc_configured"], health["edc_auth"]) == (True, [])
        _login(client)
        assert _fields(client)["edc_api_key"]["unreadable"] is True


@pytest.mark.parametrize("key", ["short", ""])
def test_secret_key_must_be_long(key):
    with pytest.raises(ValueError):
        Settings(own_bpnl=scenario.TIER1, secret_key=key)


def test_command_line_tools(monkeypatch, capsys):
    from catenax_simplified.admin.__main__ import main

    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert main(["admin", "hash-password"]) == 0
    assert verify_password(PASSWORD, capsys.readouterr().out.strip())

    monkeypatch.setattr("getpass.getpass", lambda prompt="": "short")
    assert main(["admin", "hash-password"]) == 1

    assert main(["admin", "secret-key"]) == 0
    assert len(capsys.readouterr().out.strip()) >= 32


def test_concurrent_reloads_leave_one_set_of_background_tasks(tmp_path):
    import asyncio

    app = _app(tmp_path, sync_interval_seconds=3600)
    runtime = app.state.runtime

    async def scenario_():
        runtime.start()
        await asyncio.gather(runtime.reload(), runtime.reload(), runtime.reload())
        alive = [t for t in runtime._tasks if not t.done()]
        await runtime.stop()
        return len(alive)

    assert asyncio.run(scenario_()) == 1  # the periodic sync only


def test_names_from_the_business_partner_explorer_entered_in_the_ui(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _login(client)
        explorer = {"bp_explorer_address": "https://bpe.example/api/v1/dsp"}
        saved = client.put("/api/setup/config", json={"values": explorer}).json()
        checks = {c["key"]: c for c in saved["checks"]}
        assert checks["bp_explorer"]["detail"] == "needs your EDC (CXS_EDC_MANAGEMENT_URL)"
        assert client.get("/api/health").json()["can_look_up_names"] is False

        client.put(
            "/api/setup/config", json={"values": {"edc_management_url": "https://edc.example"}}
        )
        health = client.get("/api/health").json()
        assert (health["can_look_up_names"], health["names_source"]) == (
            True,
            "Business Partner Explorer",
        )
        assert _fields(client)["bp_explorer_bpnl"]["value"] == "BPNLCOFINITYEZFA"
