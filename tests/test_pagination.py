"""Store reads must not confuse a page size with a quantity.

Two distinct bugs are pinned here.

1. `_find_doc` was a scan of the first 100 rows that checked two possible key
   names in Python. A site past row 100 was not merely slow to find — it was
   *unfindable*, so its credentials, SSH record and cache silently ceased to
   exist while the site still showed up in listings. It is now a `where=` point
   lookup, and it still has to honour both key spellings, because the
   collections genuinely disagree: SITES stores the id under `id`, while
   CREDS / CACHE / SSH_CREDS store it under `site_id`.

2. `list_sites` and the skeleton reported `len(<capped list>)` as the number of
   connected sites — a cap masquerading as a total. Both now use a real
   server-side COUNT, and `list_sites` marks a truncated page via
   `EntityList.has_more` instead of quietly returning a partial answer that
   reads like a complete one.
"""
import pytest
from imperal_sdk.testing import MockContext

import storage


@pytest.mark.asyncio
async def test_find_doc_locates_site_far_beyond_the_old_scan_window():
    """A site past row 100 must still be findable (SITES uses the `id` key)."""
    ctx = MockContext(user_id="u1")

    for i in range(150):
        await ctx.store.create(storage.SITES_COLLECTION, {"id": f"site-{i}"})
    await ctx.store.create(storage.SITES_COLLECTION, {"id": "target-site"})

    doc = await storage._find_doc(ctx, storage.SITES_COLLECTION, "target-site")
    assert doc is not None, (
        "a site past the 100-row mark used to be invisible — with it, its "
        "credentials and cache effectively vanished"
    )
    assert doc.data["id"] == "target-site"


@pytest.mark.asyncio
async def test_find_doc_honours_the_site_id_key_too():
    """CREDS / CACHE / SSH_CREDS store the id under `site_id`, not `id`."""
    ctx = MockContext(user_id="u1")

    for i in range(120):
        await ctx.store.create(storage.CREDS_COLLECTION, {"site_id": f"s-{i}"})
    await ctx.store.create(
        storage.CREDS_COLLECTION, {"site_id": "target", "blob": "x"},
    )

    doc = await storage._find_doc(ctx, storage.CREDS_COLLECTION, "target")
    assert doc is not None, "the `site_id` spelling must keep working"
    assert doc.data["blob"] == "x"


@pytest.mark.asyncio
async def test_find_doc_returns_none_for_unknown_id():
    """A miss stays a miss — the point lookup must not invent a match."""
    ctx = MockContext(user_id="u1")
    await ctx.store.create(storage.SITES_COLLECTION, {"id": "a"})

    assert await storage._find_doc(ctx, storage.SITES_COLLECTION, "b") is None


@pytest.mark.asyncio
async def test_count_site_records_is_not_capped_by_the_list_limit():
    """The total must exceed the list cap, which len() never could."""
    ctx = MockContext(user_id="u1")

    over_cap = storage._SITES_PAGE_LIMIT + 25
    for i in range(over_cap):
        await ctx.store.create(storage.SITES_COLLECTION, {"id": f"site-{i}"})

    assert await storage.count_site_records(ctx) == over_cap

    rows = await storage.list_site_records(ctx)
    assert len(rows) == storage._SITES_PAGE_LIMIT, (
        "the list is capped on purpose — that is precisely why len() must not "
        "be used as the total"
    )


@pytest.mark.asyncio
async def test_list_sites_reports_a_real_total_and_flags_truncation():
    """list_sites must not pass its page size off as the number of sites."""
    from handlers_read import list_sites

    ctx = MockContext(user_id="u1")
    over_cap = storage._SITES_PAGE_LIMIT + 10
    for i in range(over_cap):
        await ctx.store.create(
            storage.SITES_COLLECTION,
            {"id": f"site-{i}", "name": f"Site {i}", "url": f"https://s{i}.test"},
        )

    result = await list_sites(ctx, None)
    assert result.success
    assert result.data.total == over_cap, "total must be the real COUNT"
    assert result.data.has_more is True, "a truncated page must say so"
    assert len(result.data.items) == storage._SITES_PAGE_LIMIT


@pytest.mark.asyncio
async def test_list_sites_has_more_is_false_when_everything_fits():
    """The flag must not cry wolf on a normal, complete result."""
    from handlers_read import list_sites

    ctx = MockContext(user_id="u1")
    for i in range(3):
        await ctx.store.create(
            storage.SITES_COLLECTION,
            {"id": f"site-{i}", "name": f"Site {i}", "url": f"https://s{i}.test"},
        )

    result = await list_sites(ctx, None)
    assert result.success
    assert result.data.total == 3
    assert result.data.has_more is False
    assert len(result.data.items) == 3
