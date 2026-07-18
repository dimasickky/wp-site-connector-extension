from urllib.parse import urlparse

from app import chat
from imperal_sdk import ActionResult
from models import ConnectSiteParams, ConnectSiteSSHParams, SiteIdParams, Site, AddSSHParams
from wp_client import normalize_base_url, site_id_from_url, site_id_from_host, wp_get, wp_error_message, wp_error_code, now_iso
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD, INTERNAL
from error_codes import (WP_SITE_NOT_CONNECTED, WP_SITE_UNREACHABLE,
                         WP_SSH_CONNECTION_FAILED, WP_SSH_KEY_INVALID)
import storage
import wp_cli


@chat.function(
    "connect_site",
    description="Connect a WordPress site by URL, username, and Application Password.",
    action_type="write",
    data_model=Site,
    effects=["wp.connect"],
    event="wp-site-connector.connect_site",
)
async def connect_site(ctx, params: ConnectSiteParams) -> ActionResult:
    """Validate WP credentials via /users/me, then persist the site record and Application Password."""
    try:
        base_url = normalize_base_url(params.url)
    except ValueError:
        return ActionResult.error("Site URL must start with https://", retryable=False,
                                  code=VALIDATION_MISSING_FIELD)

    site_id = site_id_from_url(base_url)
    try:
        r = await wp_get(ctx, base_url, "/wp-json/wp/v2/users/me",
                         username=params.username, app_password=params.app_password)
    except Exception as e:
        await ctx.log(f"connect_site http error: {e}", level="error")
        return ActionResult.error("Could not reach the site — check the URL and try again.", retryable=True,
                                  code=WP_SITE_UNREACHABLE)

    if not (200 <= r.status_code < 300):
        return ActionResult.error(wp_error_message(r.status_code),
                                  retryable=r.status_code >= 500 or r.status_code == 429,
                                  code=wp_error_code(r.status_code))

    name = urlparse(base_url).netloc or base_url
    record = {"id": site_id, "name": name, "url": base_url, "username": params.username,
              "status": "connected", "last_checked": now_iso()}
    await storage.save_site_record(ctx, record)
    try:
        await storage.set_credential(ctx, site_id, params.app_password)
    except Exception as e:
        await ctx.log(f"connect_site: credential save failed: {e}", level="error")
        await storage.delete_site_record(ctx, site_id)
        return ActionResult.error("Could not save credentials — try again.", retryable=True, code=INTERNAL)

    site = Site(id=site_id, title=name, kind="wp_site", url=base_url,
                username=params.username, status="connected")
    return ActionResult.success(site, summary=f"Connected {name}", refresh_panels=["sidebar"])


@chat.function(
    "connect_site_ssh",
    description=(
        "Connect a WordPress site over SSH ONLY, without a WordPress Application Password. "
        "Requires SSH access and WP-CLI on the server. Publishing/reading content for this site "
        "will then run entirely through WP-CLI over SSH instead of the REST API."
    ),
    action_type="write",
    data_model=Site,
    effects=["wp.connect", "wp.ssh_connect"],
    event="wp-site-connector.connect_site_ssh",
)
async def connect_site_ssh(ctx, params: ConnectSiteSSHParams) -> ActionResult:
    """Validate SSH + WP-CLI, derive the site's real URL via `wp option get siteurl`,
    then persist the site record (auth_mode='ssh') and SSH credential — no Application
    Password or REST call involved anywhere in this path."""
    if not params.ssh_key and not params.ssh_password:
        return ActionResult.error("Provide either ssh_key or ssh_password.", retryable=False,
                                  code=VALIDATION_MISSING_FIELD)

    cred = {
        "host": params.ssh_host,
        "port": params.ssh_port,
        "user": params.ssh_user,
        "wp_path": params.wp_path,
    }
    if params.ssh_key:
        normalized_key, key_err = wp_cli.normalize_ssh_key(params.ssh_key)
        if key_err:
            return ActionResult.error(key_err, retryable=False, code=WP_SSH_KEY_INVALID)
        cred["key"] = normalized_key
    else:
        cred["password"] = params.ssh_password

    ok, msg, host_key = await wp_cli.test_connection(cred)
    if not ok:
        return ActionResult.error(f"SSH connection failed: {msg}", retryable=True,
                                  code=WP_SSH_CONNECTION_FAILED)
    if host_key:
        cred["host_key"] = host_key

    site_url, url_err = await wp_cli.get_site_url(cred)
    if url_err:
        return ActionResult.error(f"Connected over SSH but could not read the site URL: {url_err}", retryable=True,
                                  code=WP_SSH_CONNECTION_FAILED)

    try:
        base_url = normalize_base_url(site_url) if site_url.startswith("https://") else site_url.rstrip("/")
    except ValueError:
        base_url = site_url.rstrip("/")
    site_id = site_id_from_url(base_url) if "://" in base_url else site_id_from_host(params.ssh_host)
    name = urlparse(base_url).netloc or base_url

    record = {"id": site_id, "name": name, "url": base_url, "username": "", "auth_mode": "ssh",
              "status": "connected", "last_checked": now_iso(), "ssh_host": params.ssh_host}
    await storage.save_site_record(ctx, record)
    try:
        await storage.set_ssh_cred(ctx, site_id, cred)
    except Exception as e:
        await ctx.log(f"connect_site_ssh: credential save failed: {e}", level="error")
        await storage.delete_site_record(ctx, site_id)
        return ActionResult.error("Could not save credentials — try again.", retryable=True, code=INTERNAL)

    site = Site(id=site_id, title=name, kind="wp_site", url=base_url,
                username="", status="connected", auth_mode="ssh")
    return ActionResult.success(
        site, summary=f"Connected {name} over SSH — WordPress {msg}", refresh_panels=["sidebar"])


# forget_site IS LLM-visible by design: takes only site_id (no credential in args).
# The web-kernel shows the KAV confirmation card automatically for action_type="destructive".
@chat.function(
    "forget_site",
    description="Disconnect a WordPress site and delete its stored credential.",
    action_type="destructive",
    data_model=Site,
    effects=["wp.disconnect"],
    event="wp-site-connector.forget_site",
)
async def forget_site(ctx, params: SiteIdParams) -> ActionResult:
    """Remove the site record and its stored Application Password after user confirmation."""
    record = await storage.get_site_record(ctx, params.site_id)
    if not record:
        return ActionResult.error("No connected site with that id.", retryable=False,
                                  code=WP_SITE_NOT_CONNECTED)
    await storage.delete_site_record(ctx, params.site_id)
    await storage.clear_content_cache(ctx, params.site_id)
    try:
        await storage.delete_credential(ctx, params.site_id)
    except Exception as e:
        # Site record is already deleted — orphaned credential is harmless.
        await ctx.log(f"forget_site: credential cleanup failed: {e}", level="error")
    site = Site(id=params.site_id, title=record.get("name", params.site_id), kind="wp_site",
                url=record.get("url", ""), username=record.get("username", ""), status="disconnected")
    await storage.delete_ssh_cred(ctx, params.site_id)
    return ActionResult.success(
        site, summary=f"Disconnected {record.get('name', params.site_id)}",
        refresh_panels=["sidebar", "center"])


@chat.function(
    "add_ssh",
    description="Add SSH access to a connected WordPress site to enable WP-CLI features: PHP version, plugin/theme/core update counts, cron jobs, database size.",
    action_type="write",
    data_model=Site,
    effects=["wp.ssh_connect"],
    event="wp-site-connector.add_ssh",
)
async def add_ssh(ctx, params: AddSSHParams) -> ActionResult:
    """Validate SSH connection + WP-CLI, then store credentials."""
    site_id = params.site_id or await storage.get_pending_ssh_site(ctx)
    if not site_id:
        return ActionResult.error("Could not determine which site to connect — open Add SSH from the site panel.", retryable=False,
                                  code=WP_SITE_NOT_CONNECTED)
    if not params.ssh_key and not params.ssh_password:
        return ActionResult.error("Provide either ssh_key or ssh_password.", retryable=False,
                                  code=VALIDATION_MISSING_FIELD)

    cred = {
        "host": params.ssh_host,
        "port": params.ssh_port,
        "user": params.ssh_user,
        "wp_path": params.wp_path,
    }
    if params.ssh_key:
        normalized_key, key_err = wp_cli.normalize_ssh_key(params.ssh_key)
        if key_err:
            return ActionResult.error(key_err, retryable=False, code=WP_SSH_KEY_INVALID)
        cred["key"] = normalized_key
    else:
        cred["password"] = params.ssh_password

    ok, msg, host_key = await wp_cli.test_connection(cred)
    if not ok:
        return ActionResult.error(f"SSH connection failed: {msg}", retryable=True,
                                  code=WP_SSH_CONNECTION_FAILED)
    if host_key:
        cred["host_key"] = host_key

    await storage.set_ssh_cred(ctx, site_id, cred)
    await storage.clear_content_cache(ctx, site_id)

    record = await storage.get_site_record(ctx, site_id) or {}
    # Store ssh_host in the record so the sidebar can read SSH status without extra queries
    await storage.save_site_record(ctx, {**record, "ssh_host": params.ssh_host})

    site = Site(id=site_id, title=record.get("name", site_id),
                kind="wp_site", url=record.get("url", ""),
                username=record.get("username", ""), status="connected")
    return ActionResult.success(
        site,
        summary=f"SSH connected to {params.ssh_host} — WordPress {msg}",
        refresh_panels=["sidebar", "center"],
    )


@chat.function(
    "remove_ssh",
    description="Remove SSH access from a connected WordPress site.",
    action_type="write",
    data_model=Site,
    effects=["wp.ssh_disconnect"],
    event="wp-site-connector.remove_ssh",
)
async def remove_ssh(ctx, params: SiteIdParams) -> ActionResult:
    """Delete stored SSH credentials for the site."""
    await storage.delete_ssh_cred(ctx, params.site_id)
    await storage.clear_content_cache(ctx, params.site_id)
    record = await storage.get_site_record(ctx, params.site_id) or {}
    # Remove all SSH-derived fields from the record
    for field in ("ssh_host", "wp_version", "php_version", "db_size_mb", "cron_count",
                  "pending_updates", "plugin_updates_list", "theme_updates_list",
                  "server_last_checked"):
        record.pop(field, None)
    await storage.save_site_record(ctx, record)
    site = Site(id=params.site_id, title=record.get("name", params.site_id),
                kind="wp_site", url=record.get("url", ""),
                username=record.get("username", ""), status="connected")
    return ActionResult.success(site, summary="SSH access removed.",
                                refresh_panels=["center"])
