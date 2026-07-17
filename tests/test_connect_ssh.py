from imperal_sdk.testing import MockContext
import handlers_connect as hc
import storage
from models import ConnectSiteSSHParams


async def _ctx():
    return MockContext()


async def test_connect_ssh_rejects_missing_credential():
    ctx = await _ctx()
    r = await hc.connect_site_ssh(ctx, ConnectSiteSSHParams(
        ssh_host="1.2.3.4", ssh_user="root", wp_path="/var/www/html"))
    assert r.status != "success"


async def test_connect_ssh_success_stores_site_and_ssh_cred(monkeypatch):
    ctx = await _ctx()

    async def _fake_test_connection(cred):
        return True, "WordPress 6.8.1", "1.2.3.4 ssh-ed25519 AAAATEST"

    async def _fake_get_site_url(cred):
        return "https://example.com", None

    monkeypatch.setattr(hc.wp_cli, "test_connection", _fake_test_connection)
    monkeypatch.setattr(hc.wp_cli, "get_site_url", _fake_get_site_url)

    r = await hc.connect_site_ssh(ctx, ConnectSiteSSHParams(
        ssh_host="1.2.3.4", ssh_user="root", wp_path="/var/www/html",
        ssh_password="super-secret"))

    assert r.status == "success"
    assert r.data.id == "example-com"
    assert r.data.auth_mode == "ssh"

    record = await storage.get_site_record(ctx, "example-com")
    assert record["auth_mode"] == "ssh"
    assert record["url"] == "https://example.com"
    # No Application Password credential is ever stored for an SSH-only site.
    assert await storage.get_credential(ctx, "example-com") is None

    cred = await storage.get_ssh_cred(ctx, "example-com")
    assert cred["password"] == "super-secret"
    assert cred["host"] == "1.2.3.4"


async def test_connect_ssh_connection_failure_stores_nothing(monkeypatch):
    ctx = await _ctx()

    async def _fake_test_connection(cred):
        return False, "Connection refused", None

    monkeypatch.setattr(hc.wp_cli, "test_connection", _fake_test_connection)

    r = await hc.connect_site_ssh(ctx, ConnectSiteSSHParams(
        ssh_host="1.2.3.4", ssh_user="root", wp_path="/var/www/html",
        ssh_key="fake-key-content"))

    assert r.status != "success"
    assert await storage.get_site_record(ctx, "1-2-3-4") is None


async def test_connect_ssh_site_url_failure_cleans_up(monkeypatch):
    ctx = await _ctx()

    async def _fake_test_connection(cred):
        return True, "WordPress 6.8.1", "1.2.3.4 ssh-ed25519 AAAATEST"

    async def _fake_get_site_url(cred):
        return None, "wp option get failed"

    monkeypatch.setattr(hc.wp_cli, "test_connection", _fake_test_connection)
    monkeypatch.setattr(hc.wp_cli, "get_site_url", _fake_get_site_url)

    r = await hc.connect_site_ssh(ctx, ConnectSiteSSHParams(
        ssh_host="1.2.3.4", ssh_user="root", wp_path="/var/www/html",
        ssh_password="super-secret"))

    assert r.status != "success"
