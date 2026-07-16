from imperal_sdk.testing import MockContext
import app  # noqa: F401
import handlers_connect as hc
import storage
from models import SiteIdParams


async def test_forget_removes_record_and_credential():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")

    r = await hc.forget_site(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "success"
    assert await storage.get_site_record(ctx, "x-com") is None
    assert await storage.get_credential(ctx, "x-com") is None


async def test_forget_unknown_site_errors():
    ctx = MockContext()
    r = await hc.forget_site(ctx, SiteIdParams(site_id="nope"))
    assert r.status == "error"
