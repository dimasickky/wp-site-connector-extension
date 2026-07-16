from imperal_sdk.testing import MockContext
import app  # noqa: F401
import handlers_read as hr
import storage
from models import _NoParams


async def test_list_sites_returns_connected_sites():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "username": "a", "status": "connected"})
    r = await hr.list_sites(ctx, _NoParams())
    assert r.status == "success"
    assert "X" in [e.title for e in r.data.items]


async def test_list_sites_empty():
    ctx = MockContext()
    r = await hr.list_sites(ctx, _NoParams())
    assert r.status == "success" and r.data.items == []
