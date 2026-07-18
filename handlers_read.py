import asyncio

from imperal_sdk import ActionResult, sdl
from app import chat
from models import (_NoParams, Site, ListContentParams, ListMediaParams,
                    Post, Page, MediaItem, SiteIdParams, SiteHealth, RefreshAllResult,
                    ListCommentsParams, ListCustomPostsParams, Comment, WPUser, Order,
                    ServerInfo, Plugin)
import wp_cli
from wp_client import wp_get, wp_error_message, wp_error_code, wp_title, now_iso
from imperal_sdk.chat.error_codes import INTERNAL, PERMISSION_DENIED
from error_codes import (WP_SITE_NOT_CONNECTED, WP_SITE_UNREACHABLE, WP_NO_SITES_CONNECTED,
                         WP_SSH_COMMAND_FAILED, WP_SSH_CONNECTION_FAILED, WP_SSH_NOT_CONFIGURED,
                         WP_WOOCOMMERCE_NOT_INSTALLED)
import storage


@chat.function("list_sites", description="List the WordPress sites the user has connected.",
               action_type="read", data_model=sdl.EntityList[Site])
async def list_sites(ctx, params: _NoParams) -> ActionResult:
    """Return all connected WordPress sites as an entity list."""
    rows = await storage.list_site_records(ctx)
    sites = [
        Site(id=r["id"], title=r.get("name", r["id"]), kind="wp_site",
             url=r.get("url", ""), username=r.get("username", ""),
             status=r.get("status", "connected"), last_checked=r.get("last_checked"))
        for r in rows
    ]
    return ActionResult.success(sdl.EntityList[Site](items=sites), summary=f"{len(sites)} site(s) connected")


# NOTE: site auth resolution (REST vs SSH) lives in storage.resolve_site —
# shared with handlers_publish.py so both publish and read paths pick the
# same way to reach an SSH-only site (no Application Password stored at all).
_resolve_site = storage.resolve_site


async def _fetch(ctx, site_id, path, params):
    """REST-only fetch helper — used when the site resolves to 'rest' mode.

    Callers that also have an SSH-capable equivalent branch on mode via
    _resolve_site() first; this stays REST-only intentionally.
    """
    mode, session, err = await _resolve_site(ctx, site_id)
    if err:
        return None, ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)
    if mode == "ssh":
        return None, ActionResult.error(
            "This site is connected via SSH only (no REST/Application Password) — "
            "internal routing error, this path should have used the WP-CLI branch.",
            retryable=False, code=INTERNAL,
        )
    base_url, username, pw = session
    try:
        r = await wp_get(ctx, base_url, path, username=username, app_password=pw, params=params)
    except Exception as e:
        await ctx.log(f"{path} http error: {e}", level="error")
        return None, ActionResult.error("Could not reach the site — try again.", retryable=True, code=WP_SITE_UNREACHABLE)
    if r.status_code != 200:
        retry = r.status_code >= 500 or r.status_code == 429
        return None, ActionResult.error(wp_error_message(r.status_code), retryable=retry, code=wp_error_code(r.status_code))
    # HTTPResponse.body is already-parsed JSON (list for WP collection endpoints).
    # HTTPResponse.json() raises on list bodies, so read .body directly.
    return (r.body if isinstance(r.body, list) else []), None


# ── WP-CLI (SSH) → REST-shaped dict adapters ──────────────────────────────────
# `wp post/comment/user list --format=json` returns WordPress's raw column
# names (ID, post_title, comment_ID, ...) — these adapters reshape that into
# the same field names the REST-branch converters below already expect, so
# every @chat.function has ONE conversion step regardless of which mode ran.

def _cli_post_to_rest_shape(p: dict) -> dict:
    return {"id": p.get("ID", ""), "title": {"rendered": p.get("post_title", "")},
            "status": p.get("post_status", ""), "link": p.get("guid", ""),
            "date": p.get("post_date")}


def _cli_media_to_rest_shape(p: dict) -> dict:
    return {"id": p.get("ID", ""), "title": {"rendered": p.get("post_title", "")},
            "source_url": p.get("guid", ""), "mime_type": p.get("post_mime_type", "")}


_CLI_COMMENT_STATUS = {"1": "approved", "0": "hold", "spam": "spam", "trash": "trash"}


def _cli_comment_to_rest_shape(c: dict) -> dict:
    raw_status = c.get("comment_approved", "")
    return {"id": c.get("comment_ID", ""), "author_name": c.get("comment_author", "Anonymous"),
            "status": _CLI_COMMENT_STATUS.get(raw_status, raw_status),
            "content": {"rendered": c.get("comment_content", "")},
            "post": c.get("comment_post_ID", ""), "date": c.get("comment_date", "")}


def _cli_user_to_rest_shape(u: dict) -> dict:
    roles = u.get("roles", "")
    return {"id": u.get("ID", ""), "name": u.get("display_name", "") or u.get("user_login", ""),
            "roles": [r.strip() for r in roles.split(",")] if roles else [],
            "registered_date": u.get("user_registered", "")}


def _cli_order_to_rest_shape(o: dict) -> dict:
    return {"id": o.get("id", ""), "status": o.get("status", ""),
            "total": o.get("total", ""), "currency": o.get("currency", "")}


# REST status filter -> WP-CLI's own vocabulary (WP-CLI uses "approve", not "approved").
_REST_TO_CLI_COMMENT_STATUS = {"approved": "approve", "hold": "hold", "spam": "spam", "all": "all"}


@chat.function("list_posts", description="List recent posts on a connected WordPress site.",
               action_type="read", data_model=sdl.EntityList[Post])
async def list_posts(ctx, params: ListContentParams) -> ActionResult:
    """Return recent posts — via REST for Application Password sites, or via
    `wp post list` over SSH (no REST call at all) for SSH-only sites."""
    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)
    if mode == "ssh":
        rows, cli_err = await wp_cli.list_content_cli(session, post_type="post",
                                                       limit=params.limit, search=params.search)
        if cli_err:
            return ActionResult.error(cli_err, retryable=True, code=WP_SSH_COMMAND_FAILED)
        data = [_cli_post_to_rest_shape(p) for p in rows]
    else:
        q = {"per_page": params.limit}
        if params.search:
            q["search"] = params.search
        data, fetch_err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/posts", q)
        if fetch_err:
            return fetch_err
    items = [Post(id=str(p["id"]), title=wp_title(p), kind="wp_post",
                  status=p.get("status", ""), link=p.get("link", ""), date=p.get("date")) for p in data]
    return ActionResult.success(sdl.EntityList[Post](items=items), summary=f"{len(items)} post(s)")


@chat.function("list_pages", description="List pages on a connected WordPress site.",
               action_type="read", data_model=sdl.EntityList[Page])
async def list_pages(ctx, params: ListContentParams) -> ActionResult:
    """Return pages — via REST for Application Password sites, or via
    `wp post list --post_type=page` over SSH for SSH-only sites."""
    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)
    if mode == "ssh":
        rows, cli_err = await wp_cli.list_content_cli(session, post_type="page",
                                                       limit=params.limit, search=params.search)
        if cli_err:
            return ActionResult.error(cli_err, retryable=True, code=WP_SSH_COMMAND_FAILED)
        data = [_cli_post_to_rest_shape(p) for p in rows]
    else:
        q = {"per_page": params.limit}
        if params.search:
            q["search"] = params.search
        data, fetch_err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/pages", q)
        if fetch_err:
            return fetch_err
    items = [Page(id=str(p["id"]), title=wp_title(p), kind="wp_page",
                  status=p.get("status", ""), link=p.get("link", ""), date=p.get("date")) for p in data]
    return ActionResult.success(sdl.EntityList[Page](items=items), summary=f"{len(items)} page(s)")


@chat.function("list_media", description="List media library items on a connected WordPress site.",
               action_type="read", data_model=sdl.EntityList[MediaItem])
async def list_media(ctx, params: ListMediaParams) -> ActionResult:
    """Return media items — via REST for Application Password sites, or via
    `wp post list --post_type=attachment` over SSH for SSH-only sites."""
    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)
    if mode == "ssh":
        rows, cli_err = await wp_cli.list_content_cli(session, post_type="attachment", limit=params.limit)
        if cli_err:
            return ActionResult.error(cli_err, retryable=True, code=WP_SSH_COMMAND_FAILED)
        data = [_cli_media_to_rest_shape(p) for p in rows]
    else:
        data, fetch_err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/media", {"per_page": params.limit})
        if fetch_err:
            return fetch_err
    items = [MediaItem(id=str(m["id"]), title=wp_title(m), kind="wp_media",
                       url=m.get("source_url", ""), mime_type=m.get("mime_type", "")) for m in data]
    return ActionResult.success(sdl.EntityList[MediaItem](items=items), summary=f"{len(items)} media item(s)")


@chat.function("get_site_health", description="Report read-only health for a connected WordPress site.",
               action_type="read", data_model=SiteHealth)
async def get_site_health(ctx, params: SiteIdParams) -> ActionResult:
    """Report best-effort read-only health: reachability, auth, SSL, and content counts —
    via REST for Application Password sites, or via WP-CLI over SSH for SSH-only sites."""
    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)

    if mode == "ssh":
        ok, msg, _ = await wp_cli.test_connection(session)
        posts_n, _ = await wp_cli.count_posts_cli(session, "post") if ok else (0, None)
        pages_n, _ = await wp_cli.count_posts_cli(session, "page") if ok else (0, None)
        media_n, _ = await wp_cli.count_posts_cli(session, "attachment") if ok else (0, None)
        record = await storage.get_site_record(ctx, params.site_id) or {}
        base_url = record.get("url", "")
        reachable = ok
        auth_ok = ok
        counts = {"posts": posts_n or 0, "pages": pages_n or 0, "media": media_n or 0}
    else:
        base_url, username, pw = session

        async def _call(path, per_page=1):
            try:
                return await wp_get(ctx, base_url, path, username=username, app_password=pw,
                                    params={"per_page": per_page})
            except Exception:
                return None

        me, posts_r, pages_r, media_r = await asyncio.gather(
            _call("/wp-json/wp/v2/users/me"),
            _call("/wp-json/wp/v2/posts", 100),
            _call("/wp-json/wp/v2/pages", 100),
            _call("/wp-json/wp/v2/media", 100),
        )

        def _count(r):
            return len(r.body) if r and r.status_code == 200 and isinstance(r.body, list) else 0

        reachable = me is not None
        auth_ok = me is not None and me.status_code == 200
        counts = {"posts": _count(posts_r), "pages": _count(pages_r), "media": _count(media_r)}

    health = SiteHealth(
        id=params.site_id, title=params.site_id, kind="wp_site_health",
        reachable=reachable, auth_ok=auth_ok, ssl_valid=base_url.startswith("https://"),
        content_counts=counts,
    )
    status = "✅" if auth_ok else ("⚠️" if reachable else "❌")
    return ActionResult.success(
        health,
        summary=f"{status} {params.site_id}: {counts['posts']} posts · {counts['pages']} pages · {counts['media']} media",
    )


@chat.function(
    "refresh_site",
    description="Re-check connectivity and auth for a connected WordPress site and update its stored status.",
    action_type="write",
    data_model=Site,
    effects=["wp.health_check"],
    event="wp-site-connector.refresh_site",
)
async def refresh_site(ctx, params: SiteIdParams) -> ActionResult:
    """Ping the site (REST or WP-CLI over SSH depending on how it's connected),
    update stored status, and refresh the overview panel."""
    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)
    record = await storage.get_site_record(ctx, params.site_id) or {}

    if mode == "ssh":
        ok, msg, _ = await wp_cli.test_connection(session)
        status = "connected" if ok else "error"
        base_url = record.get("url", "")
        username = record.get("username", "")
    else:
        base_url, username, pw = session
        try:
            r = await wp_get(ctx, base_url, "/wp-json/wp/v2/users/me",
                             username=username, app_password=pw)
            status = "connected" if 200 <= r.status_code < 300 else "error"
        except Exception as e:
            await ctx.log(f"refresh_site http error: {e}", level="error")
            return ActionResult.error("Could not reach the site — try again.", retryable=True, code=WP_SITE_UNREACHABLE)

    await storage.save_site_record(ctx, {**record, "status": status, "last_checked": now_iso()})
    await storage.clear_content_cache(ctx, params.site_id)

    name = record.get("name", params.site_id)
    site = Site(id=params.site_id, title=name, kind="wp_site",
                url=base_url, username=username, status=status)
    icon = "✅" if status == "connected" else "❌"
    return ActionResult.success(
        site,
        summary=f"{icon} {name}: {status}",
        refresh_panels=["sidebar", "center"],
    )


@chat.function(
    "refresh_all_sites",
    description="Re-check connectivity for all connected WordPress sites at once.",
    action_type="write",
    data_model=RefreshAllResult,
    effects=["wp.health_check"],
    event="wp-site-connector.refresh_all_sites",
)
async def refresh_all_sites(ctx, params: _NoParams) -> ActionResult:
    """Ping every connected site in parallel (REST or WP-CLI over SSH depending
    on how each is connected), update stored statuses, clear content caches."""
    rows = await storage.list_site_records(ctx)
    if not rows:
        return ActionResult.error("No sites connected.", retryable=False, code=WP_NO_SITES_CONNECTED)

    async def _check(record):
        site_id = record["id"]
        mode, session, err = await _resolve_site(ctx, site_id)
        if err:
            updated = {**record, "status": "error", "last_checked": now_iso()}
        elif mode == "ssh":
            ok, msg, _ = await wp_cli.test_connection(session)
            updated = {**record, "status": "connected" if ok else "error", "last_checked": now_iso()}
        else:
            base_url, username, pw = session
            try:
                r = await wp_get(ctx, base_url, "/wp-json/wp/v2/users/me",
                                 username=username, app_password=pw)
                status = "connected" if 200 <= r.status_code < 300 else "error"
            except Exception:
                status = "error"
            updated = {**record, "status": status, "last_checked": now_iso()}
        await storage.save_site_record(ctx, updated)
        await storage.clear_content_cache(ctx, site_id)
        return updated

    results = await asyncio.gather(*[_check(r) for r in rows])
    connected = sum(1 for r in results if r.get("status") == "connected")
    total = len(results)
    result = RefreshAllResult(
        id="refresh_all", title=f"{connected}/{total} sites connected",
        kind="refresh_all", connected=connected, total=total,
    )
    icon = "✅" if connected == total else ("⚠️" if connected > 0 else "❌")
    return ActionResult.success(
        result,
        summary=f"{icon} {connected}/{total} sites connected",
        refresh_panels=["sidebar"],
    )


@chat.function(
    "list_comments",
    description="List comments on a connected WordPress site. Use status='hold' to see comments pending moderation, 'approved' for published, 'spam' for spam.",
    action_type="read",
    data_model=sdl.EntityList[Comment],
)
async def list_comments(ctx, params: ListCommentsParams) -> ActionResult:
    """Return comments — via REST for Application Password sites, or via
    `wp comment list` over SSH for SSH-only sites."""
    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)
    if mode == "ssh":
        cli_status = _REST_TO_CLI_COMMENT_STATUS.get(params.status, params.status)
        rows, cli_err = await wp_cli.list_comments_cli(session, status=cli_status, limit=params.limit)
        if cli_err:
            return ActionResult.error(cli_err, retryable=True, code=WP_SSH_COMMAND_FAILED)
        data = [_cli_comment_to_rest_shape(c) for c in rows]
    else:
        q: dict = {"per_page": params.limit, "orderby": "date", "order": "desc"}
        if params.status != "all":
            q["status"] = params.status
        data, fetch_err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/comments", q)
        if fetch_err:
            return fetch_err
    items = [
        Comment(
            id=str(c["id"]),
            title=c.get("author_name", "Anonymous"),
            kind="wp_comment",
            status=c.get("status", ""),
            author=c.get("author_name", ""),
            snippet=(c.get("content", {}).get("rendered", "") or "")
                    .replace("<p>", "").replace("</p>", "")[:120].strip(),
            post_id=str(c.get("post", "")),
            date=c.get("date", ""),
        )
        for c in data
    ]
    pending = sum(1 for i in items if i.status == "hold")
    summary = f"{len(items)} comment(s)"
    if pending:
        summary += f" — {pending} pending moderation"
    return ActionResult.success(sdl.EntityList[Comment](items=items), summary=summary)


@chat.function(
    "list_scheduled",
    description="List posts scheduled for future publication on a connected WordPress site.",
    action_type="read",
    data_model=sdl.EntityList[Post],
)
async def list_scheduled(ctx, params: ListContentParams) -> ActionResult:
    """Return scheduled (future) posts — via REST for Application Password sites,
    or via `wp post list --post_status=future` over SSH for SSH-only sites."""
    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)
    if mode == "ssh":
        rows, cli_err = await wp_cli.list_content_cli(session, post_type="post", limit=params.limit,
                                                       search=params.search, status="future",
                                                       orderby="date", order="asc")
        if cli_err:
            return ActionResult.error(cli_err, retryable=True, code=WP_SSH_COMMAND_FAILED)
        data = [_cli_post_to_rest_shape(p) for p in rows]
    else:
        q: dict = {"per_page": params.limit, "status": "future", "orderby": "date", "order": "asc"}
        if params.search:
            q["search"] = params.search
        data, fetch_err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/posts", q)
        if fetch_err:
            return fetch_err
    items = [Post(id=str(p["id"]), title=wp_title(p), kind="wp_post",
                  status="scheduled", link=p.get("link", ""),
                  date=p.get("date", "")) for p in data]
    return ActionResult.success(sdl.EntityList[Post](items=items),
                                summary=f"{len(items)} scheduled post(s)")


@chat.function(
    "list_users",
    description="List recently registered users on a connected WordPress site.",
    action_type="read",
    data_model=sdl.EntityList[WPUser],
)
async def list_users(ctx, params: ListContentParams) -> ActionResult:
    """Return users — via REST for Application Password sites, or via
    `wp user list` over SSH for SSH-only sites."""
    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)
    if mode == "ssh":
        rows, cli_err = await wp_cli.list_users_cli(session, limit=params.limit, search=params.search)
        if cli_err:
            return ActionResult.error(cli_err, retryable=True, code=WP_SSH_COMMAND_FAILED)
        data = [_cli_user_to_rest_shape(u) for u in rows]
    else:
        q: dict = {"per_page": params.limit, "orderby": "registered_date", "order": "desc"}
        if params.search:
            q["search"] = params.search
        data, fetch_err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/users", q)
        if fetch_err:
            return fetch_err
    items = [
        WPUser(
            id=str(u["id"]),
            title=u.get("name", ""),
            kind="wp_user",
            role=", ".join(u.get("roles", [])),
            registered=(u.get("registered_date", "") or "")[:10],
        )
        for u in data
    ]
    return ActionResult.success(sdl.EntityList[WPUser](items=items),
                                summary=f"{len(items)} user(s)")


@chat.function(
    "list_orders",
    description="List WooCommerce orders on a connected WordPress site. Returns an error if WooCommerce is not installed.",
    action_type="read",
    data_model=sdl.EntityList[Order],
)
async def list_orders(ctx, params: ListMediaParams) -> ActionResult:
    """Return WooCommerce orders — via REST for Application Password sites, or via
    `wp wc shop_order list` over SSH for SSH-only sites."""
    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)
    if mode == "ssh":
        rows, cli_err = await wp_cli.list_orders_cli(session, limit=params.limit)
        if cli_err:
            code = WP_WOOCOMMERCE_NOT_INSTALLED if "WooCommerce is not installed" in cli_err else WP_SSH_COMMAND_FAILED
            return ActionResult.error(cli_err, retryable=False, code=code)
        data = [_cli_order_to_rest_shape(o) for o in rows]
    else:
        base_url, username, pw = session
        try:
            r = await wp_get(ctx, base_url, "/wp-json/wc/v3/orders",
                             username=username, app_password=pw,
                             params={"per_page": params.limit, "orderby": "date", "order": "desc"})
        except Exception as e:
            await ctx.log(f"list_orders http error: {e}", level="error")
            return ActionResult.error("Could not reach the site.", retryable=True, code=WP_SITE_UNREACHABLE)
        if r.status_code == 404:
            return ActionResult.error("WooCommerce is not installed on this site.", retryable=False,
                                      code=WP_WOOCOMMERCE_NOT_INSTALLED)
        if r.status_code in (401, 403):
            return ActionResult.error(
                "WooCommerce requires additional permissions — ensure the Application Password user has shop manager or admin role.",
                retryable=False, code=PERMISSION_DENIED,
            )
        if r.status_code != 200 or not isinstance(r.body, list):
            return ActionResult.error(wp_error_message(r.status_code), retryable=r.status_code >= 500,
                                      code=wp_error_code(r.status_code))
        data = r.body
    items = [
        Order(
            id=str(o["id"]),
            title=f"Order #{o['id']}",
            kind="wc_order",
            status=o.get("status", ""),
            total=str(o.get("total", "")),
            currency=o.get("currency", ""),
        )
        for o in data
    ]
    return ActionResult.success(sdl.EntityList[Order](items=items),
                                summary=f"{len(items)} order(s)")


@chat.function(
    "list_plugins",
    description="List installed plugins on a connected WordPress site — name, active/inactive status, version, and whether an update is available. Requires SSH access (add_ssh) since WordPress core doesn't expose plugin management over REST.",
    action_type="read",
    data_model=sdl.EntityList[Plugin],
)
async def list_plugins(ctx, params: SiteIdParams) -> ActionResult:
    """List plugins via `wp plugin list` over SSH. SSH-only — WordPress core's
    REST API has no plugin-listing endpoint without a companion plugin, so
    there is no REST fallback path here (unlike list_posts/list_comments/etc)."""
    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "SSH not configured for this site. Use add_ssh first.", retryable=False,
            code=WP_SSH_NOT_CONFIGURED,
        )
    rows, cli_err = await wp_cli.list_plugins_cli(cred)
    if cli_err:
        return ActionResult.error(cli_err, retryable=True, code=WP_SSH_COMMAND_FAILED)
    items = [
        Plugin(
            id=p.get("name", ""),
            title=p.get("name", ""),
            kind="wp_plugin",
            status=p.get("status", ""),
            version=p.get("version", ""),
            update_available=p.get("update_version", "") if p.get("update") == "available" else "",
        )
        for p in rows
    ]
    return ActionResult.success(sdl.EntityList[Plugin](items=items),
                                summary=f"{len(items)} plugin(s)")


@chat.function(
    "list_custom_posts",
    description="List items of a custom post type on a connected WordPress site. Use post_type= with the REST base slug (e.g. 'products', 'events', 'portfolio'). Check the site's panel to see available post types.",
    action_type="read",
    data_model=sdl.EntityList[Post],
)
async def list_custom_posts(ctx, params: ListCustomPostsParams) -> ActionResult:
    """Return items of the given custom post type — via REST for Application Password
    sites, or via `wp post list --post_type=<type>` over SSH for SSH-only sites."""
    mode, session, err = await _resolve_site(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False, code=WP_SITE_NOT_CONNECTED)
    if mode == "ssh":
        rows, cli_err = await wp_cli.list_content_cli(session, post_type=params.post_type,
                                                       limit=params.limit, search=params.search)
        if cli_err:
            return ActionResult.error(cli_err, retryable=True, code=WP_SSH_COMMAND_FAILED)
        data = [_cli_post_to_rest_shape(p) for p in rows]
    else:
        q: dict = {"per_page": params.limit, "orderby": "date", "order": "desc"}
        if params.search:
            q["search"] = params.search
        data, fetch_err = await _fetch(ctx, params.site_id, f"/wp-json/wp/v2/{params.post_type}", q)
        if fetch_err:
            return fetch_err
    items = [Post(id=str(p["id"]), title=wp_title(p), kind=f"wp_cpt_{params.post_type}",
                  status=p.get("status", ""), link=p.get("link", ""),
                  date=p.get("date", "")) for p in data]
    return ActionResult.success(sdl.EntityList[Post](items=items),
                                summary=f"{len(items)} {params.post_type} item(s)")


@chat.function(
    "get_server_info",
    description="Get server information for a WordPress site via SSH + WP-CLI: PHP version, WordPress version, available plugin/theme/core updates, cron job count, database size. SSH must be configured first with add_ssh.",
    action_type="write",
    data_model=ServerInfo,
    effects=["wp.health_check"],
    event="wp-site-connector.get_server_info",
)
async def get_server_info(ctx, params: SiteIdParams) -> ActionResult:
    """Run WP-CLI commands via SSH and return server/site diagnostics."""
    record = await storage.get_site_record(ctx, params.site_id) or {}
    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "SSH not configured for this site. Use add_ssh first.", retryable=False,
            code=WP_SSH_NOT_CONFIGURED,
        )
    try:
        info = await wp_cli.get_server_info(cred)
    except Exception as e:
        await ctx.log(f"get_server_info: {e}", level="error")
        return ActionResult.error("SSH connection failed — check credentials.", retryable=True,
                                  code=WP_SSH_CONNECTION_FAILED)

    if "error" in info:
        await storage.save_site_record(ctx, {**record, "ssh_error": info["error"]})
        return ActionResult.error(f"SSH/WP-CLI error: {info['error']}", retryable=True,
                                  code=WP_SSH_COMMAND_FAILED, refresh_panels=["center"])

    result = ServerInfo(
        id=params.site_id,
        title=f"Server: {params.site_id}",
        kind="server_info",
        wp_version=info["wp_version"],
        php_version=info["php_version"],
        plugin_updates=info["plugin_updates"],
        plugin_updates_list=info["plugin_updates_list"],
        theme_updates=info["theme_updates"],
        theme_updates_list=info["theme_updates_list"],
        core_update=info["core_update"],
        core_update_version=info["core_update_version"],
        cron_count=info["cron_count"],
        db_size_mb=info["db_size_mb"],
    )
    updates = result.plugin_updates + result.theme_updates + (1 if result.core_update else 0)

    # Only persist if we actually got real data (SSH succeeded)
    if not result.wp_version:
        return ActionResult.error(
            "SSH connected but WP-CLI returned no data — check the WordPress path and WP-CLI installation.",
            retryable=True, code=WP_SSH_COMMAND_FAILED,
        )

    await storage.save_site_record(ctx, {
        **record,
        "wp_version":          result.wp_version,
        "php_version":         result.php_version,
        "db_size_mb":          result.db_size_mb,
        "cron_count":          result.cron_count,
        "pending_updates":     updates,
        "plugin_updates_list": info["plugin_updates_list"],
        "theme_updates_list":  info["theme_updates_list"],
        "server_last_checked": now_iso(),
    })

    icon = "⚠️" if updates else "✅"
    summary = f"{icon} WP {result.wp_version} · PHP {result.php_version}"
    if updates:
        summary += f" · {updates} update(s) available"
    return ActionResult.success(result, summary=summary, refresh_panels=["sidebar", "center"])
