import json

import crypto_util

SITES_COLLECTION = "sites"
CREDS_COLLECTION = "creds"


# ── Site records ──────────────────────────────────────────────────────────────

# Explicit ceiling for the one read that is genuinely a LIST.
#
# Cursor paging is not available: `Page` carries `cursor`/`has_more` and
# `StoreProtocol` advertises a `cursor=` argument, but the real client
# (`imperal_sdk/store/client.py`, SDK 5.9.12) accepts only `limit` — page 2
# cannot be requested. So: a named ceiling instead of a bare `limit=100` that
# reads like "all of them", and `where=` everywhere the read is really a point
# lookup.
_SITES_PAGE_LIMIT = 100


async def _find_doc(ctx, collection, site_id):
    """Find one document by site id — a point lookup, not a scan.

    Two `where=` queries rather than one because the collections genuinely
    disagree on the key name: SITES stores the id under `id` (see
    handlers_connect), while CREDS / CACHE / SSH_CREDS store it under
    `site_id`. The old code papered over that by reading the first 100 rows and
    checking both keys in Python — which also meant a site past row 100 became
    invisible: not "slow", but unfindable, so its credentials and cache
    silently ceased to exist.

    `site_id` first because that is the majority of callers; `id` second for
    SITES. Both are exact-match on a string id, so unlike telegram's chat_id
    there is no int/str mismatch to worry about here.
    """
    page = await ctx.store.query(collection, where={"site_id": site_id}, limit=1)
    if page.data:
        return page.data[0]
    page = await ctx.store.query(collection, where={"id": site_id}, limit=1)
    return page.data[0] if page.data else None


async def list_site_records(ctx):
    """Every site this user connected (capped at `_SITES_PAGE_LIMIT`).

    A real list, and the one place the cap is a genuine limitation rather than
    a formality. 100 connected WordPress sites for a single user is far outside
    normal use, and paging is impossible on this SDK — so the cap is named and
    documented instead of hidden in the call.
    """
    page = await ctx.store.query(SITES_COLLECTION, limit=_SITES_PAGE_LIMIT)
    return [doc.data for doc in page.data]


async def count_site_records(ctx) -> int:
    """How many sites this user connected — a server-side COUNT, no cap.

    Use this for totals instead of `len(await list_site_records(ctx))`, which
    would report the page size once the cap is reached.
    """
    return await ctx.store.count(SITES_COLLECTION)


async def get_site_record(ctx, site_id):
    doc = await _find_doc(ctx, SITES_COLLECTION, site_id)
    return doc.data if doc else None


async def save_site_record(ctx, record):
    doc = await _find_doc(ctx, SITES_COLLECTION, record["id"])
    if doc:
        await ctx.store.update(SITES_COLLECTION, doc.id, record)
    else:
        await ctx.store.create(SITES_COLLECTION, record)


async def delete_site_record(ctx, site_id):
    doc = await _find_doc(ctx, SITES_COLLECTION, site_id)
    if doc:
        await ctx.store.delete(SITES_COLLECTION, doc.id)


# ── Credentials (encrypted at rest — Fernet key from Developer Portal → Secrets) ──

async def get_credential(ctx, site_id):
    doc = await _find_doc(ctx, CREDS_COLLECTION, site_id)
    if not doc:
        return None
    stored = doc.data.get("password")
    return await crypto_util.decrypt_value(ctx, stored) if stored else None


async def set_credential(ctx, site_id, app_password):
    encrypted = await crypto_util.encrypt_value(ctx, app_password)
    doc = await _find_doc(ctx, CREDS_COLLECTION, site_id)
    if doc:
        await ctx.store.update(CREDS_COLLECTION, doc.id,
                               {"site_id": site_id, "password": encrypted})
    else:
        await ctx.store.create(CREDS_COLLECTION,
                               {"site_id": site_id, "password": encrypted})


async def delete_credential(ctx, site_id):
    doc = await _find_doc(ctx, CREDS_COLLECTION, site_id)
    if doc:
        await ctx.store.delete(CREDS_COLLECTION, doc.id)


# ── Content cache (posts/pages/media fetched once, tabs switch from cache) ────

CACHE_COLLECTION = "wp_cache"
SSH_CREDS_COLLECTION = "ssh_creds"


async def get_content_cache(ctx, site_id):
    doc = await _find_doc(ctx, CACHE_COLLECTION, site_id)
    return doc.data if doc else None


async def set_content_cache(ctx, site_id, posts=None, pages=None, media=None,
                            comments=None, scheduled=None, users=None, orders=None,
                            dynamic=None):
    data = {
        "site_id":   site_id,
        "posts":     posts or [],
        "pages":     pages or [],
        "media":     media or [],
        "comments":  comments or [],
        "scheduled": scheduled or [],
        "users":     users or [],
        "orders":    orders,   # None = WC not installed; [] = installed but no orders
        "dynamic":   dynamic or {},  # CPTs, taxonomies, metadata
    }
    doc = await _find_doc(ctx, CACHE_COLLECTION, site_id)
    if doc:
        await ctx.store.update(CACHE_COLLECTION, doc.id, data)
    else:
        await ctx.store.create(CACHE_COLLECTION, data)


PENDING_SSH_COLLECTION = "pending_ssh"


async def set_pending_ssh_site(ctx, site_id):
    page = await ctx.store.query(PENDING_SSH_COLLECTION, limit=1)
    if page.data:
        await ctx.store.update(PENDING_SSH_COLLECTION, page.data[0].id, {"site_id": site_id})
    else:
        await ctx.store.create(PENDING_SSH_COLLECTION, {"site_id": site_id})


async def get_pending_ssh_site(ctx) -> str:
    page = await ctx.store.query(PENDING_SSH_COLLECTION, limit=1)
    return page.data[0].data.get("site_id", "") if page.data else ""


_SSH_SECRET_FIELDS = ("key", "password")


async def get_ssh_cred(ctx, site_id):
    """Return the SSH credential dict with 'key'/'password' decrypted in-memory."""
    doc = await _find_doc(ctx, SSH_CREDS_COLLECTION, site_id)
    if not doc:
        return None
    cred = dict(doc.data)
    for field in _SSH_SECRET_FIELDS:
        if cred.get(field):
            cred[field] = await crypto_util.decrypt_value(ctx, cred[field])
    return cred


async def set_ssh_cred(ctx, site_id, cred: dict):
    """Persist an SSH credential dict, encrypting 'key'/'password' before storage.

    Non-secret fields (host, port, user, wp_path, host_key_fingerprint) are
    stored as-is.
    """
    data = {"site_id": site_id, **cred}
    for field in _SSH_SECRET_FIELDS:
        if data.get(field):
            data[field] = await crypto_util.encrypt_value(ctx, data[field])
    doc = await _find_doc(ctx, SSH_CREDS_COLLECTION, site_id)
    if doc:
        await ctx.store.update(SSH_CREDS_COLLECTION, doc.id, data)
    else:
        await ctx.store.create(SSH_CREDS_COLLECTION, data)


async def delete_ssh_cred(ctx, site_id):
    doc = await _find_doc(ctx, SSH_CREDS_COLLECTION, site_id)
    if doc:
        await ctx.store.delete(SSH_CREDS_COLLECTION, doc.id)


async def has_ssh(ctx, site_id) -> bool:
    return await get_ssh_cred(ctx, site_id) is not None


async def clear_content_cache(ctx, site_id):
    doc = await _find_doc(ctx, CACHE_COLLECTION, site_id)
    if doc:
        await ctx.store.delete(CACHE_COLLECTION, doc.id)


# ── Auth resolution (shared by publish + read handlers) ────────────────────────

async def resolve_site(ctx, site_id):
    """Look up a site and decide which client to read/publish through.

    Returns (mode, session, error) where mode is 'rest' (session =
    (base_url, username, password)) or 'ssh' (session = the decrypted SSH
    credential dict for wp_cli). A site connected via connect_site_ssh has
    no Application Password at all, so REST is never attempted for it.
    """
    record = await get_site_record(ctx, site_id)
    if not record:
        return None, None, "No connected site with that id."
    if record.get("auth_mode") == "ssh":
        cred = await get_ssh_cred(ctx, site_id)
        if not cred:
            return None, None, "Stored SSH credential is missing — reconnect the site."
        return "ssh", cred, None
    pw = await get_credential(ctx, site_id)
    if not pw:
        return None, None, "Stored credential is missing — reconnect the site."
    return "rest", (record["url"], record.get("username", ""), pw), None
