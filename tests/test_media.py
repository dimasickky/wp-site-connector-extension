import base64

from imperal_sdk.testing import MockContext
import handlers_publish as hp
import storage
from models import UploadMediaParams, CreatePostParams


TINY_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake-image-bytes").decode()


async def _connected_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com",
                                         "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


def _files_payload(b64=TINY_PNG_B64, name="cover.png", content_type="image/png"):
    return [{"data_base64": b64, "name": name, "content_type": content_type}]


async def test_upload_media_no_file_provided():
    ctx = await _connected_ctx()
    r = await hp.upload_media(ctx, UploadMediaParams(site_id="x-com", files=None))
    assert r.status != "success"


async def test_upload_media_invalid_base64():
    ctx = await _connected_ctx()
    r = await hp.upload_media(ctx, UploadMediaParams(
        site_id="x-com", files=[{"data_base64": "not-valid-base64!!!", "name": "x.png"}]))
    assert r.status != "success"


async def test_upload_media_unknown_site():
    ctx = MockContext()
    r = await hp.upload_media(ctx, UploadMediaParams(site_id="nope", files=_files_payload()))
    assert r.status != "success"


async def test_upload_media_success_returns_id_and_url():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/media",
                       {"id": 99, "title": {"rendered": "cover.png"},
                        "source_url": "https://x.com/wp-content/uploads/2026/07/cover.png",
                        "mime_type": "image/png"}, 201)
    r = await hp.upload_media(ctx, UploadMediaParams(site_id="x-com", files=_files_payload()))
    assert r.status == "success"
    assert r.data.id == "99"
    assert r.data.url == "https://x.com/wp-content/uploads/2026/07/cover.png"


async def test_upload_media_bad_credentials():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/media", {}, 401)
    r = await hp.upload_media(ctx, UploadMediaParams(site_id="x-com", files=_files_payload()))
    assert r.status != "success"


async def test_create_post_with_featured_media_id_sets_featured_media_field():
    ctx = await _connected_ctx()
    captured = {}

    async def fake_wp_post(ctx_, base_url, path, *, username, app_password, json_body=None):
        captured["body"] = json_body
        from imperal_sdk.types.models import HTTPResponse
        return HTTPResponse(status_code=201, body={"id": 5, "title": {"rendered": "Hi"},
                                                    "status": "draft", "link": "https://x.com/?p=5"})

    hp.wp_post = fake_wp_post
    try:
        r = await hp.create_post(ctx, CreatePostParams(site_id="x-com", title="Hi", featured_media_id=99))
        assert r.status == "success"
        assert captured["body"]["featured_media"] == 99
    finally:
        import wp_client
        hp.wp_post = wp_client.wp_post
