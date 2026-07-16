import wp_cli


def test_ssh_cmd_with_pinned_host_key_uses_strict_checking():
    cmd = wp_cli._ssh_cmd("1.2.3.4", 22, "root", "/tmp/key", "echo hi",
                          known_hosts_path="/tmp/known_hosts")
    joined = " ".join(cmd)
    assert "StrictHostKeyChecking=yes" in joined
    assert "UserKnownHostsFile=/tmp/known_hosts" in joined
    assert "StrictHostKeyChecking=no" not in joined


def test_ssh_cmd_without_pinned_key_uses_accept_new_not_disabled():
    # Legacy credentials without a pinned host_key must still verify —
    # accept-new trusts first contact but rejects a later CHANGED key,
    # unlike the old StrictHostKeyChecking=no which trusted blindly forever.
    cmd = wp_cli._ssh_cmd("1.2.3.4", 22, "root", "/tmp/key", "echo hi",
                          known_hosts_path=None)
    joined = " ".join(cmd)
    assert "StrictHostKeyChecking=accept-new" in joined
    assert "StrictHostKeyChecking=no" not in joined


async def test_scan_host_key_returns_none_on_missing_binary(monkeypatch):
    async def _raise(*a, **kw):
        raise FileNotFoundError()
    monkeypatch.setattr(wp_cli.asyncio, "create_subprocess_exec", _raise)
    key, err = await wp_cli.scan_host_key("1.2.3.4", 22)
    assert key is None
    assert "ssh-keyscan" in err


def test_ssh_cmd_password_auth_enables_prompt_without_exposing_password():
    cmd = wp_cli._ssh_cmd("1.2.3.4", 22, "root", None, "echo hi",
                          known_hosts_path="/tmp/known_hosts", password_auth=True)
    joined = " ".join(cmd)
    assert "BatchMode=no" in joined
    assert "PreferredAuthentications=password,keyboard-interactive" in joined
    assert "PubkeyAuthentication=no" in joined
    assert "StrictHostKeyChecking=yes" in joined
    assert "super-secret" not in joined


async def test_askpass_helper_contains_no_password():
    async with wp_cli._askpass_file(True) as path:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "IMPERAL_SSH_PASSWORD" in content
        assert "super-secret" not in content


async def test_connection_accepts_password_and_keeps_pinned_host_key(monkeypatch):
    calls = []

    async def _run(*args, **kwargs):
        calls.append((args, kwargs))
        return "6.8.1", None

    monkeypatch.setattr(wp_cli, "_run", _run)
    cred = {
        "host": "1.2.3.4", "port": 22, "user": "root",
        "wp_path": "/var/www/html", "password": "super-secret",
        "host_key": "1.2.3.4 ssh-ed25519 AAAATEST",
    }
    ok, message, host_key = await wp_cli.test_connection(cred)

    assert ok is True
    assert message == "WordPress 6.8.1"
    assert host_key == cred["host_key"]
    assert calls[0][1]["password"] == "super-secret"
    assert calls[0][1]["known_hosts_path"]


async def test_get_server_info_accepts_password(monkeypatch):
    calls = []

    async def _run(*args, **kwargs):
        calls.append(kwargs)
        return "", None

    monkeypatch.setattr(wp_cli, "_run", _run)
    result = await wp_cli.get_server_info({
        "host": "1.2.3.4", "port": 22, "user": "root",
        "wp_path": "/var/www/html", "password": "super-secret",
        "host_key": "1.2.3.4 ssh-ed25519 AAAATEST",
    })

    assert "error" not in result
    assert len(calls) == 7
    assert all(call["password"] == "super-secret" for call in calls)
    assert all(call["known_hosts_path"] for call in calls)
