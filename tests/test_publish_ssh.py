from imperal_sdk.testing import MockContext
import handlers_publish as hp
import storage
from models import CreatePostParams, UpdatePostParams, UploadMediaParams


async def _ssh_ctx():
    """A site connected via connect_site_ssh — auth_mode='ssh', no Application Password."""
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "ssh-site", "name": "ssh-site", "url": "https://ssh-site.example",
        "auth_mode": "ssh", "status": "connected",
    })
    await storage.set_ssh_cred(ctx, "ssh-site", {
        "host": "1.2.3.4", "port": 22, "user": "root", "wp_path": "/var/www/html",
        "password": "super-secret", "host_key": "1.2.3.4 ssh-ed25519 AAAATEST",
    })
    return ctx


async def test_create_post_uses_cli_for_ssh_site(monkeypatch):
    ctx = await _ssh_ctx()
    seen = {}

    async def _fake_create(cred, title, content, status, excerpt="", date=None, slug=None):
        seen["cred"] = cred
        seen["title"] = title
        seen["slug"] = slug
        return {"id": "7", "title": title, "status": status}, None

    monkeypatch.setattr(hp.wp_cli, "create_post_cli", _fake_create)
    r = await hp.create_post(ctx, CreatePostParams(
        site_id="ssh-site", title="Hi", content="Body", slug="infinityfree-review-2026"))

    assert r.status == "success"
    assert r.data.id == "7"
    assert seen["cred"]["host"] == "1.2.3.4"
    assert seen["title"] == "Hi"
    assert seen["slug"] == "infinityfree-review-2026"


async def test_create_post_ssh_cli_failure_surfaces_error(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_create(cred, title, content, status, excerpt="", date=None, slug=None):
        return None, "Connection refused"

    monkeypatch.setattr(hp.wp_cli, "create_post_cli", _fake_create)
    r = await hp.create_post(ctx, CreatePostParams(site_id="ssh-site", title="Hi", content="Body"))
    assert r.status != "success"


async def test_update_post_uses_cli_for_ssh_site(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_update(cred, post_id, title, content, status, excerpt=None, slug=None):
        return {"id": post_id, "title": title, "status": status}, None

    monkeypatch.setattr(hp.wp_cli, "update_post_cli", _fake_update)
    r = await hp.update_post(ctx, UpdatePostParams(site_id="ssh-site", post_id="7", title="Updated"))
    assert r.status == "success"
    assert r.data.id == "7"


async def test_update_post_ssh_slug_alone_counts_as_a_field(monkeypatch):
    ctx = await _ssh_ctx()

    async def _fake_update(cred, post_id, title, content, status, excerpt=None, slug=None):
        return {"id": post_id, "title": None, "status": None}, None

    monkeypatch.setattr(hp.wp_cli, "update_post_cli", _fake_update)
    r = await hp.update_post(ctx, UpdatePostParams(site_id="ssh-site", post_id="7", slug="new-slug"))
    assert r.status == "success"


async def test_update_post_ssh_requires_a_field(monkeypatch):
    ctx = await _ssh_ctx()
    r = await hp.update_post(ctx, UpdatePostParams(site_id="ssh-site", post_id="7"))
    assert r.status != "success"


async def test_upload_media_uses_cli_for_ssh_site(monkeypatch):
    ctx = await _ssh_ctx()
    import base64
    b64 = base64.b64encode(b"fake-image-bytes").decode()

    async def _fake_upload(cred, b64_data, filename, title=""):
        return {"id": "99", "title": title or filename}, None

    monkeypatch.setattr(hp.wp_cli, "upload_media_cli", _fake_upload)
    r = await hp.upload_media(ctx, UploadMediaParams(
        site_id="ssh-site", files=[{"data_base64": b64, "name": "photo.jpg", "content_type": "image/jpeg"}]))
    assert r.status == "success"
    assert r.data.id == "99"


async def test_create_post_still_uses_rest_for_app_password_site():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com",
                                         "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/posts",
                       {"id": 42, "title": {"rendered": "Hi"}, "status": "draft",
                        "link": "https://x.com/?p=42", "date": "2026-07-16T10:00:00"}, 201)
    r = await hp.create_post(ctx, CreatePostParams(site_id="x-com", title="Hi", content="Body"))
    assert r.status == "success"
    assert r.data.id == "42"


async def test_create_post_rest_sends_custom_slug_in_body():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com",
                                         "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/posts",
                       {"id": 42, "title": {"rendered": "Hi"}, "status": "publish",
                        "link": "https://x.com/infinityfree-review-2026/",
                        "date": "2026-07-16T10:00:00"}, 201)
    r = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hi", content="Body", status="publish",
        slug="infinityfree-review-2026"))
    assert r.status == "success"
    assert r.data.link == "https://x.com/infinityfree-review-2026/"
