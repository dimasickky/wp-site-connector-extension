from imperal_sdk.testing import MockContext
import handlers_connect as hc
import storage
from models import ConnectSiteParams


async def _ctx():
    ctx = MockContext()
    return ctx


async def test_connect_rejects_non_https():
    ctx = await _ctx()
    r = await hc.connect_site(ctx, ConnectSiteParams(url="http://x.com", username="a", app_password="p"))
    assert r.status != "success"
    assert await storage.get_site_record(ctx, "x-com") is None


async def test_connect_success_stores_site_and_credential():
    ctx = await _ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    r = await hc.connect_site(ctx, ConnectSiteParams(url="https://x.com", username="admin", app_password="pw"))
    assert r.status == "success" and r.data.id == "x-com"
    assert (await storage.get_site_record(ctx, "x-com"))["status"] == "connected"
    assert await storage.get_credential(ctx, "x-com") == "pw"


async def test_connect_bad_credentials_returns_error_and_stores_nothing():
    ctx = await _ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {}, 401)
    r = await hc.connect_site(ctx, ConnectSiteParams(url="https://x.com", username="admin", app_password="bad"))
    assert r.status != "success"
    assert await storage.get_site_record(ctx, "x-com") is None
    assert await storage.get_credential(ctx, "x-com") is None
