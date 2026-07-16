from app import ext
import storage


@ext.skeleton("sites_overview", description="How many WordPress sites are connected.")
async def sites_overview(ctx):
    """Ambient context for the intent classifier: count of connected sites."""
    rows = await storage.list_site_records(ctx)
    return {"response": {"sites_connected": len(rows)}}
