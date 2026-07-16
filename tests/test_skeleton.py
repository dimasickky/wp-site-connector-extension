from imperal_sdk.testing import MockContext
import app  # noqa: F401
import skeleton
import storage


async def test_skeleton_counts_connected_sites():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    out = await skeleton.sites_overview(ctx)
    assert out["response"]["sites_connected"] == 1


async def test_skeleton_zero_sites():
    ctx = MockContext()
    out = await skeleton.sites_overview(ctx)
    assert out["response"]["sites_connected"] == 0
