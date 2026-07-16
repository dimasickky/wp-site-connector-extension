from imperal_sdk.testing import MockContext
import storage


async def test_save_and_list_site_records():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "url": "https://x.com", "status": "connected"})
    rows = await storage.list_site_records(ctx)
    assert any(r["id"] == "x-com" for r in rows)


async def test_save_is_idempotent_update():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X2", "status": "connected"})
    matching = [r for r in await storage.list_site_records(ctx) if r["id"] == "x-com"]
    assert len(matching) == 1 and matching[0]["name"] == "X2"


async def test_get_and_delete_site_record():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X"})
    assert (await storage.get_site_record(ctx, "x-com"))["name"] == "X"
    await storage.delete_site_record(ctx, "x-com")
    assert await storage.get_site_record(ctx, "x-com") is None


async def test_credential_roundtrip_and_delete():
    ctx = MockContext()
    await storage.set_credential(ctx, "x-com", "pw-1")
    assert await storage.get_credential(ctx, "x-com") == "pw-1"
    await storage.delete_credential(ctx, "x-com")
    assert await storage.get_credential(ctx, "x-com") is None
