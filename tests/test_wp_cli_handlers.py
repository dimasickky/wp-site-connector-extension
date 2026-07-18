"""Tests for handlers_wp_cli.py — manage_plugin, purge_cache, run_wp_cli.

Covers the end-to-end wiring (handler + wp_cli_policy + wp_cli), not just the
pure policy unit tests in test_wp_cli_policy.py. In particular: the explicit
two-step confirm-flow (preview call does nothing, confirm=true call executes),
live-plugin-list validation (never trust an LLM-given slug), and that a
namespace/subcommand rejected by policy never reaches the SSH transport.
"""
import app  # noqa: F401
import handlers_wp_cli as hw
import storage
import wp_cli
from models import ManagePluginParams, PurgeCacheParams, RunWpCliParams


async def _ssh_ctx():
    from imperal_sdk.testing import MockContext
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "ssh-site", "name": "SSH Site", "url": "https://ssh-site.example",
        "username": "", "status": "connected", "auth_mode": "ssh",
    })
    await storage.set_ssh_cred(ctx, "ssh-site", {
        "host": "1.2.3.4", "port": 22, "user": "ubuntu", "wp_path": "/var/www/html",
        "password": "pw", "host_key": "1.2.3.4 ssh-ed25519 AAAATEST",
    })
    return ctx


_PLUGIN_ROWS = [
    {"name": "litespeed-cache", "status": "active", "version": "6.5", "update": "none", "update_version": ""},
    {"name": "rank-math-seo", "status": "active", "version": "25.1", "update": "none", "update_version": ""},
]


# ── manage_plugin ────────────────────────────────────────────────────────── #

async def test_manage_plugin_activate_runs_immediately_no_confirm_needed(monkeypatch):
    """'activate'/'update' aren't in _DESTRUCTIVE_PLUGIN_ACTIONS — run on first call."""
    ctx = await _ssh_ctx()

    async def _fake_list_plugins_cli(cred):
        return _PLUGIN_ROWS, None

    async def _fake_manage_plugin_cli(cred, plugin, action):
        assert plugin == "litespeed-cache"
        assert action == "activate"
        return "Plugin 'litespeed-cache' activated.", None

    monkeypatch.setattr(wp_cli, "list_plugins_cli", _fake_list_plugins_cli)
    monkeypatch.setattr(wp_cli, "manage_plugin_cli", _fake_manage_plugin_cli)
    r = await hw.manage_plugin(ctx, ManagePluginParams(site_id="ssh-site", plugin="litespeed-cache", action="activate"))
    assert r.status == "success"
    assert r.data.needs_confirmation is False


async def test_manage_plugin_deactivate_first_call_previews_without_executing(monkeypatch):
    ctx = await _ssh_ctx()
    executed = {"called": False}

    async def _fake_list_plugins_cli(cred):
        return _PLUGIN_ROWS, None

    async def _fake_manage_plugin_cli(cred, plugin, action):
        executed["called"] = True
        return "should not run", None

    monkeypatch.setattr(wp_cli, "list_plugins_cli", _fake_list_plugins_cli)
    monkeypatch.setattr(wp_cli, "manage_plugin_cli", _fake_manage_plugin_cli)
    r = await hw.manage_plugin(ctx, ManagePluginParams(site_id="ssh-site", plugin="litespeed-cache", action="deactivate"))
    assert r.status == "success"
    assert r.data.needs_confirmation is True
    assert executed["called"] is False  # nothing actually ran


async def test_manage_plugin_deactivate_confirmed_actually_executes(monkeypatch):
    ctx = await _ssh_ctx()
    executed = {"called": False}

    async def _fake_list_plugins_cli(cred):
        return _PLUGIN_ROWS, None

    async def _fake_manage_plugin_cli(cred, plugin, action):
        executed["called"] = True
        return "Plugin 'litespeed-cache' deactivated.", None

    monkeypatch.setattr(wp_cli, "list_plugins_cli", _fake_list_plugins_cli)
    monkeypatch.setattr(wp_cli, "manage_plugin_cli", _fake_manage_plugin_cli)
    r = await hw.manage_plugin(ctx, ManagePluginParams(
        site_id="ssh-site", plugin="litespeed-cache", action="deactivate", confirm=True))
    assert r.status == "success"
    assert r.data.needs_confirmation is False
    assert executed["called"] is True


async def test_manage_plugin_rejects_unknown_slug_not_in_live_list(monkeypatch):
    """Never trust an LLM-given slug — must be validated against the live list."""
    ctx = await _ssh_ctx()

    async def _fake_list_plugins_cli(cred):
        return _PLUGIN_ROWS, None

    monkeypatch.setattr(wp_cli, "list_plugins_cli", _fake_list_plugins_cli)
    r = await hw.manage_plugin(ctx, ManagePluginParams(site_id="ssh-site", plugin="totally-made-up-plugin", action="activate"))
    assert r.status == "error"
    assert "not installed" in r.error


async def test_manage_plugin_rejects_invalid_action():
    ctx = await _ssh_ctx()
    r = await hw.manage_plugin(ctx, ManagePluginParams(site_id="ssh-site", plugin="litespeed-cache", action="delete"))
    assert r.status == "error"


async def test_manage_plugin_requires_ssh_configured():
    from imperal_sdk.testing import MockContext
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "rest-only", "name": "REST Site", "url": "https://x",
                                        "username": "admin", "status": "connected"})
    r = await hw.manage_plugin(ctx, ManagePluginParams(site_id="rest-only", plugin="x", action="activate"))
    assert r.status == "error"


# ── purge_cache ──────────────────────────────────────────────────────────── #

async def test_purge_cache_detects_litespeed_and_purges(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_list_plugins_cli(cred):
        return _PLUGIN_ROWS, None

    async def _fake_run_wp_cli_cli(cred, namespace, args):
        assert namespace == "litespeed-purge"
        return "Cache purged.", None

    monkeypatch.setattr(wp_cli, "list_plugins_cli", _fake_list_plugins_cli)
    monkeypatch.setattr(wp_cli, "run_wp_cli_cli", _fake_run_wp_cli_cli)
    r = await hw.purge_cache(ctx, PurgeCacheParams(site_id="ssh-site"))
    assert r.status == "success"
    assert r.data.cache_plugin == "litespeed-cache"


async def test_purge_cache_no_cache_plugin_reports_clearly_not_silent_noop(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_list_plugins_cli(cred):
        return [{"name": "rank-math-seo", "status": "active", "version": "25.1", "update": "none", "update_version": ""}], None

    monkeypatch.setattr(wp_cli, "list_plugins_cli", _fake_list_plugins_cli)
    r = await hw.purge_cache(ctx, PurgeCacheParams(site_id="ssh-site"))
    assert r.status == "error"
    assert "No supported cache plugin" in r.error


async def test_purge_cache_rejects_invalid_scope():
    ctx = await _ssh_ctx()
    r = await hw.purge_cache(ctx, PurgeCacheParams(site_id="ssh-site", scope="tag"))
    assert r.status == "error"


# ── run_wp_cli ───────────────────────────────────────────────────────────── #

async def test_run_wp_cli_rejects_blocked_namespace_before_touching_ssh(monkeypatch):
    """eval must never even reach _require_ssh / the transport."""
    ctx = await _ssh_ctx()
    touched = {"ssh": False}

    async def _fake_run_wp_cli_cli(cred, namespace, args):
        touched["ssh"] = True
        return "should never run", None

    monkeypatch.setattr(wp_cli, "run_wp_cli_cli", _fake_run_wp_cli_cli)
    r = await hw.run_wp_cli(ctx, RunWpCliParams(site_id="ssh-site", namespace="eval", args=["1+1"]))
    assert r.status == "error"
    assert touched["ssh"] is False


async def test_run_wp_cli_non_destructive_call_runs_immediately(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_run_wp_cli_cli(cred, namespace, args):
        assert namespace == "transient"
        assert args == ["list"]
        return '[]', None

    monkeypatch.setattr(wp_cli, "run_wp_cli_cli", _fake_run_wp_cli_cli)
    r = await hw.run_wp_cli(ctx, RunWpCliParams(site_id="ssh-site", namespace="transient", args=["list"]))
    assert r.status == "success"
    assert r.data.needs_confirmation is False


async def test_run_wp_cli_destructive_subcommand_in_allowlisted_namespace_previews_first(monkeypatch):
    """`user set-role` — namespace 'user' is allowlisted, but the subcommand must
    still force destructive classification and require confirm=true."""
    ctx = await _ssh_ctx()
    executed = {"called": False}

    async def _fake_run_wp_cli_cli(cred, namespace, args):
        executed["called"] = True
        return "should not run", None

    monkeypatch.setattr(wp_cli, "run_wp_cli_cli", _fake_run_wp_cli_cli)
    r = await hw.run_wp_cli(ctx, RunWpCliParams(
        site_id="ssh-site", namespace="user", args=["set-role", "5", "administrator"]))
    assert r.status == "success"
    assert r.data.needs_confirmation is True
    assert executed["called"] is False


async def test_run_wp_cli_destructive_subcommand_confirmed_executes(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_run_wp_cli_cli(cred, namespace, args):
        return "User updated.", None

    monkeypatch.setattr(wp_cli, "run_wp_cli_cli", _fake_run_wp_cli_cli)
    r = await hw.run_wp_cli(ctx, RunWpCliParams(
        site_id="ssh-site", namespace="user", args=["set-role", "5", "administrator"], confirm=True))
    assert r.status == "success"
    assert r.data.needs_confirmation is False


async def test_run_wp_cli_strips_global_flags_before_reaching_transport(monkeypatch):
    """--path=/--allow-root etc. supplied by the caller must never reach the shell —
    they're stripped, not merely rejected."""
    ctx = await _ssh_ctx()
    seen_args = {}

    async def _fake_run_wp_cli_cli(cred, namespace, args):
        seen_args["args"] = args
        return "ok", None

    monkeypatch.setattr(wp_cli, "run_wp_cli_cli", _fake_run_wp_cli_cli)
    r = await hw.run_wp_cli(ctx, RunWpCliParams(
        site_id="ssh-site", namespace="transient", args=["list", "--path=/etc/passwd", "--allow-root"]))
    assert r.status == "success"
    assert "--path=/etc/passwd" not in seen_args["args"]
    assert "--allow-root" not in seen_args["args"]
    assert "list" in seen_args["args"]


async def test_run_wp_cli_requires_ssh_configured():
    from imperal_sdk.testing import MockContext
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "rest-only", "name": "REST Site", "url": "https://x",
                                        "username": "admin", "status": "connected"})
    r = await hw.run_wp_cli(ctx, RunWpCliParams(site_id="rest-only", namespace="transient", args=["list"]))
    assert r.status == "error"
