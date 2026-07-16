import base64
import pytest
from imperal_sdk.testing import MockContext
import wp_client as wc


def test_basic_auth_header():
    h = wc.basic_auth_header("admin", "abcd efgh")
    token = base64.b64encode(b"admin:abcd efgh").decode()
    assert h["Authorization"] == f"Basic {token}"


def test_normalize_base_url_forces_https_and_strips_slash():
    assert wc.normalize_base_url("https://Example.com/") == "https://Example.com"
    with pytest.raises(ValueError):
        wc.normalize_base_url("http://example.com")


def test_site_id_from_url():
    assert wc.site_id_from_url("https://Example.com/blog") == "example-com"


def test_error_messages_are_user_safe():
    assert "credential" in wc.wp_error_message(401).lower()
    assert "not found" in wc.wp_error_message(404).lower()
    assert "server" in wc.wp_error_message(500).lower()


async def test_wp_get_calls_http_with_auth():
    ctx = MockContext()
    ctx.http.mock_get("https://example.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    r = await wc.wp_get(ctx, "https://example.com", "/wp-json/wp/v2/users/me",
                        username="admin", app_password="pw")
    assert r.status_code == 200 and r.json()["name"] == "Admin"


async def test_wp_get_with_params_matches_mock():
    ctx = MockContext()
    ctx.http.mock_get("https://example.com/wp-json/wp/v2/posts", [{"id": 1}], 200)
    r = await wc.wp_get(ctx, "https://example.com", "/wp-json/wp/v2/posts",
                        username="a", app_password="p", params={"per_page": 5})
    assert r.status_code == 200
