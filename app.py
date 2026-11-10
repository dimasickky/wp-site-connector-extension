from imperal_sdk import Extension, ChatExtension

ext = Extension(
    "wp-site-connector-extension",
    version="0.12.0",
    capabilities=["wp-site-connector-extension:read", "wp-site-connector-extension:write"],
    display_name="WP Site Connector",
    description="Securely connect WordPress sites, publish posts, upload media, and inspect site health.",
    icon="icon.svg",
    actions_explicit=True,
)

# ─── Semantic Omnisearch Provider (SDK 5.15+) ─────────────────────────────── #

from imperal_sdk.search import SearchEntityResult
import storage


@ext.search_provider("wp_sites", description="Search connected WordPress sites by name or URL")
async def search_provider_wp_sites(ctx, query: str) -> list[SearchEntityResult]:
    """Provide connected WordPress sites for global Cmd+K omnisearch."""
    if not query or not query.strip():
        return []
    try:
        rows = await storage.list_site_records(ctx)
        q = query.strip().lower()
        matches = [
            r for r in rows
            if q in (r.get("name") or "").lower() or q in (r.get("url") or "").lower()
        ]
        results = []
        for r in matches[:10]:
            sid = r["id"]
            title = r.get("name") or r.get("url") or sid
            url = r.get("url", "")
            results.append(SearchEntityResult(
                id=sid,
                title=title,
                type="wp_site",
                snippet=f"Status: {r.get('status', 'connected')} · {url}",
                url=f"/workspace/wp-site-connector?site_id={sid}",
                metadata={"url": url, "status": r.get("status")},
            ))
        return results
    except Exception:
        return []


chat = ChatExtension(ext, tool_name="wp-site-connector", description="Connect, inspect, and publish to WordPress sites")


# ─── Secrets (app-scope: developer-owned, shared by all users) ────────────── #

ext.secret(
    name="wp_encryption_key",
    description=(
        "Fernet key used to encrypt WordPress Application Passwords and SSH "
        "credentials before they reach storage. Shared across all users; "
        "generate once with `Fernet.generate_key()` and set in Developer "
        "Portal → Secrets."
    ),
    scope="app",
    required=True,
    max_bytes=256,
)(lambda: None)


@ext.health_check
async def health_check(ctx) -> dict:
    """Liveness probe for the extension."""
    return {"status": "ok"}


