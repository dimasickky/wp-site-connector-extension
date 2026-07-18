"""Tests that every read function actually goes through WP-CLI over SSH for an
SSH-only connected site (auth_mode='ssh', no Application Password stored) —
previously these all hard-required a REST credential and returned "Stored
credential is missing" for a real SSH-only site, silently ignoring the whole
point of connecting it via SSH."""
import app  # noqa: F401
import handlers_read as hr
import storage
import wp_cli
from models import (ListContentParams, ListMediaParams, SiteIdParams,
                    ListCommentsParams, ListCustomPostsParams)


async def _ssh_ctx():
    from imperal_sdk.testing import MockContext
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "ssh-site", "name": "SSH Site", "url": "https://ssh-site.example",
        "username": "", "status": "connected", "auth_mode": "ssh",
    })
    await storage.set_ssh_cred(ctx, "ssh-site", {
        "host": "1.2.3.4", "port": 22, "user": "root", "wp_path": "/var/www/html",
        "password": "pw", "host_key": "1.2.3.4 ssh-ed25519 AAAATEST",
    })
    return ctx


async def test_list_posts_uses_wp_cli_for_ssh_site(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_list_content_cli(cred, post_type="post", limit=20, search=None,
                                     status=None, orderby=None, order=None):
        assert post_type == "post"
        return [{"ID": "1", "post_title": "Hello", "post_status": "publish",
                 "guid": "https://ssh-site.example/hello", "post_date": "2026-07-01"}], None

    monkeypatch.setattr(wp_cli, "list_content_cli", _fake_list_content_cli)
    r = await hr.list_posts(ctx, ListContentParams(site_id="ssh-site"))
    assert r.status == "success"
    assert r.data.items[0].title == "Hello"
    assert r.data.items[0].link == "https://ssh-site.example/hello"


async def test_list_pages_uses_wp_cli_with_post_type_page(monkeypatch):
    ctx = await _ssh_ctx()
    seen = {}

    async def _fake_list_content_cli(cred, post_type="post", limit=20, search=None,
                                     status=None, orderby=None, order=None):
        seen["post_type"] = post_type
        return [{"ID": "2", "post_title": "About", "post_status": "publish",
                 "guid": "https://ssh-site.example/about"}], None

    monkeypatch.setattr(wp_cli, "list_content_cli", _fake_list_content_cli)
    r = await hr.list_pages(ctx, ListContentParams(site_id="ssh-site"))
    assert r.status == "success"
    assert seen["post_type"] == "page"
    assert r.data.items[0].title == "About"


async def test_list_media_uses_wp_cli_with_post_type_attachment(monkeypatch):
    ctx = await _ssh_ctx()
    seen = {}

    async def _fake_list_content_cli(cred, post_type="post", limit=20, search=None,
                                     status=None, orderby=None, order=None):
        seen["post_type"] = post_type
        return [{"ID": "3", "post_title": "photo.jpg", "guid": "https://x/photo.jpg",
                 "post_mime_type": "image/jpeg"}], None

    monkeypatch.setattr(wp_cli, "list_content_cli", _fake_list_content_cli)
    r = await hr.list_media(ctx, ListMediaParams(site_id="ssh-site"))
    assert r.status == "success"
    assert seen["post_type"] == "attachment"
    assert r.data.items[0].mime_type == "image/jpeg"


async def test_get_site_health_uses_wp_cli_test_connection_and_counts(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_test_connection(cred):
        return True, "WordPress 6.8.1", None

    async def _fake_count_posts_cli(cred, post_type="post"):
        return {"post": 12, "page": 3, "attachment": 5}[post_type], None

    monkeypatch.setattr(wp_cli, "test_connection", _fake_test_connection)
    monkeypatch.setattr(wp_cli, "count_posts_cli", _fake_count_posts_cli)
    r = await hr.get_site_health(ctx, SiteIdParams(site_id="ssh-site"))
    assert r.status == "success"
    assert r.data.reachable is True
    assert r.data.auth_ok is True
    assert r.data.content_counts == {"posts": 12, "pages": 3, "media": 5}


async def test_refresh_site_uses_wp_cli_test_connection(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_test_connection(cred):
        return True, "WordPress 6.8.1", None

    monkeypatch.setattr(wp_cli, "test_connection", _fake_test_connection)
    r = await hr.refresh_site(ctx, SiteIdParams(site_id="ssh-site"))
    assert r.status == "success"
    assert r.data.status == "connected"

    record = await storage.get_site_record(ctx, "ssh-site")
    assert record["status"] == "connected"


async def test_refresh_site_marks_error_when_ssh_fails(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_test_connection(cred):
        return False, "Connection refused", None

    monkeypatch.setattr(wp_cli, "test_connection", _fake_test_connection)
    r = await hr.refresh_site(ctx, SiteIdParams(site_id="ssh-site"))
    assert r.data.status == "error"


async def test_refresh_all_sites_handles_mixed_rest_and_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    await storage.save_site_record(ctx, {"id": "rest-site", "name": "REST Site",
                                        "url": "https://rest-site.example",
                                        "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "rest-site", "pw")
    ctx.http.mock_get("https://rest-site.example/wp-json/wp/v2/users/me", {"id": 1}, 200)

    async def _fake_test_connection(cred):
        return True, "WordPress 6.8.1", None

    monkeypatch.setattr(wp_cli, "test_connection", _fake_test_connection)
    r = await hr.refresh_all_sites(ctx, None)
    assert r.status == "success"
    assert r.data.connected == 2
    assert r.data.total == 2


async def test_list_comments_uses_wp_cli_and_maps_status(monkeypatch):
    ctx = await _ssh_ctx()
    seen = {}

    async def _fake_list_comments_cli(cred, status="hold", limit=20):
        seen["status"] = status
        return [{"comment_ID": "9", "comment_author": "Bob",
                 "comment_content": "<p>Nice post!</p>", "comment_post_ID": "1",
                 "comment_date": "2026-07-01", "comment_approved": "0"}], None

    monkeypatch.setattr(wp_cli, "list_comments_cli", _fake_list_comments_cli)
    r = await hr.list_comments(ctx, ListCommentsParams(site_id="ssh-site", status="hold"))
    assert r.status == "success"
    assert seen["status"] == "hold"
    assert r.data.items[0].author == "Bob"
    assert r.data.items[0].status == "hold"
    assert "Nice post!" in r.data.items[0].snippet


async def test_list_scheduled_uses_wp_cli_with_future_status(monkeypatch):
    ctx = await _ssh_ctx()
    seen = {}

    async def _fake_list_content_cli(cred, post_type="post", limit=20, search=None,
                                     status=None, orderby=None, order=None):
        seen["status"] = status
        return [{"ID": "5", "post_title": "Future post", "guid": "https://x/future",
                 "post_date": "2026-08-01"}], None

    monkeypatch.setattr(wp_cli, "list_content_cli", _fake_list_content_cli)
    r = await hr.list_scheduled(ctx, ListContentParams(site_id="ssh-site"))
    assert r.status == "success"
    assert seen["status"] == "future"
    assert r.data.items[0].status == "scheduled"


async def test_list_users_uses_wp_cli(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_list_users_cli(cred, limit=20, search=None):
        return [{"ID": "2", "user_login": "jane", "display_name": "Jane Doe",
                 "roles": "administrator", "user_registered": "2026-01-01 00:00:00"}], None

    monkeypatch.setattr(wp_cli, "list_users_cli", _fake_list_users_cli)
    r = await hr.list_users(ctx, ListContentParams(site_id="ssh-site"))
    assert r.status == "success"
    assert r.data.items[0].title == "Jane Doe"
    assert r.data.items[0].role == "administrator"


async def test_list_orders_uses_wp_cli(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_list_orders_cli(cred, limit=20):
        return [{"id": "77", "status": "processing", "total": "49.99", "currency": "USD"}], None

    monkeypatch.setattr(wp_cli, "list_orders_cli", _fake_list_orders_cli)
    r = await hr.list_orders(ctx, ListMediaParams(site_id="ssh-site"))
    assert r.status == "success"
    assert r.data.items[0].total == "49.99"


async def test_list_orders_wp_cli_error_surfaces_woocommerce_message(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_list_orders_cli(cred, limit=20):
        return None, "WooCommerce is not installed on this site."

    monkeypatch.setattr(wp_cli, "list_orders_cli", _fake_list_orders_cli)
    r = await hr.list_orders(ctx, ListMediaParams(site_id="ssh-site"))
    assert r.status == "error"
    assert "WooCommerce" in r.error


async def test_list_custom_posts_uses_wp_cli_with_given_post_type(monkeypatch):
    ctx = await _ssh_ctx()
    seen = {}

    async def _fake_list_content_cli(cred, post_type="post", limit=20, search=None,
                                     status=None, orderby=None, order=None):
        seen["post_type"] = post_type
        return [{"ID": "8", "post_title": "Widget", "guid": "https://x/widget"}], None

    monkeypatch.setattr(wp_cli, "list_content_cli", _fake_list_content_cli)
    r = await hr.list_custom_posts(ctx, ListCustomPostsParams(site_id="ssh-site", post_type="products"))
    assert r.status == "success"
    assert seen["post_type"] == "products"
    assert r.data.items[0].title == "Widget"


async def test_list_plugins_uses_wp_cli(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_list_plugins_cli(cred):
        return [
            {"name": "rank-math-seo", "status": "active", "version": "25.1", "update": "none", "update_version": ""},
            {"name": "litespeed-cache", "status": "active", "version": "6.5", "update": "available", "update_version": "6.6"},
        ], None

    monkeypatch.setattr(wp_cli, "list_plugins_cli", _fake_list_plugins_cli)
    r = await hr.list_plugins(ctx, SiteIdParams(site_id="ssh-site"))
    assert r.status == "success"
    assert len(r.data.items) == 2
    assert r.data.items[0].title == "rank-math-seo"
    assert r.data.items[0].status == "active"
    assert r.data.items[0].update_available == ""
    assert r.data.items[1].update_available == "6.6"


async def test_list_plugins_wp_cli_error_surfaces(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_list_plugins_cli(cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(wp_cli, "list_plugins_cli", _fake_list_plugins_cli)
    r = await hr.list_plugins(ctx, SiteIdParams(site_id="ssh-site"))
    assert r.status == "error"
    assert "SSH connection failed" in r.error


async def test_list_plugins_requires_ssh_configured():
    """No SSH cred stored at all (e.g. Application-Password-only site) — must fail
    with a clear, actionable message, never crash trying to reach REST (there is
    no REST fallback for plugin listing)."""
    from imperal_sdk.testing import MockContext
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "rest-only", "name": "REST Site", "url": "https://x",
                                        "username": "admin", "status": "connected"})
    r = await hr.list_plugins(ctx, SiteIdParams(site_id="rest-only"))
    assert r.status == "error"
    assert "SSH not configured" in r.error


async def test_ssh_site_still_errors_cleanly_if_ssh_cred_missing():
    """Site record says auth_mode=ssh but the credential doc is gone (edge case) —
    must fail with a clear message, never crash or silently fall through to REST."""
    from imperal_sdk.testing import MockContext
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "broken-ssh", "name": "Broken", "url": "https://x",
                                        "username": "", "status": "connected", "auth_mode": "ssh"})
    r = await hr.list_posts(ctx, ListContentParams(site_id="broken-ssh"))
    assert r.status == "error"
    assert "SSH credential" in r.error
