from imperal_sdk.testing import MockContext
import app  # noqa: F401
import handlers_read as hr
import storage
from models import ListContentParams, ListMediaParams, SiteIdParams


async def _connected_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def test_list_posts_maps_rest_payload():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts",
                      [{"id": 1, "title": {"rendered": "Hello"}, "status": "publish",
                        "link": "https://x.com/hello", "date": "2026-06-16T00:00:00"}], 200)
    r = await hr.list_posts(ctx, ListContentParams(site_id="x-com"))
    assert r.status == "success"
    assert r.data.items[0].title == "Hello" and r.data.items[0].link.endswith("/hello")


async def test_list_posts_unknown_site_errors():
    ctx = await _connected_ctx()
    r = await hr.list_posts(ctx, ListContentParams(site_id="missing"))
    assert r.status == "error"


async def test_list_posts_http_error_maps_message():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts", {}, 401)
    r = await hr.list_posts(ctx, ListContentParams(site_id="x-com"))
    assert r.status == "error"


async def test_list_pages_maps_payload():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages",
                      [{"id": 2, "title": {"rendered": "About"}, "status": "publish", "link": "https://x.com/about"}], 200)
    r = await hr.list_pages(ctx, ListContentParams(site_id="x-com"))
    assert r.data.items[0].title == "About"


async def test_list_media_maps_source_url():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media",
                      [{"id": 9, "title": {"rendered": "img"}, "source_url": "https://x.com/img.png", "mime_type": "image/png"}], 200)
    r = await hr.list_media(ctx, ListMediaParams(site_id="x-com"))
    assert r.data.items[0].url.endswith("img.png") and r.data.items[0].mime_type == "image/png"


async def test_refresh_site_sets_connected_on_200():
    ctx = await _connected_ctx()
    # site starts as "error"
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com",
                                         "username": "admin", "status": "error"})
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    result = await hr.refresh_site(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    record = await storage.get_site_record(ctx, "x-com")
    assert record["status"] == "connected"


async def test_refresh_site_sets_error_on_401():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"code": "rest_forbidden"}, 401)
    result = await hr.refresh_site(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"  # function itself succeeded — status was updated
    record = await storage.get_site_record(ctx, "x-com")
    assert record["status"] == "error"


async def test_refresh_site_errors_on_missing_site():
    ctx = MockContext()
    result = await hr.refresh_site(ctx, SiteIdParams(site_id="no-such-site"))
    assert result.status == "error"
