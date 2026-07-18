"""Security policy for the generalized WP-CLI executor (`run_wp_cli`).

Pure, side-effect-free functions — no SSH, no I/O — so the security-critical
logic here can be unit-tested in complete isolation from the transport layer.
See `extensions/wp-site-connector.md` (2026-07-18 spec + same-day counter-review)
for the full design rationale. Every rule below traces back to a specific
finding in that doc; don't loosen any of them without updating the doc too.

Three independent layers, all must pass before a command is built:
1. Namespace allowlist/blocklist (`classify_namespace`).
2. Subcommand-level destructive trigger — INDEPENDENT of namespace, because
   `user set-role`, `post delete --force`, `theme delete` etc. are just as
   dangerous as anything in `plugin`, but a namespace-only allowlist would
   have let them through as merely "write" (`is_destructive_call`).
3. Global WP-CLI/SSH flag stripping — `--path=`, `--url=`, `--ssh=`,
   `--allow-root` (we set our own), `--skip-plugins`, `--skip-themes`,
   `--skip-packages` must never come from user-supplied args, or a
   shared-hosting caller could redirect the command at a sibling site on
   the same filesystem (`strip_global_flags`).
"""
import shlex

# ── Namespace allowlist ──────────────────────────────────────────────────── #
# Only these namespaces may be used with run_wp_cli. Anything else — including
# any namespace not listed here, even if it sounds harmless — is rejected.
# Third-party plugin namespaces (e.g. `litespeed-purge`) are allowed generically
# via ALLOWED_NAMESPACES since the whole point is "no hardcoding per plugin";
# operators can extend this set for other known-safe plugin namespaces.
ALLOWED_NAMESPACES = frozenset({
    "plugin", "theme", "cache", "litespeed-purge", "transient", "cron",
    "media", "user", "post", "core",
})

# Always rejected, no exceptions — direct code/SQL execution or secret exposure.
BLOCKED_NAMESPACES = frozenset({
    "eval", "eval-file", "db", "shell", "config", "option", "package",
    "cli", "scaffold", "i18n", "profile",
})

# `core` is allowed only for these read/info subcommands — `core update` /
# `core update-db` are real-world-breaking and out of scope for v1 (see spec).
_CORE_ALLOWED_SUBCOMMANDS = frozenset({"check-update", "version"})

# Subcommands that force action_type="destructive" regardless of which
# allowed namespace they appear under — the subcommand itself is the risk,
# not just the namespace. Matched as the first positional arg after
# namespace, case-insensitive.
_DESTRUCTIVE_SUBCOMMANDS = frozenset({
    "delete", "remove", "uninstall", "drop", "reset", "empty", "trash",
    "set-role",
})

# Field names that make a "meta update"/"update" call destructive even when
# the subcommand itself is otherwise plain (e.g. `wp user meta update <id>
# wp_capabilities ...` is a privilege-escalation vector dressed up as a
# metadata write).
_DESTRUCTIVE_META_FIELDS = frozenset({
    "wp_capabilities", "capabilities", "role", "roles",
})

# Global WP-CLI / SSH flags that must NEVER be accepted from user-supplied
# args — they either bypass the pinned site (--path=, --url=, --ssh=), touch
# unrelated environment behavior (--skip-plugins/--skip-themes/--skip-packages),
# or would conflict with the value we set ourselves (--allow-root).
_GLOBAL_FLAG_PREFIXES = (
    "--path", "--url", "--ssh", "--allow-root", "--skip-plugins",
    "--skip-themes", "--skip-packages", "--http", "--user=",
)


def classify_namespace(namespace: str) -> tuple[str | None, str | None]:
    """Normalize + validate a namespace against the allow/blocklist.

    Returns (normalized_namespace, None) if allowed, or (None, error_message)
    if rejected. Normalization (lowercase + strip) happens BEFORE the compare
    so `" Plugin "` / `"PLUGIN"` can't slip past a case-sensitive check.
    """
    normalized = (namespace or "").strip().lower()
    if not normalized:
        return None, "WP-CLI namespace is required."
    if normalized in BLOCKED_NAMESPACES:
        return None, (
            f"WP-CLI namespace '{normalized}' is not allowed — it can execute "
            "arbitrary code, run raw SQL, or expose site secrets."
        )
    if normalized not in ALLOWED_NAMESPACES:
        return None, (
            f"WP-CLI namespace '{normalized}' is not on the allowlist. "
            f"Allowed: {', '.join(sorted(ALLOWED_NAMESPACES))}."
        )
    return normalized, None


def strip_global_flags(args: list[str]) -> tuple[list[str], list[str]]:
    """Remove global WP-CLI/SSH flags from user-supplied args before the
    command is assembled. Returns (clean_args, stripped_flags) — callers
    should log `stripped_flags` to the audit trail even on an otherwise
    successful call, since their presence alone is a signal worth recording.
    """
    clean: list[str] = []
    stripped: list[str] = []
    for arg in args:
        lowered = arg.strip().lower()
        if any(lowered == p or lowered.startswith(p + "=") for p in _GLOBAL_FLAG_PREFIXES):
            stripped.append(arg)
            continue
        clean.append(arg)
    return clean, stripped


def is_destructive_call(namespace: str, args: list[str]) -> bool:
    """True if this specific (namespace, args) call must be treated as
    destructive, independent of the namespace's own default classification.

    Two triggers:
    - First positional arg (the subcommand) is in _DESTRUCTIVE_SUBCOMMANDS.
    - It's a `meta update`/`meta set`/`meta add` call whose meta key is a
      capability/role field (privilege escalation dressed as a metadata op).
    """
    positional = [a for a in args if not a.startswith("-")]
    if not positional:
        return False
    subcommand = positional[0].strip().lower()
    if subcommand in _DESTRUCTIVE_SUBCOMMANDS:
        return True
    if subcommand == "meta" and len(positional) >= 4:
        # Shape: meta <verb> <object_id> <meta_key> [<meta_value>]
        meta_verb = positional[1].strip().lower()
        meta_key = positional[3].strip().lower()
        if meta_verb in ("update", "set", "add") and meta_key in _DESTRUCTIVE_META_FIELDS:
            return True
    return False


def validate_core_subcommand(args: list[str]) -> str | None:
    """`core` namespace is restricted to read/info subcommands only (see spec:
    `core update` is out of scope for v1, real-world-breaking). Returns an
    error message if the subcommand isn't in the mini-allowlist, else None.
    """
    positional = [a for a in args if not a.startswith("-")]
    subcommand = positional[0].strip().lower() if positional else ""
    if subcommand not in _CORE_ALLOWED_SUBCOMMANDS:
        return (
            f"'core {subcommand or '<missing>'}' is not allowed — only "
            f"{', '.join(sorted(_CORE_ALLOWED_SUBCOMMANDS))} are permitted "
            "under the 'core' namespace."
        )
    return None


def build_wp_cli_command(wp_path: str, namespace: str, args: list[str]) -> str:
    """Assemble the final shell command string. Every arg is individually
    shlex-quoted (never joined into one f-string of raw user text) — same
    pattern already used for post content in `update_post_cli`/
    `set_rank_math_meta_cli`. Caller is responsible for having already run
    strip_global_flags() on `args`.
    """
    quoted_args = " ".join(shlex.quote(a) for a in args)
    return f"wp {namespace} {quoted_args} --path={wp_path} --allow-root".strip()
