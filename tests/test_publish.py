from imperal_sdk.testing import MockContext
import handlers_publish as hp
import storage
from models import CreatePostParams, UpdatePostParams


async def _connected_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com",
                                         "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def test_create_post_rejects_invalid_status():
    ctx = await _connected_ctx()
    r = await hp.create_post(ctx, CreatePostParams(site_id="x-com", title="Hi", status="bogus"))
    assert r.status != "success"


async def test_create_post_future_requires_date():
    ctx = await _connected_ctx()
    r = await hp.create_post(ctx, CreatePostParams(site_id="x-com", title="Hi", status="future"))
    assert r.status != "success"


async def test_create_post_unknown_site():
    ctx = MockContext()
    r = await hp.create_post(ctx, CreatePostParams(site_id="nope", title="Hi"))
    assert r.status != "success"


async def test_create_post_success():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/posts",
                       {"id": 42, "title": {"rendered": "Hi"}, "status": "draft",
                        "link": "https://x.com/?p=42", "date": "2026-07-16T10:00:00"}, 201)
    r = await hp.create_post(ctx, CreatePostParams(site_id="x-com", title="Hi", content="Body"))
    assert r.status == "success"
    assert r.data.id == "42"
    assert r.data.status == "draft"


async def test_create_post_bad_credentials():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/posts", {}, 401)
    r = await hp.create_post(ctx, CreatePostParams(site_id="x-com", title="Hi"))
    assert r.status != "success"


async def test_update_post_requires_at_least_one_field():
    ctx = await _connected_ctx()
    r = await hp.update_post(ctx, UpdatePostParams(site_id="x-com", post_id="42"))
    assert r.status != "success"


async def test_update_post_rejects_invalid_status():
    ctx = await _connected_ctx()
    r = await hp.update_post(ctx, UpdatePostParams(site_id="x-com", post_id="42", status="bogus"))
    assert r.status != "success"


async def test_update_post_not_found():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/posts/999", {}, 404)
    r = await hp.update_post(ctx, UpdatePostParams(site_id="x-com", post_id="999", title="New"))
    assert r.status != "success"


async def test_update_post_success():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/posts/42",
                       {"id": 42, "title": {"rendered": "New title"}, "status": "publish",
                        "link": "https://x.com/?p=42", "date": "2026-07-16T10:00:00"}, 200)
    r = await hp.update_post(ctx, UpdatePostParams(site_id="x-com", post_id="42",
                                                   title="New title", status="publish"))
    assert r.status == "success"
    assert r.data.status == "publish"
