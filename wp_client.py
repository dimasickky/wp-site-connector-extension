import base64
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

_ERROR_MESSAGES = {
    401: "WordPress rejected the credentials — reconnect the site with a fresh Application Password.",
    403: "That WordPress user lacks permission for this request.",
    404: "WordPress REST API not found — is this a WordPress site and is the REST API enabled?",
    429: "WordPress is rate-limiting requests — try again shortly.",
}


def basic_auth_header(username: str, app_password: str) -> dict:
    token = base64.b64encode(f"{username}:{app_password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def normalize_base_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise ValueError("Site URL must use https://")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def site_id_from_url(url: str) -> str:
    host = urlparse(url.strip()).netloc.lower()
    host = re.sub(r"^www\.", "", host)
    return re.sub(r"[^a-z0-9]+", "-", host).strip("-")


def wp_error_message(status_code: int) -> str:
    if status_code in _ERROR_MESSAGES:
        return _ERROR_MESSAGES[status_code]
    if 500 <= status_code < 600:
        return "WordPress returned a server error — try again shortly."
    return f"WordPress request failed (HTTP {status_code})."


async def wp_get(ctx, base_url, path, *, username, app_password, params=None):
    headers = basic_auth_header(username, app_password)
    return await ctx.http.get(f"{base_url}{path}", headers=headers, params=params)


async def wp_post(ctx, base_url, path, *, username, app_password, json_body=None):
    """POST to the WP REST API. Used for both create (POST /posts) and update
    (POST /posts/<id> — WordPress accepts POST for partial updates, no need
    for PUT/PATCH), mirroring wp_get's Basic Auth handling."""
    headers = basic_auth_header(username, app_password)
    return await ctx.http.post(f"{base_url}{path}", headers=headers, json=json_body)


_EXT_CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
}


def guess_image_content_type(filename: str, fallback: str = "") -> str:
    """Best-effort content-type from a filename extension; falls back to a
    caller-supplied value (e.g. the source download's own content-type)."""
    lower = filename.lower()
    for ext, ct in _EXT_CONTENT_TYPES.items():
        if lower.endswith(ext):
            return ct
    return fallback or "application/octet-stream"


async def wp_upload_media(ctx, base_url, *, username, app_password,
                          file_bytes: bytes, filename: str, content_type: str):
    """Upload raw bytes to the WP Media Library (POST /wp/v2/media).

    Unlike wp_post, the WordPress media endpoint expects the RAW file body
    (not JSON) plus Content-Disposition so it knows the filename. Basic Auth
    header is reused from the same credential as every other WP call.
    """
    headers = basic_auth_header(username, app_password)
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    headers["Content-Type"] = content_type
    return await ctx.http.post(f"{base_url}/wp-json/wp/v2/media",
                               headers=headers, content=file_bytes)


def now_iso() -> str:
    """Current UTC timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def wp_title(item: dict) -> str:
    """WordPress entities carry title as {"rendered": "..."}; fall back to id, then empty string."""
    t = item.get("title")
    if isinstance(t, dict):
        return t.get("rendered") or str(item.get("id", "")) or ""
    return t or str(item.get("id", "")) or ""
