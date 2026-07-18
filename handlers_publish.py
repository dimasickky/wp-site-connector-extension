import base64

from app import chat
from imperal_sdk import ActionResult
from models import CreatePostParams, UpdatePostParams, UploadMediaParams, Post, MediaItem
from wp_client import wp_post, wp_upload_media, guess_image_content_type, wp_error_message, wp_title
import storage
import wp_cli


_VALID_STATUSES = {"draft", "publish", "pending", "future"}


# NOTE: site auth resolution (REST vs SSH) lives in storage.resolve_site —
# shared with handlers_read.py so both publish and read paths pick the same
# way to reach an SSH-only site.
_resolve_site = storage.resolve_site


@chat.function(
    "create_post",
    description="Create a new post on a connected WordPress site. Defaults to status='draft' — pass status='publish' to publish immediately, or status='future' with a date to schedule.",
    action_type="write",
    data_model=Post,
    effects=["wp.create_post"],
    event="wp-site-connector.create_post",
)
async def create_post(ctx, params: CreatePostParams) -> ActionResult:
    """Create a WordPress post — via the REST API for Application Password sites,
    or via WP-CLI over SSH (no REST call at all) for SSH-only sites."""
    if params.status not in _VALID_STATUSES:
        return ActionResult.error(
            f"Invalid status '{params.status}' — use draft, publish, pending, or future.",
            retryable=False,
        )
    if params.status == "future" and not params.date:
        return ActionResult.error(
            "status='future' requires a date (ISO 8601, e.g. 2026-08-01T09:00:00).",
            retryable=False,
        )

    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)

    if mode == "ssh":
        result, cli_err = await wp_cli.create_post_cli(
            session, title=params.title, content=params.content, status=params.status,
            excerpt=params.excerpt, date=params.date, slug=params.slug)
        if cli_err:
            return ActionResult.error(f"WP-CLI publish failed: {cli_err}", retryable=True)
        post = Post(id=result["id"], title=result["title"], kind="wp_post",
                    status=result["status"], link="", date=params.date)
        icon = "✅" if post.status == "publish" else "📝"
        summary = f"{icon} Created \"{post.title}\" ({post.status}) via SSH"
        if params.meta_description is not None or params.focus_keyword is not None:
            meta_errs = await wp_cli.set_rank_math_meta_cli(
                session, post.id, description=params.meta_description, focus_keyword=params.focus_keyword)
            if meta_errs:
                summary += f" — ⚠️ Rank Math SEO fields NOT saved ({'; '.join(meta_errs)})"
            else:
                summary += " + Rank Math SEO fields set"
        return ActionResult.success(post, summary=summary, refresh_panels=["center"])

    base_url, username, pw = session
    body = {
        "title": params.title,
        "content": params.content,
        "status": params.status,
        "excerpt": params.excerpt,
    }
    if params.date:
        body["date"] = params.date
    if params.slug:
        body["slug"] = params.slug
    if params.categories:
        body["categories"] = params.categories
    if params.tags:
        body["tags"] = params.tags
    if params.featured_media_id is not None:
        body["featured_media"] = params.featured_media_id

    try:
        r = await wp_post(ctx, base_url, "/wp-json/wp/v2/posts",
                          username=username, app_password=pw, json_body=body)
    except Exception as e:
        await ctx.log(f"create_post http error: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)

    if not (200 <= r.status_code < 300):
        return ActionResult.error(wp_error_message(r.status_code),
                                  retryable=r.status_code >= 500 or r.status_code == 429)

    data = r.body if isinstance(r.body, dict) else {}
    post = Post(id=str(data.get("id", "")), title=wp_title(data) or params.title, kind="wp_post",
                status=data.get("status", params.status), link=data.get("link", ""),
                date=data.get("date"))
    icon = "✅" if post.status == "publish" else "📝"
    summary = f"{icon} Created \"{post.title}\" ({post.status})"
    if params.meta_description is not None or params.focus_keyword is not None:
        summary += (" — ⚠️ Rank Math SEO fields NOT saved: this site is connected via Application "
                   "Password/REST, and Rank Math does not expose meta_description/focus_keyword to "
                   "the REST API. Connect this site over SSH to set them.")
    return ActionResult.success(
        post, summary=summary,
        refresh_panels=["center"],
    )


@chat.function(
    "update_post",
    description="Update an existing post on a connected WordPress site — title, content, status, excerpt, or scheduled date. Only fields you pass are changed.",
    action_type="write",
    data_model=Post,
    effects=["wp.update_post"],
    event="wp-site-connector.update_post",
)
async def update_post(ctx, params: UpdatePostParams) -> ActionResult:
    """Partially update a WordPress post — via REST for Application Password
    sites, or via WP-CLI over SSH for SSH-only sites. Only fields you pass are changed."""
    if params.status is not None and params.status not in _VALID_STATUSES:
        return ActionResult.error(
            f"Invalid status '{params.status}' — use draft, publish, pending, or future.",
            retryable=False,
        )

    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)

    if mode == "ssh":
        if (params.title is None and params.content is None and params.status is None
                and params.excerpt is None and params.slug is None
                and params.meta_description is None and params.focus_keyword is None):
            return ActionResult.error(
                "No fields to update — pass at least one of title/content/status/excerpt/slug/meta_description/focus_keyword.",
                retryable=False)
        summary = None
        if (params.title is not None or params.content is not None or params.status is not None
                or params.excerpt is not None or params.slug is not None):
            result, cli_err = await wp_cli.update_post_cli(
                session, post_id=params.post_id, title=params.title, content=params.content,
                status=params.status, excerpt=params.excerpt, slug=params.slug)
            if cli_err:
                return ActionResult.error(f"WP-CLI update failed: {cli_err}", retryable=True)
            summary = f"✅ Updated post {result['id']} via SSH"
            post = Post(id=result["id"], title=result["title"] or "", kind="wp_post",
                        status=result["status"] or "", link="", date=None)
        else:
            post = Post(id=params.post_id, title="", kind="wp_post", status="", link="", date=None)
            summary = f"✅ Updated post {params.post_id} via SSH"
        if params.meta_description is not None or params.focus_keyword is not None:
            meta_errs = await wp_cli.set_rank_math_meta_cli(
                session, params.post_id, description=params.meta_description, focus_keyword=params.focus_keyword)
            if meta_errs:
                summary += f" — ⚠️ Rank Math SEO fields NOT saved ({'; '.join(meta_errs)})"
            else:
                summary += " + Rank Math SEO fields set"
        return ActionResult.success(post, summary=summary, refresh_panels=["center"])

    base_url, username, pw = session
    body = {}
    if params.title is not None:
        body["title"] = params.title
    if params.content is not None:
        body["content"] = params.content
    if params.status is not None:
        body["status"] = params.status
    if params.excerpt is not None:
        body["excerpt"] = params.excerpt
    if params.date is not None:
        body["date"] = params.date
    if params.slug is not None:
        body["slug"] = params.slug
    if params.featured_media_id is not None:
        body["featured_media"] = params.featured_media_id

    if not body:
        if params.meta_description is not None or params.focus_keyword is not None:
            return ActionResult.error(
                "meta_description/focus_keyword can't be set on this site — it's connected via "
                "Application Password/REST, and Rank Math doesn't expose those fields to the REST "
                "API. Connect this site over SSH instead, or pass another field to update too.",
                retryable=False)
        return ActionResult.error("No fields to update — pass at least one of title/content/status/excerpt/date/slug/featured_media_id.",
                                  retryable=False)

    try:
        r = await wp_post(ctx, base_url, f"/wp-json/wp/v2/posts/{params.post_id}",
                          username=username, app_password=pw, json_body=body)
    except Exception as e:
        await ctx.log(f"update_post http error: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)

    if r.status_code == 404:
        return ActionResult.error("Post not found on this site.", retryable=False)
    if not (200 <= r.status_code < 300):
        return ActionResult.error(wp_error_message(r.status_code),
                                  retryable=r.status_code >= 500 or r.status_code == 429)

    data = r.body if isinstance(r.body, dict) else {}
    post = Post(id=str(data.get("id", params.post_id)), title=wp_title(data), kind="wp_post",
                status=data.get("status", ""), link=data.get("link", ""), date=data.get("date"))
    summary = f"✅ Updated \"{post.title}\" ({post.status})"
    if params.meta_description is not None or params.focus_keyword is not None:
        summary += (" — ⚠️ Rank Math SEO fields NOT saved: this site is connected via Application "
                   "Password/REST, and Rank Math does not expose meta_description/focus_keyword to "
                   "the REST API. Connect this site over SSH to set them.")
    return ActionResult.success(
        post, summary=summary,
        refresh_panels=["center"],
    )


def _extract_b64(payload) -> tuple[str, str, str]:
    """Return (data_base64, filename, content_type) from a FileUpload payload
    (same shape as notes' attachment upload — list[dict] or dict)."""
    if isinstance(payload, list) and payload:
        item = payload[0] if isinstance(payload[0], dict) else {}
    elif isinstance(payload, dict):
        item = payload
    else:
        return "", "", ""
    b64 = item.get("data_base64", "")
    if b64.startswith("data:") and "," in b64:
        b64 = b64.split(",", 1)[1]
    return b64, item.get("name", "image"), item.get("content_type", "")


@chat.function(
    "upload_media",
    description=(
        "Upload an image to a connected WordPress site's Media Library. Returns a media_id "
        "(use as featured_media_id on create_post/update_post for the cover image) and a url "
        "(embed as <img src=\"...\"> inside a post's content to place it anywhere in the text)."
    ),
    action_type="write",
    chain_callable=True,
    data_model=MediaItem,
    effects=["wp.upload_media"],
    event="wp-site-connector.upload_media",
)
async def upload_media(ctx, params: UploadMediaParams) -> ActionResult:
    """Upload a base64-encoded image — via REST (POST /wp/v2/media) for Application
    Password sites, or via `wp media import` over SSH for SSH-only sites."""
    b64, filename, upload_content_type = _extract_b64(params.files)
    if not b64:
        return ActionResult.error("No file provided — attach an image to upload.", retryable=False)

    try:
        file_bytes = base64.b64decode(b64)
    except Exception:
        return ActionResult.error("Invalid file data (base64 decode failed).", retryable=False)

    if not file_bytes:
        return ActionResult.error("Uploaded file is empty.", retryable=False)

    content_type = guess_image_content_type(filename, upload_content_type)

    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)

    if mode == "ssh":
        result, cli_err = await wp_cli.upload_media_cli(
            session, b64_data=b64, filename=filename, title=params.title or "")
        if cli_err:
            return ActionResult.error(f"WP-CLI media upload failed: {cli_err}", retryable=True)
        media = MediaItem(id=result["id"], title=result["title"], kind="wp_media",
                          url=result.get("url", ""), mime_type=content_type)
        return ActionResult.success(
            media, summary=f"🖼️ Uploaded \"{media.title}\" via SSH (media_id={media.id})",
            refresh_panels=["center"])

    base_url, username, pw = session
    try:
        r = await wp_upload_media(ctx, base_url, username=username, app_password=pw,
                                  file_bytes=file_bytes, filename=filename, content_type=content_type)
    except Exception as e:
        await ctx.log(f"upload_media http error: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)

    if not (200 <= r.status_code < 300):
        return ActionResult.error(wp_error_message(r.status_code),
                                  retryable=r.status_code >= 500 or r.status_code == 429)

    data = r.body if isinstance(r.body, dict) else {}
    media_id = data.get("id")
    if media_id is None:
        return ActionResult.error("WordPress accepted the upload but returned no media id — try again.",
                                  retryable=True)

    media = MediaItem(id=str(media_id), title=wp_title(data) or filename, kind="wp_media",
                      url=data.get("source_url", ""), mime_type=data.get("mime_type", content_type))
    if params.title or params.alt_text:
        try:
            await wp_post(ctx, base_url, f"/wp-json/wp/v2/media/{media_id}",
                          username=username, app_password=pw,
                          json_body={k: v for k, v in {
                              "title": params.title or None, "alt_text": params.alt_text or None,
                          }.items() if v is not None})
        except Exception as e:
            # Metadata patch is best-effort — the upload itself already succeeded.
            await ctx.log(f"upload_media metadata patch failed: {e}", level="warning")

    return ActionResult.success(
        media, summary=f"🖼️ Uploaded \"{media.title}\" (media_id={media.id})",
        refresh_panels=["center"],
    )
