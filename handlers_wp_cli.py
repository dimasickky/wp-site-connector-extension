"""wp-site-connector · Generalized WP-CLI plugin/console management.

Second, third, and fourth tools of the WP-CLI roadmap (see
extensions/wp-site-connector.md, 2026-07-18 spec + same-day counter-review):
`manage_plugin` (own explicit confirm-flow), `purge_cache`, and `run_wp_cli`
(namespace-allowlisted raw fallback). All SSH-only — WordPress core has no
REST endpoint for plugin management or WP-CLI passthrough.

Every function here delegates security decisions (namespace allow/blocklist,
subcommand destructive triggers, global-flag stripping) to the pure,
unit-tested `wp_cli_policy` module — nothing here re-implements or bypasses
those checks. Audit logging covers BOTH successful and rejected calls via
`ctx.log`, per the spec requirement that a security-relevant log shouldn't
only record what succeeded.
"""
from imperal_sdk import ActionResult
from app import chat
from models import (ManagePluginParams, PurgeCacheParams, RunWpCliParams,
                    PluginActionResult, CacheActionResult, WpCliResult)
from error_codes import WP_SSH_NOT_CONFIGURED, WP_SSH_COMMAND_FAILED
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD, PERMISSION_DENIED
import storage
import wp_cli
import wp_cli_policy as policy


_MANAGE_PLUGIN_ACTIONS = {"activate", "deactivate", "update"}
# Only 'deactivate' is destructive by default — it can break site functionality
# that depends on the plugin. 'activate'/'update' are still self-confirmed
# (own confirm=True flow) but don't require the same load-bearing warning.
_DESTRUCTIVE_PLUGIN_ACTIONS = {"deactivate"}


async def _require_ssh(ctx, site_id: str):
    """Shared SSH-cred lookup + audit log for a rejected/missing-config call.
    Returns (cred, error_result) — error_result is None when cred is present."""
    cred = await storage.get_ssh_cred(ctx, site_id)
    if not cred:
        await ctx.log(f"wp_cli: rejected — no SSH configured for site_id={site_id}", level="warning")
        return None, ActionResult.error(
            "SSH not configured for this site. Use add_ssh first.", retryable=False,
            code=WP_SSH_NOT_CONFIGURED,
        )
    return cred, None


@chat.function(
    "manage_plugin",
    description=(
        "Activate, deactivate, or update a plugin on a connected WordPress site. "
        "The plugin slug is validated against the site's live plugin list (call "
        "list_plugins first) — never guess a slug. 'deactivate' can break site "
        "functionality that depends on the plugin, so it requires an explicit "
        "confirm=true on a second call; the first call only previews the action."
    ),
    action_type="destructive",
    data_model=PluginActionResult,
    effects=["wp.manage_plugin"],
    event="wp-site-connector.manage_plugin",
)
async def manage_plugin(ctx, params: ManagePluginParams) -> ActionResult:
    """Activate/deactivate/update a plugin via `wp plugin <action> <slug>` over SSH.

    Own explicit two-step confirm-flow for the destructive 'deactivate' action:
    the first call (confirm=false, the default) returns a preview and performs
    no change; the caller must re-call with confirm=true to actually run it.
    This does NOT rely on the platform's confirmation gate (account-level,
    off by default, not controllable by an extension — see wp-site-connector.md).
    """
    action = (params.action or "").strip().lower()
    if action not in _MANAGE_PLUGIN_ACTIONS:
        await ctx.log(f"manage_plugin: rejected — invalid action '{params.action}'", level="warning")
        return ActionResult.error(
            f"Invalid action '{params.action}' — use activate, deactivate, or update.",
            retryable=False, code=VALIDATION_MISSING_FIELD,
        )

    cred, err = await _require_ssh(ctx, params.site_id)
    if err:
        return err

    # Validate the plugin slug against the site's REAL, live plugin list —
    # never trust an LLM-generated slug at face value (this is the "no
    # hardcoding, but exact" requirement from the spec).
    rows, cli_err = await wp_cli.list_plugins_cli(cred)
    if cli_err:
        await ctx.log(f"manage_plugin: rejected — could not verify plugin list: {cli_err}", level="warning")
        return ActionResult.error(cli_err, retryable=True, code=WP_SSH_COMMAND_FAILED)
    known_slugs = {p.get("name", "") for p in rows}
    if params.plugin not in known_slugs:
        await ctx.log(
            f"manage_plugin: rejected — unknown plugin slug '{params.plugin}' for site_id={params.site_id}",
            level="warning",
        )
        return ActionResult.error(
            f"'{params.plugin}' is not installed on this site. Call list_plugins to see what's available.",
            retryable=False, code=VALIDATION_MISSING_FIELD,
        )

    is_destructive = action in _DESTRUCTIVE_PLUGIN_ACTIONS
    if is_destructive and not params.confirm:
        await ctx.log(
            f"manage_plugin: preview only (awaiting confirm) — {action} '{params.plugin}' on site_id={params.site_id}",
            level="info",
        )
        return ActionResult.success(
            PluginActionResult(
                id=params.plugin, title=params.plugin, kind="wp_plugin_action",
                plugin=params.plugin, action=action, needs_confirmation=True,
            ),
            summary=(
                f"This will {action} '{params.plugin}', which may affect site functionality. "
                "Call again with confirm=true to actually run it."
            ),
        )

    out, run_err = await wp_cli.manage_plugin_cli(cred, params.plugin, action)
    if run_err:
        await ctx.log(f"manage_plugin: SSH/WP-CLI error — {action} '{params.plugin}': {run_err}", level="error")
        return ActionResult.error(run_err, retryable=True, code=WP_SSH_COMMAND_FAILED)

    await ctx.log(f"manage_plugin: executed — {action} '{params.plugin}' on site_id={params.site_id}", level="info")
    return ActionResult.success(
        PluginActionResult(
            id=params.plugin, title=params.plugin, kind="wp_plugin_action",
            plugin=params.plugin, action=action, needs_confirmation=False,
            output=(out or "").strip(),
        ),
        summary=f"{action.capitalize()}d '{params.plugin}'.",
    )


@chat.function(
    "purge_cache",
    description=(
        "Purge the site's page cache. Auto-detects an active cache plugin "
        "(currently LiteSpeed Cache via its litespeed-purge WP-CLI namespace) "
        "from the site's real, live plugin list — if none is found, reports "
        "that clearly instead of silently doing nothing."
    ),
    action_type="write",
    data_model=CacheActionResult,
    effects=["wp.purge_cache"],
    event="wp-site-connector.purge_cache",
)
async def purge_cache(ctx, params: PurgeCacheParams) -> ActionResult:
    """Purge the site's cache via `wp litespeed-purge <scope>` over SSH.

    Auto-detects LiteSpeed Cache from the site's live plugin list (list_plugins)
    rather than assuming it's installed — reports clearly when no supported
    cache plugin is active instead of silently doing nothing.
    """
    scope = (params.scope or "all").strip().lower()
    if scope not in ("all", "front"):
        return ActionResult.error(
            f"Invalid scope '{params.scope}' — use 'all' or 'front'.",
            retryable=False, code=VALIDATION_MISSING_FIELD,
        )

    cred, err = await _require_ssh(ctx, params.site_id)
    if err:
        return err

    rows, cli_err = await wp_cli.list_plugins_cli(cred)
    if cli_err:
        await ctx.log(f"purge_cache: rejected — could not read plugin list: {cli_err}", level="warning")
        return ActionResult.error(cli_err, retryable=True, code=WP_SSH_COMMAND_FAILED)

    active_slugs = {p.get("name", "") for p in rows if p.get("status") == "active"}
    if "litespeed-cache" in active_slugs:
        cache_plugin = "litespeed-cache"
        args = [scope] if scope != "all" else []
        out, run_err = await wp_cli.run_wp_cli_cli(cred, "litespeed-purge", args)
    else:
        await ctx.log(
            f"purge_cache: rejected — no known cache plugin active on site_id={params.site_id}",
            level="info",
        )
        return ActionResult.error(
            "No supported cache plugin (LiteSpeed Cache) is active on this site. "
            "Call list_plugins to see what's installed.",
            retryable=False, code=VALIDATION_MISSING_FIELD,
        )

    if run_err:
        await ctx.log(f"purge_cache: SSH/WP-CLI error — {run_err}", level="error")
        return ActionResult.error(run_err, retryable=True, code=WP_SSH_COMMAND_FAILED)

    await ctx.log(f"purge_cache: executed — scope={scope} plugin={cache_plugin} site_id={params.site_id}", level="info")
    return ActionResult.success(
        CacheActionResult(
            id=params.site_id, title=f"{cache_plugin} purge", kind="wp_cache_action",
            scope=scope, cache_plugin=cache_plugin, output=(out or "").strip(),
        ),
        summary=f"Purged {cache_plugin} cache ({scope}).",
    )


@chat.function(
    "run_wp_cli",
    description=(
        "Run a WP-CLI command in a namespace not covered by the dedicated tools "
        "(manage_plugin, purge_cache) — e.g. WooCommerce (wc), a theme, transients, "
        "cron. namespace must be on the server-side allowlist; dangerous namespaces "
        "(eval, db, config, shell) are always rejected. Destructive subcommands "
        "(delete/remove/set-role/etc.) require an explicit confirm=true on a second "
        "call — the first call only previews what would run."
    ),
    action_type="write",
    data_model=WpCliResult,
    effects=["wp.run_wp_cli"],
    event="wp-site-connector.run_wp_cli",
)
async def run_wp_cli(ctx, params: RunWpCliParams) -> ActionResult:
    """Generalized, namespace-allowlisted WP-CLI executor — the last-resort
    fallback for WP-CLI operations not covered by manage_plugin/purge_cache
    (e.g. WooCommerce `wp wc`, ACF, Yoast, or any other plugin's own namespace).

    Three independent security layers (all in wp_cli_policy.py, see that module
    and wp-site-connector.md for the full rationale) run before anything is
    executed: namespace allow/blocklist, subcommand-level destructive triggers
    (independent of namespace — e.g. `user set-role` is destructive even though
    'user' is allowlisted), and global WP-CLI/SSH flag stripping. Own explicit
    confirm=true flow for write/destructive calls — same reasoning as
    manage_plugin, not the platform's (off-by-default) confirmation gate.
    """
    namespace, ns_err = policy.classify_namespace(params.namespace)
    if ns_err:
        await ctx.log(
            f"run_wp_cli: rejected — namespace '{params.namespace}' — {ns_err}", level="warning",
        )
        return ActionResult.error(ns_err, retryable=False, code=PERMISSION_DENIED)

    clean_args, stripped = policy.strip_global_flags(params.args or [])
    if stripped:
        await ctx.log(
            f"run_wp_cli: stripped global flag(s) {stripped} from namespace='{namespace}' "
            f"site_id={params.site_id} — never forwarded to the shell",
            level="warning",
        )

    if namespace == "core":
        core_err = policy.validate_core_subcommand(clean_args)
        if core_err:
            await ctx.log(f"run_wp_cli: rejected — {core_err}", level="warning")
            return ActionResult.error(core_err, retryable=False, code=PERMISSION_DENIED)

    cred, err = await _require_ssh(ctx, params.site_id)
    if err:
        return err

    destructive = policy.is_destructive_call(namespace, clean_args)
    classification = "destructive" if destructive else "write"
    if destructive and not params.confirm:
        await ctx.log(
            f"run_wp_cli: preview only (awaiting confirm) — namespace='{namespace}' args={clean_args} "
            f"site_id={params.site_id}",
            level="info",
        )
        return ActionResult.success(
            WpCliResult(
                id=namespace, title=f"wp {namespace}", kind="wp_cli_call",
                namespace=namespace, classification=classification, needs_confirmation=True,
            ),
            summary=(
                f"'wp {namespace} {' '.join(clean_args)}' is classified destructive. "
                "Call again with confirm=true to actually run it."
            ),
        )

    out, run_err = await wp_cli.run_wp_cli_cli(cred, namespace, clean_args)
    if run_err:
        await ctx.log(
            f"run_wp_cli: SSH/WP-CLI error — namespace='{namespace}' args={clean_args}: {run_err}",
            level="error",
        )
        return ActionResult.error(run_err, retryable=True, code=WP_SSH_COMMAND_FAILED)

    await ctx.log(
        f"run_wp_cli: executed — namespace='{namespace}' args={clean_args} "
        f"classification={classification} site_id={params.site_id}",
        level="info",
    )
    return ActionResult.success(
        WpCliResult(
            id=namespace, title=f"wp {namespace}", kind="wp_cli_call",
            namespace=namespace, classification=classification, needs_confirmation=False,
            output=(out or "").strip(),
        ),
        summary=f"Ran 'wp {namespace} {' '.join(clean_args)}'.",
    )
