"""Unit tests for wp_cli_policy — pure security-logic functions, no SSH/I/O.

Every test here traces to a specific requirement in extensions/wp-site-connector.md
(the 2026-07-18 spec + same-day counter-review). Keep that traceability when
adding cases — this is the load-bearing security surface for run_wp_cli.
"""
import wp_cli_policy as policy


# ── classify_namespace ───────────────────────────────────────────────────── #

def test_classify_namespace_allows_known_namespace():
    ns, err = policy.classify_namespace("plugin")
    assert ns == "plugin"
    assert err is None


def test_classify_namespace_normalizes_case_and_whitespace():
    ns, err = policy.classify_namespace("  PLUGIN  ")
    assert ns == "plugin"
    assert err is None


def test_classify_namespace_rejects_blocked_eval():
    ns, err = policy.classify_namespace("eval")
    assert ns is None
    assert "not allowed" in err


def test_classify_namespace_rejects_blocked_db():
    ns, err = policy.classify_namespace("db")
    assert ns is None
    assert err


def test_classify_namespace_rejects_blocked_config():
    ns, err = policy.classify_namespace("config")
    assert ns is None
    assert err


def test_classify_namespace_rejects_unknown_namespace_not_just_blocklist():
    """Anything not explicitly allowlisted is rejected too — not just the
    hardcoded blocklist. A brand-new/unknown namespace must fail closed."""
    ns, err = policy.classify_namespace("some-random-namespace")
    assert ns is None
    assert "allowlist" in err


def test_classify_namespace_case_insensitive_blocklist_bypass_blocked():
    """A naive case-sensitive blocklist check could be bypassed by 'Eval' or
    'EVAL' — must normalize BEFORE the compare."""
    ns, err = policy.classify_namespace("EVAL")
    assert ns is None
    assert "not allowed" in err


def test_classify_namespace_rejects_empty():
    ns, err = policy.classify_namespace("")
    assert ns is None
    assert "required" in err


# ── strip_global_flags ───────────────────────────────────────────────────── #

def test_strip_global_flags_removes_path_override():
    clean, stripped = policy.strip_global_flags(["update", "--path=/var/www/other-site"])
    assert clean == ["update"]
    assert stripped == ["--path=/var/www/other-site"]


def test_strip_global_flags_removes_ssh_override():
    clean, stripped = policy.strip_global_flags(["list", "--ssh=other-host"])
    assert clean == ["list"]
    assert "--ssh=other-host" in stripped


def test_strip_global_flags_removes_url_override():
    clean, stripped = policy.strip_global_flags(["list", "--url=https://evil.example"])
    assert clean == ["list"]
    assert stripped


def test_strip_global_flags_removes_skip_plugins():
    clean, stripped = policy.strip_global_flags(["list", "--skip-plugins"])
    assert clean == ["list"]
    assert stripped == ["--skip-plugins"]


def test_strip_global_flags_removes_allow_root_override():
    """We set --allow-root ourselves at command-assembly time — a user-supplied
    one (possibly with a different value or just a dupe) must still be stripped."""
    clean, stripped = policy.strip_global_flags(["list", "--allow-root"])
    assert clean == ["list"]
    assert stripped == ["--allow-root"]


def test_strip_global_flags_case_insensitive():
    clean, stripped = policy.strip_global_flags(["list", "--PATH=/tmp/x"])
    assert clean == ["list"]
    assert stripped


def test_strip_global_flags_preserves_safe_args():
    clean, stripped = policy.strip_global_flags(["update", "akismet", "--minor"])
    assert clean == ["update", "akismet", "--minor"]
    assert stripped == []


# ── is_destructive_call — subcommand triggers independent of namespace ──── #

def test_destructive_delete_subcommand():
    assert policy.is_destructive_call("plugin", ["delete", "akismet"]) is True


def test_destructive_user_set_role_privilege_escalation():
    """wp user set-role <id> administrator — privilege escalation, must be
    destructive even though 'user' namespace default might otherwise be write."""
    assert policy.is_destructive_call("user", ["set-role", "5", "administrator"]) is True


def test_destructive_post_delete_force():
    assert policy.is_destructive_call("post", ["delete", "42", "--force"]) is True


def test_destructive_theme_delete():
    assert policy.is_destructive_call("theme", ["delete", "twentyfifteen"]) is True


def test_destructive_meta_update_capabilities_field():
    """wp user meta update <id> wp_capabilities ... — capability grant hidden
    behind a generic 'meta update' verb, must still trip destructive."""
    assert policy.is_destructive_call("user", ["meta", "update", "5", "wp_capabilities", "a:1:{...}"]) is True


def test_destructive_meta_update_role_field():
    assert policy.is_destructive_call("user", ["meta", "update", "5", "role", "administrator"]) is True


def test_non_destructive_plain_meta_update():
    """A meta update on an unrelated field (e.g. nickname) is NOT destructive —
    only capability/role fields trigger it."""
    assert policy.is_destructive_call("user", ["meta", "update", "5", "nickname", "Bob"]) is False


def test_non_destructive_plugin_activate():
    assert policy.is_destructive_call("plugin", ["activate", "akismet"]) is False


def test_non_destructive_plugin_update():
    assert policy.is_destructive_call("plugin", ["update", "akismet"]) is False


def test_destructive_call_empty_args_is_false():
    assert policy.is_destructive_call("plugin", []) is False


def test_destructive_call_only_flags_no_positional_is_false():
    assert policy.is_destructive_call("plugin", ["--all"]) is False


# ── validate_core_subcommand — core namespace restricted to read/info ──── #

def test_core_allows_check_update():
    assert policy.validate_core_subcommand(["check-update"]) is None


def test_core_allows_version():
    assert policy.validate_core_subcommand(["version"]) is None


def test_core_rejects_update():
    err = policy.validate_core_subcommand(["update"])
    assert err is not None
    assert "not allowed" in err


def test_core_rejects_missing_subcommand():
    err = policy.validate_core_subcommand([])
    assert err is not None


# ── build_wp_cli_command — every arg individually shlex-quoted ─────────── #

def test_build_command_quotes_args_individually():
    cmd = policy.build_wp_cli_command("/var/www/html", "plugin", ["update", "akismet"])
    assert cmd == "wp plugin update akismet --path=/var/www/html --allow-root"


def test_build_command_quotes_special_characters():
    cmd = policy.build_wp_cli_command("/var/www/html", "post", ["delete", "1; rm -rf /"])
    # The dangerous string must come out as a single shell-quoted token, not
    # split into separate shell-interpreted commands.
    assert "'1; rm -rf /'" in cmd or '"1; rm -rf /"' in cmd
    assert cmd.count(";") == 1  # the ; only exists inside the quoted literal
