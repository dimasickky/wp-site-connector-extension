"""wp-site-connector · Skeleton tools."""
import logging

from app import ext
import storage

log = logging.getLogger("wp-site-connector")


@ext.skeleton(
    "sites_overview",
    alert=True,
    ttl=300,
    description="Connected WordPress sites — id, title, url per site.",
)
async def sites_overview(ctx):
    """Ambient context for the intent classifier: connected WordPress sites."""
    try:
        rows = await storage.list_site_records(ctx)
        sites = [
            {"id": r["id"], "title": r.get("name", r["id"]), "url": r.get("url", "")}
            for r in rows
        ]
        return {"response": {"sites_connected": len(sites), "sites": sites}}
    except Exception as e:
        log.error("skeleton refresh failed: %s", e)
        return {"response": {"sites_connected": 0, "sites": []}}


@ext.tool(
    "skeleton_alert_sites_overview",
    description="Alert on sites connected or disconnected.",
)
async def skeleton_alert_sites_overview(
    ctx,
    old: dict | None = None,
    new: dict | None = None,
) -> dict:
    """Called by platform when sites_overview snapshot changes between ticks."""
    if not old or not new:
        return {"response": ""}

    old_ids = {s["id"] for s in old.get("sites", [])}
    new_ids = {s["id"] for s in new.get("sites", [])}
    added = new_ids - old_ids
    removed = old_ids - new_ids

    if not added and not removed:
        return {"response": ""}

    parts = []
    if added:
        parts.append(f"{len(added)} site{'s' if len(added) > 1 else ''} connected")
    if removed:
        parts.append(f"{len(removed)} site{'s' if len(removed) > 1 else ''} disconnected")

    return {"response": "; ".join(parts)}
