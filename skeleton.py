"""wp-site-connector · Skeleton tools."""
import logging

from app import ext
import storage

log = logging.getLogger("wp-site-connector")


@ext.skeleton(
    "sites_overview",
    alert=True,
    # 120s, down from 300s but deliberately not the 60s used by the busier
    # sections. The set of connected sites only changes on an explicit
    # connect_site / forget_site — rare and user-initiated — so the staleness
    # risk is far lower here than for counters that move on their own. What 300s
    # did cost was the moment that matters most: right after connecting a site,
    # the assistant could still claim none was connected for five minutes.
    #
    # The platform ticks on the MINIMUM ttl across a user's sections, so this
    # value doesn't set the tick — it just means this section refreshes every
    # other tick instead of every one, which is the right trade for a snapshot
    # this static.
    ttl=120,
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
        # `sites_connected` is a real COUNT, not len(sites): the list is capped,
        # so its length would report the page size as the total. The classifier
        # reads this number to decide whether the user has sites at all —
        # feeding it a cap disguised as a total is exactly the quiet blindness
        # this section exists to remove.
        total = await storage.count_site_records(ctx)
        return {"response": {"sites_connected": total, "sites": sites}}
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
