"""Unit tests for the WP-CLI publish/read helpers (create_post_cli, update_post_cli,
list_posts_cli, upload_media_cli) — verifying command construction is injection-safe
(shlex.quote on every interpolated field, content always via STDIN never via argv)."""
import wp_cli


async def _capture_run(monkeypatch, fake_output="42", fake_err=None):
    """Patch wp_cli._run to capture (host, port, user, key_path, remote_cmd, stdin_data)."""
    captured = {}

    async def _fake_run(host, port, user, key_path, remote_cmd, known_hosts_path=None,
                        password=None, askpass_path=None, timeout=None, stdin_data=None):
        captured["remote_cmd"] = remote_cmd
        captured["stdin_data"] = stdin_data
        captured["host"] = host
        if fake_err:
            return None, fake_err
        return fake_output, None

    monkeypatch.setattr(wp_cli, "_run", _fake_run)
    return captured


_CRED = {"host": "1.2.3.4", "port": 22, "user": "root", "wp_path": "/var/www/html",
        "password": "pw", "host_key": "1.2.3.4 ssh-ed25519 AAAA"}


async def test_create_post_cli_puts_content_on_stdin_not_in_command(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="7")
    post, err = await wp_cli.create_post_cli(
        _CRED, title="Hello; rm -rf /", content="body text with `backticks` and $(danger)",
        status="draft")
    assert err is None
    assert post["id"] == "7"
    # The dangerous content never appears in the command string — it went over STDIN.
    assert "backticks" not in captured["remote_cmd"]
    assert "$(danger)" not in captured["remote_cmd"]
    assert captured["stdin_data"] == "body text with `backticks` and $(danger)"
    # The title WAS shell-quoted, so a shell metacharacter inside it is neutralised.
    assert "wp post create -" in captured["remote_cmd"]


async def test_create_post_cli_quotes_title_with_shell_metacharacters(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="7")
    await wp_cli.create_post_cli(_CRED, title="a'; echo pwned; '", content="", status="draft")
    # shlex.quote wraps in single quotes and escapes any embedded single quote —
    # the raw unescaped title must never appear verbatim in the command.
    assert "a'; echo pwned; '" not in captured["remote_cmd"]


async def test_create_post_cli_rejects_non_numeric_output(monkeypatch):
    await _capture_run(monkeypatch, fake_output="not-a-number")
    post, err = await wp_cli.create_post_cli(_CRED, title="Hi", content="Body", status="draft")
    assert post is None
    assert "Unexpected" in err


async def test_create_post_cli_requires_key_or_password():
    post, err = await wp_cli.create_post_cli(
        {"host": "1.2.3.4", "port": 22, "user": "root", "wp_path": "/var/www/html"},
        title="Hi", content="Body", status="draft")
    assert post is None
    assert "SSH private key or SSH password" in err


async def test_update_post_cli_quotes_post_id_and_uses_stdin_for_content(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="ok")
    post, err = await wp_cli.update_post_cli(
        _CRED, post_id="7", title="New; title", content="new $(content)", status=None)
    assert err is None
    assert captured["stdin_data"] == "new $(content)"
    assert "$(content)" not in captured["remote_cmd"]


async def test_create_post_cli_slug_becomes_post_name_flag(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="7")
    await wp_cli.create_post_cli(_CRED, title="InfinityFree Review 2026", content="Body",
                                 status="publish", slug="infinityfree-review-2026")
    assert "--post_name=infinityfree-review-2026" in captured["remote_cmd"]


async def test_create_post_cli_omits_post_name_flag_when_no_slug(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="7")
    await wp_cli.create_post_cli(_CRED, title="Hi", content="Body", status="draft")
    assert "--post_name" not in captured["remote_cmd"]


async def test_update_post_cli_slug_becomes_post_name_flag_and_is_quoted(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="ok")
    await wp_cli.update_post_cli(_CRED, post_id="7", title=None, content=None, status=None,
                                 slug="new'; rm -rf /; 'slug")
    assert "new'; rm -rf /; 'slug" not in captured["remote_cmd"]
    assert "--post_name=" in captured["remote_cmd"]


async def test_update_post_cli_rejects_non_numeric_post_id():
    post, err = await wp_cli.update_post_cli(_CRED, post_id="abc; rm -rf /", title="x",
                                             content=None, status=None)
    assert post is None
    assert "numeric" in err


async def test_update_post_cli_no_stdin_when_content_not_given(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="ok")
    await wp_cli.update_post_cli(_CRED, post_id="7", title="New", content=None, status=None)
    assert captured["stdin_data"] is None
    assert " - " not in captured["remote_cmd"].replace("post_title", "")


async def test_list_posts_cli_quotes_search_term(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="[]")
    posts, err = await wp_cli.list_posts_cli(_CRED, limit=10, search="foo'; rm -rf /; '")
    assert err is None
    assert posts == []
    assert "foo'; rm -rf /; '" not in captured["remote_cmd"]


async def test_list_posts_cli_parses_json_output(monkeypatch):
    await _capture_run(monkeypatch, fake_output='[{"ID": "1", "post_title": "Hi"}]')
    posts, err = await wp_cli.list_posts_cli(_CRED)
    assert err is None
    assert posts[0]["post_title"] == "Hi"


async def test_upload_media_cli_pipes_b64_over_stdin(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="99")
    media, err = await wp_cli.upload_media_cli(_CRED, b64_data="ZmFrZS1kYXRh",
                                               filename="photo.jpg", title="A photo")
    assert err is None
    assert media["id"] == "99"


# ── Read-side WP-CLI helpers (list_content_cli, list_comments_cli, list_users_cli,
# list_orders_cli, count_posts_cli) — the functions that make SSH-only sites
# actually READABLE, not just writable. ──────────────────────────────────────

async def test_list_content_cli_quotes_search_and_sets_post_type(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="[]")
    posts, err = await wp_cli.list_content_cli(_CRED, post_type="page", limit=5,
                                               search="foo'; rm -rf /; '")
    assert err is None
    assert posts == []
    assert "--post_type=page" in captured["remote_cmd"]
    assert "foo'; rm -rf /; '" not in captured["remote_cmd"]


async def test_list_content_cli_parses_json_and_applies_status_orderby(monkeypatch):
    captured = await _capture_run(monkeypatch,
                                  fake_output='[{"ID": "5", "post_title": "Future"}]')
    posts, err = await wp_cli.list_content_cli(_CRED, post_type="post", status="future",
                                               orderby="date", order="asc")
    assert err is None
    assert posts[0]["post_title"] == "Future"
    assert "--post_status=future" in captured["remote_cmd"]
    assert "--orderby=date" in captured["remote_cmd"]
    assert "--order=asc" in captured["remote_cmd"]


async def test_list_comments_cli_maps_rest_status_and_quotes(monkeypatch):
    captured = await _capture_run(monkeypatch,
                                  fake_output='[{"comment_ID": "1", "comment_author": "Bob"}]')
    comments, err = await wp_cli.list_comments_cli(_CRED, status="approve", limit=10)
    assert err is None
    assert comments[0]["comment_ID"] == "1"
    assert "--status=approve" in captured["remote_cmd"]


async def test_list_comments_cli_all_status_omits_status_flag(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="[]")
    await wp_cli.list_comments_cli(_CRED, status="all")
    assert "--status=" not in captured["remote_cmd"]


async def test_list_users_cli_quotes_search_term(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="[]")
    users, err = await wp_cli.list_users_cli(_CRED, search="jane'; rm -rf /; '")
    assert err is None
    assert "jane'; rm -rf /; '" not in captured["remote_cmd"]


async def test_list_users_cli_parses_json(monkeypatch):
    await _capture_run(monkeypatch, fake_output='[{"ID": "2", "display_name": "Jane"}]')
    users, err = await wp_cli.list_users_cli(_CRED)
    assert err is None
    assert users[0]["display_name"] == "Jane"


async def test_list_orders_cli_parses_json(monkeypatch):
    await _capture_run(monkeypatch, fake_output='[{"id": "7", "total": "9.99"}]')
    orders, err = await wp_cli.list_orders_cli(_CRED)
    assert err is None
    assert orders[0]["total"] == "9.99"


async def test_list_orders_cli_reports_woocommerce_not_installed(monkeypatch):
    captured = await _capture_run(
        monkeypatch, fake_err="Error: 'wc' is not a registered wp command. See 'wp help'.")
    orders, err = await wp_cli.list_orders_cli(_CRED)
    assert orders is None
    assert "WooCommerce is not installed" in err


async def test_count_posts_cli_parses_integer(monkeypatch):
    await _capture_run(monkeypatch, fake_output="42")
    n, err = await wp_cli.count_posts_cli(_CRED, "page")
    assert err is None
    assert n == 42


async def test_count_posts_cli_rejects_non_numeric_output(monkeypatch):
    await _capture_run(monkeypatch, fake_output="not a number")
    n, err = await wp_cli.count_posts_cli(_CRED)
    assert n is None
    assert "Unexpected" in err


async def test_upload_media_cli_rejects_unsafe_extension_falls_back(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="99")
    await wp_cli.upload_media_cli(_CRED, b64_data="ZGF0YQ==", filename="evil.php", title="")
    # .php must never become the mktemp suffix — falls back to a safe generic one.
    assert ".php" not in captured["remote_cmd"]
    assert ".img" in captured["remote_cmd"]


async def test_upload_media_cli_rejects_non_numeric_output(monkeypatch):
    await _capture_run(monkeypatch, fake_output="Error: something went wrong")
    media, err = await wp_cli.upload_media_cli(_CRED, b64_data="ZGF0YQ==", filename="x.jpg")
    assert media is None
    assert "Unexpected" in err


# ── Rank Math SEO meta (wp post meta update) ───────────────────────────────────

async def test_set_post_meta_cli_uses_meta_update_command_and_stdin(monkeypatch):
    captured = await _capture_run(monkeypatch, fake_output="Success: Updated custom field.")
    ok, err = await wp_cli.set_post_meta_cli(_CRED, post_id="7", meta_key="rank_math_description",
                                             meta_value="A great review with `backticks` and $(danger)")
    assert err is None
    assert ok is True
    assert "wp post meta update" in captured["remote_cmd"]
    assert "rank_math_description" in captured["remote_cmd"]
    # Value never touches argv — it goes over STDIN, so shell metacharacters can't matter.
    assert "backticks" not in captured["remote_cmd"]
    assert "$(danger)" not in captured["remote_cmd"]
    assert captured["stdin_data"] == "A great review with `backticks` and $(danger)"


async def test_set_post_meta_cli_rejects_non_numeric_post_id():
    ok, err = await wp_cli.set_post_meta_cli(_CRED, post_id="abc; rm -rf /",
                                             meta_key="rank_math_description", meta_value="x")
    assert ok is False
    assert "numeric" in err


async def test_set_post_meta_cli_surfaces_ssh_failure(monkeypatch):
    await _capture_run(monkeypatch, fake_err="Connection refused")
    ok, err = await wp_cli.set_post_meta_cli(_CRED, post_id="7", meta_key="rank_math_description",
                                             meta_value="x")
    assert ok is False
    assert err == "Connection refused"


async def test_set_rank_math_meta_cli_writes_both_fields(monkeypatch):
    calls = []

    async def _fake_set_meta(cred, post_id, meta_key, meta_value):
        calls.append((post_id, meta_key, meta_value))
        return True, None

    monkeypatch.setattr(wp_cli, "set_post_meta_cli", _fake_set_meta)
    errs = await wp_cli.set_rank_math_meta_cli(_CRED, post_id="7", description="desc here",
                                               focus_keyword="my keyword")
    assert errs == []
    assert ("7", "rank_math_description", "desc here") in calls
    assert ("7", "rank_math_focus_keyword", "my keyword") in calls


async def test_set_rank_math_meta_cli_only_writes_given_fields(monkeypatch):
    calls = []

    async def _fake_set_meta(cred, post_id, meta_key, meta_value):
        calls.append(meta_key)
        return True, None

    monkeypatch.setattr(wp_cli, "set_post_meta_cli", _fake_set_meta)
    await wp_cli.set_rank_math_meta_cli(_CRED, post_id="7", description="only description")
    assert calls == ["rank_math_description"]


async def test_set_rank_math_meta_cli_collects_errors_per_field(monkeypatch):
    async def _fake_set_meta(cred, post_id, meta_key, meta_value):
        return False, f"failed for {meta_key}"

    monkeypatch.setattr(wp_cli, "set_post_meta_cli", _fake_set_meta)
    errs = await wp_cli.set_rank_math_meta_cli(_CRED, post_id="7", description="d",
                                               focus_keyword="k")
    assert len(errs) == 2
