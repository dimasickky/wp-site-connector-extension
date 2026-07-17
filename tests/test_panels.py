from imperal_sdk.testing import MockContext
import app  # noqa: F401 — registers ext/chat
import panels
import storage


async def _ctx_with_sites(*site_records):
    ctx = MockContext()
    for r in site_records:
        await storage.save_site_record(ctx, r)
    return ctx


# ── sidebar ───────────────────────────────────────────────────────────────────

async def test_sidebar_empty_state():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "Connect via Password" in s
    assert "Connect via SSH" in s
    assert "Divider" in s
    assert "No sites" in s


async def test_sidebar_renders_site_list():
    ctx = await _ctx_with_sites(
        {"id": "a-com", "name": "A", "url": "https://a.com", "status": "connected"},
        {"id": "b-com", "name": "B", "url": "https://b.com", "status": "error"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "a.com" in s
    assert "b.com" in s
    assert "List" in s


async def test_sidebar_connect_button_at_top():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    s = str(node)
    assert s.index("Connect via Password") < s.index("Divider")


async def test_sidebar_divider_present():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    assert "Divider" in str(node)


async def test_sidebar_connect_button_calls_center_with_connect_view():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "__panel__center" in s
    assert "connect" in s


async def test_sidebar_site_click_calls_center_with_site_id():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "__panel__center" in s
    assert "x-com" in s


async def test_sidebar_auto_action_set_when_sites_exist():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    assert hasattr(node, "props") and "auto_action" in node.props


async def test_sidebar_no_auto_action_when_active_site():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx, active_site_id="x-com")
    assert not (hasattr(node, "props") and "auto_action" in node.props)


async def test_sidebar_no_auto_action_when_no_sites():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    assert not (hasattr(node, "props") and "auto_action" in node.props)


async def test_sidebar_item_has_refresh_and_remove_actions():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "refresh_site" in s
    assert "forget_site" in s


async def test_sidebar_shows_domain_not_name():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "admin", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "x.com" in s


async def test_sidebar_connected_badge_green():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    assert "green" in str(node)


async def test_sidebar_error_badge_red():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "error"},
    )
    node = await panels.sidebar(ctx)
    assert "red" in str(node)


# ── center panel ──────────────────────────────────────────────────────────────

async def test_center_empty_when_no_args():
    ctx = MockContext()
    node = await panels.center(ctx)
    assert node is not None
    assert "Empty" in str(node) or "Select" in str(node)


async def test_center_shows_connect_form_when_view_connect():
    ctx = MockContext()
    node = await panels.center(ctx, view="connect", site_id="")
    s = str(node)
    assert "app_password" in s and "'type': 'password'" in s


async def test_center_connect_form_has_cancel_pointing_to_center():
    ctx = MockContext()
    node = await panels.center(ctx, view="connect", site_id="")
    s = str(node)
    assert "Cancel" in s
    assert "__panel__center" in s


async def test_center_connect_form_has_url_and_username():
    ctx = MockContext()
    node = await panels.center(ctx, view="connect", site_id="")
    s = str(node)
    assert "url" in s
    assert "username" in s


async def test_center_shows_detail_when_site_id():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X",
                                         "url": "https://x.com", "username": "admin",
                                         "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts",
                      [{"id": 1, "title": {"rendered": "Hello"}, "status": "publish",
                        "date": "2026-06-01T00:00:00"}], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media", [], 200)
    node = await panels.center(ctx, view="", site_id="x-com")
    s = str(node)
    assert "x.com" in s
    assert "Stats" in s
    assert "Hello" in s
    assert "Standard" in s and "Activity" in s  # group tab buttons


async def test_center_detail_shows_alert_on_missing_credential():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X",
                                         "url": "https://x.com", "username": "admin",
                                         "status": "connected"})
    node = await panels.center(ctx, view="", site_id="x-com")
    s = str(node)
    assert "Alert" in s or "credential" in s.lower()


async def test_center_connect_view_overrides_site_id():
    """view=connect takes priority even if site_id is set (accumulated params scenario)."""
    ctx = MockContext()
    node = await panels.center(ctx, view="connect", site_id="x-com")
    s = str(node)
    assert "app_password" in s


async def test_center_shows_connect_ssh_form_when_view_connect_ssh():
    ctx = MockContext()
    node = await panels.center(ctx, view="connect_ssh", site_id="")
    s = str(node)
    assert "ssh_host" in s and "ssh_user" in s and "wp_path" in s
    assert "app_password" not in s


async def test_center_connect_ssh_form_has_cancel_and_no_app_password_needed_alert():
    ctx = MockContext()
    node = await panels.center(ctx, view="connect_ssh", site_id="")
    s = str(node)
    assert "Cancel" in s
    assert "Alert" in s


async def test_center_detail_for_ssh_site_shows_ssh_auth_mode_not_credential_error():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "ssh-site", "name": "ssh-site", "url": "https://ssh-site.example",
        "auth_mode": "ssh", "status": "connected",
    })
    await storage.set_ssh_cred(ctx, "ssh-site", {
        "host": "1.2.3.4", "port": 22, "user": "root", "wp_path": "/var/www/html",
        "password": "super-secret",
    })
    node = await panels.center(ctx, view="", site_id="ssh-site")
    s = str(node)
    assert "SSH only" in s
    assert "Credential missing" not in s
