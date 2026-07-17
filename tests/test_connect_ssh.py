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


# ── Private key normalization (the classic "pasted key breaks" bug) ───────────

_VALID_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)


async def test_connect_ssh_rejects_mangled_key_before_attempting_ssh(monkeypatch):
    """A key pasted with no BEGIN/END markers at all must be rejected immediately,
    with wp_cli.test_connection never even called — fail fast with a clear
    message, not a 15s ssh timeout ending in an opaque libcrypto error."""
    ctx = await _ctx()
    called = {"test_connection": False}

    async def _fake_test_connection(cred):
        called["test_connection"] = True
        return True, "WordPress 6.8.1", "1.2.3.4 ssh-ed25519 AAAATEST"

    monkeypatch.setattr(hc.wp_cli, "test_connection", _fake_test_connection)
    r = await hc.connect_site_ssh(ctx, ConnectSiteSSHParams(
        ssh_host="1.2.3.4", ssh_user="root", wp_path="/var/www/html",
        ssh_key="totally not a key"))

    assert r.status != "success"
    assert not called["test_connection"]
    assert "private key" in r.error.lower()


async def test_connect_ssh_repairs_literal_backslash_n_key_and_connects(monkeypatch):
    """The classic form-paste bug — real line breaks collapsed into literal '\\n'
    text — is auto-repaired, and the REPAIRED key (not the mangled original) is
    what gets stored and what would be handed to ssh."""
    ctx = await _ctx()
    seen = {}

    async def _fake_test_connection(cred):
        seen["key"] = cred.get("key")
        return True, "WordPress 6.8.1", "1.2.3.4 ssh-ed25519 AAAATEST"

    async def _fake_get_site_url(cred):
        return "https://example.com", None

    monkeypatch.setattr(hc.wp_cli, "test_connection", _fake_test_connection)
    monkeypatch.setattr(hc.wp_cli, "get_site_url", _fake_get_site_url)

    mangled_key = _VALID_KEY.replace("\n", "\\n")
    r = await hc.connect_site_ssh(ctx, ConnectSiteSSHParams(
        ssh_host="1.2.3.4", ssh_user="root", wp_path="/var/www/html", ssh_key=mangled_key))

    assert r.status == "success"
    assert "\\n" not in seen["key"]
    assert "-----BEGIN OPENSSH PRIVATE KEY-----\n" in seen["key"]

    cred = await storage.get_ssh_cred(ctx, "example-com")
    assert "\\n" not in cred["key"]
    assert cred["key"].endswith("\n")
