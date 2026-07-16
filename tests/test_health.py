from imperal_sdk.testing import MockContext
import app  # noqa: F401
import handlers_read as hr
import storage
from models import SiteIdParams


async def _connected_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def test_health_reports_available_fields_and_marks_vnext():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts", [{"id": 1}, {"id": 2}, {"id": 3}], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [{"id": 1}], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media", [], 200)
    r = await hr.get_site_health(ctx, SiteIdParams(site_id="x-com"))
    h = r.data
    assert h.reachable and h.auth_ok and h.ssl_valid
    assert h.content_counts["posts"] == 3 and h.content_counts["media"] == 0
    assert "vNext" in h.plugin_updates_available and "vNext" in h.php_version


async def test_health_unknown_site_errors():
    ctx = MockContext()
    r = await hr.get_site_health(ctx, SiteIdParams(site_id="nope"))
    assert r.status == "error"
