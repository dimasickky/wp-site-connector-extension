import pytest
from pydantic import ValidationError
from models import ListContentParams, Site, Post, MediaItem, SiteHealth


def test_list_content_defaults():
    p = ListContentParams(site_id="x-com")
    assert p.limit == 20 and p.search is None


def test_list_content_limit_bounds_enforced():
    with pytest.raises(ValidationError):
        ListContentParams(site_id="x-com", limit=500)


def test_site_entity_uses_base_and_custom_fields():
    s = Site(id="x-com", title="X", kind="wp_site", url="https://x.com",
             username="admin", status="connected", last_checked="2026-06-16T00:00:00Z")
    assert s.kind == "wp_site" and s.status == "connected" and s.username == "admin"


def test_post_and_media_entities():
    post = Post(id="1", title="Hello", kind="wp_post", status="publish",
                link="https://x.com/hello", date="2026-06-16T00:00:00Z")
    media = MediaItem(id="9", title="img", kind="wp_media", url="https://x.com/img.png", mime_type="image/png")
    assert post.link.endswith("/hello") and media.mime_type == "image/png"


def test_site_health_marks_vnext_fields_unavailable():
    h = SiteHealth(id="x-com", title="X health", kind="wp_site_health",
                   reachable=True, auth_ok=True, ssl_valid=True, content_counts={"posts": 3})
    assert "vNext" in h.plugin_updates_available and "vNext" in h.php_version
