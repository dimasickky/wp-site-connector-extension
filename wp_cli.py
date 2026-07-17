"""SSH + WP-CLI executor using the system ssh binary.

Uses asyncio.create_subprocess_exec to run ssh without any third-party
SSH library — works in any environment that has the ssh binary available.
Private key is written to a temporary file (chmod 600) and deleted immediately
after the connection is established.
"""
import asyncio
import json
import os
import shlex
import stat
import tempfile
import contextlib

_CMD_TIMEOUT = 30  # seconds per command


@contextlib.asynccontextmanager
async def _key_file(key_content: str):
    """Write a private key to a secure temp file; delete on exit."""
    if not key_content:
        yield None
        return
    fd, path = tempfile.mkstemp(suffix=".key")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(key_content)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 600 — ssh refuses world-readable keys
        yield path
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


_KEYSCAN_TIMEOUT = 10  # seconds


async def scan_host_key(host: str, port: int) -> tuple[str | None, str | None]:
    """Fetch the server's SSH host public key via ssh-keyscan (first-connect only).

    Returns (host_key_line, error). The returned line is the raw
    known_hosts-format entry ("host key-type key-base64") to be pinned and
    reused on every subsequent connection (TOFU — trust on first use).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh-keyscan", "-p", str(port), "-T", str(_KEYSCAN_TIMEOUT), host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return None, "ssh-keyscan binary not found — the server environment does not have it installed"
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_KEYSCAN_TIMEOUT + 5)
    except asyncio.TimeoutError:
        proc.kill()
        return None, "Host key scan timed out"
    lines = [l for l in stdout.decode().splitlines() if l.strip() and not l.startswith("#")]
    if not lines:
        return None, (stderr.decode().strip()[:300] or "Could not retrieve the server's SSH host key")
    # Prefer an ed25519 entry if present (most common modern default), else first line.
    for line in lines:
        if " ssh-ed25519 " in line:
            return line.strip(), None
    return lines[0].strip(), None


@contextlib.asynccontextmanager
async def _known_hosts_file(host_key_line: str | None):
    """Write a pinned known_hosts file with exactly one trusted host key."""
    if not host_key_line:
        yield None
        return
    fd, path = tempfile.mkstemp(suffix=".known_hosts")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(host_key_line + "\n")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        yield path
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


@contextlib.asynccontextmanager
async def _askpass_file(enabled: bool):
    """Create a password-free SSH_ASKPASS helper for non-interactive auth.

    The helper contains no credential; it prints a value inherited only by
    the child ssh process through ``IMPERAL_SSH_PASSWORD``.
    """
    if not enabled:
        yield None
        return
    fd, path = tempfile.mkstemp(suffix=".askpass")
    try:
        with os.fdopen(fd, "w") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "$IMPERAL_SSH_PASSWORD"\n')
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        yield path
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def _ssh_cmd(host: str, port: int, user: str, key_path: str | None, remote_cmd: str,
            known_hosts_path: str | None = None, password_auth: bool = False) -> list[str]:
    batch_mode = "no" if password_auth else "yes"
    cmd = ["ssh", "-p", str(port), "-o", "ConnectTimeout=15", "-o", f"BatchMode={batch_mode}"]
    if known_hosts_path:
        # Host key was pinned on first connect (TOFU) — verify strictly against it.
        cmd += ["-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_hosts_path}"]
    else:
        # No pinned key available (legacy credential predating host-key pinning).
        # Accept-new keeps us safe against a *changed* key while allowing first
        # contact — strictly better than disabling checking outright.
        cmd += ["-o", "StrictHostKeyChecking=accept-new", "-o", "UserKnownHostsFile=/dev/null"]
    if key_path:
        cmd += ["-i", key_path]
    if password_auth:
        cmd += ["-o", "PreferredAuthentications=password,keyboard-interactive",
                "-o", "PubkeyAuthentication=no"]
    cmd += [f"{user}@{host}", remote_cmd]
    return cmd


async def _run(host, port, user, key_path, remote_cmd, known_hosts_path=None,
               password: str | None = None, askpass_path: str | None = None,
               timeout=_CMD_TIMEOUT, stdin_data: str | None = None) -> tuple[str | None, str | None]:
    """Run one remote command. Returns (stdout, error_message).

    stdin_data, when given, is piped to the remote command's STDIN (e.g. for
    `wp post create -` / `wp post update <id> -`, which read post content
    from STDIN rather than a command-line argument — safer for large or
    special-character-heavy content than any amount of shell-escaping).
    """
    env = None
    if password:
        env = os.environ.copy()
        env.update({
            "SSH_ASKPASS": askpass_path or "",
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": env.get("DISPLAY") or ":0",
            "IMPERAL_SSH_PASSWORD": password,
        })
    try:
        proc = await asyncio.create_subprocess_exec(
            *_ssh_cmd(host, port, user, key_path, remote_cmd, known_hosts_path,
                      password_auth=bool(password)),
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        return None, "ssh binary not found — the server environment does not have ssh installed"
    except Exception as e:
        return None, f"subprocess error: {e}"
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_data.encode() if stdin_data is not None else None),
            timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return None, "Command timed out"
    if proc.returncode == 0:
        return stdout.decode().strip(), None
    err_text = stderr.decode().strip()
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in err_text.upper():
        return None, ("SSH host key changed since it was first pinned — this can mean the server was "
                      "rebuilt, or it can indicate a man-in-the-middle attack. Verify out-of-band, then "
                      "remove and re-add SSH to re-pin the new key.")
    return None, err_text[:300]


async def test_connection(cred: dict) -> tuple[bool, str, str | None]:
    """Test SSH + WP-CLI. Returns (ok, message, host_key_line).

    On first connect (cred has no pinned host_key yet) this scans and pins
    the server's host key (TOFU), then verifies strictly against it in the
    same call — never connects with checking disabled.
    """
    key = cred.get("key")
    password = cred.get("password")
    if not key and not password:
        return False, "Provide either an SSH private key or SSH password.", None

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = shlex.quote(cred.get("wp_path", "/var/www/html"))

    host_key = cred.get("host_key")
    if not host_key:
        host_key, scan_err = await scan_host_key(host, port)
        if not host_key:
            return False, f"Could not verify server identity: {scan_err}", None

    async with (_key_file(key) as kf,
                _known_hosts_file(host_key) as khf,
                _askpass_file(bool(password)) as askpass):
        out, err = await _run(host, port, user, kf,
                              f"wp core version --path={wp_path} --allow-root",
                              known_hosts_path=khf, password=password,
                              askpass_path=askpass)
    if out is None:
        return False, err or "SSH connection failed", None
    return True, f"WordPress {out}", host_key


async def get_site_url(cred: dict) -> tuple[str | None, str | None]:
    """Fetch the WordPress siteurl via WP-CLI over SSH (no REST/Application

    Password needed). Used to validate + name an SSH-only connected site,
    the same way connect_site validates over REST via /users/me.
    Returns (site_url, error_message).
    """
    key = cred.get("key")
    password = cred.get("password")
    if not key and not password:
        return None, "Provide either an SSH private key or SSH password."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = shlex.quote(cred.get("wp_path", "/var/www/html"))
    host_key = cred.get("host_key")

    async with (_key_file(key) as kf,
                _known_hosts_file(host_key) as khf,
                _askpass_file(bool(password)) as askpass):
        out, err = await _run(host, port, user, kf,
                              f"wp option get siteurl --path={wp_path} --allow-root",
                              known_hosts_path=khf, password=password,
                              askpass_path=askpass)
    if out is None:
        return None, err or "SSH connection failed"
    return out.strip(), None


async def get_server_info(cred: dict) -> dict:
    """Run WP-CLI diagnostic commands and return results."""
    key = cred.get("key")
    password = cred.get("password")
    if not key and not password:
        return {"error": "SSH private key or password is required."}

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = shlex.quote(cred.get("wp_path", "/var/www/html"))
    host_key = cred.get("host_key")  # None for legacy creds predating host-key pinning

    commands = [
        f"wp core version --path={wp_path} --allow-root",
        f"wp eval 'echo PHP_VERSION;' --path={wp_path} --allow-root",
        f"wp plugin list --update=available --format=json --fields=name,title,version,update_version --path={wp_path} --allow-root",
        f"wp theme list --update=available --format=json --fields=name,title,version,update_version --path={wp_path} --allow-root",
        f"wp core check-update --format=json --path={wp_path} --allow-root",
        f"wp cron event list --format=count --path={wp_path} --allow-root",
        f"wp db size --size_format=mb --path={wp_path} --allow-root",
    ]

    async with (_key_file(key) as kf,
                _known_hosts_file(host_key) as khf,
                _askpass_file(bool(password)) as askpass):
        results = await asyncio.gather(*[
            _run(host, port, user, kf, cmd, known_hosts_path=khf,
                 password=password, askpass_path=askpass)
            for cmd in commands
        ])

    (wp_r, php_r, plug_r, theme_r, core_r, cron_r, db_r) = results

    def _parse_list(raw) -> list:
        if not raw[0]:
            return []
        try:
            data = json.loads(raw[0])
            return data if isinstance(data, list) else []
        except Exception:
            return []

    plugin_list = _parse_list(plug_r)
    theme_list  = _parse_list(theme_r)

    # Parse core update
    core_update = False
    core_update_ver = ""
    if core_r[0]:
        try:
            updates = json.loads(core_r[0])
            if updates and isinstance(updates, list):
                core_update = True
                core_update_ver = updates[0].get("version", "")
        except Exception:
            pass

    def _int(val):
        v = (val[0] or "").strip()
        return int(v) if v.isdigit() else 0

    return {
        "wp_version":          (wp_r[0] or "").strip(),
        "php_version":         (php_r[0] or "").strip(),
        "plugin_updates":      len(plugin_list),
        "plugin_updates_list": plugin_list,
        "theme_updates":       len(theme_list),
        "theme_updates_list":  theme_list,
        "core_update":         core_update,
        "core_update_version": core_update_ver,
        "cron_count":          _int(cron_r),
        "db_size_mb":          (db_r[0] or "").strip(),
    }


# ── WP-CLI publish/read path (SSH-only sites — no REST/Application Password) ──
#
# post_title/post_content/post_excerpt are NEVER interpolated into the shell
# command string. Title/excerpt go through --post_title=<shlex-quoted>, and
# content is piped over STDIN to `wp post create -`/`wp post update <id> -`
# (WP-CLI's own documented mechanism for reading post_content from STDIN) —
# this avoids both shell-escaping edge cases and WP-CLI's own history of
# mangling multi-line --post_content=<...> arguments.

async def _cli_session(cred: dict):
    """Shared connection setup for the WP-CLI publish/read helpers below."""
    key = cred.get("key")
    password = cred.get("password")
    if not key and not password:
        return None, "Provide either an SSH private key or SSH password."
    return {
        "host": cred["host"], "port": int(cred.get("port", 22)), "user": cred["user"],
        "wp_path": shlex.quote(cred.get("wp_path", "/var/www/html")),
        "host_key": cred.get("host_key"), "key": key, "password": password,
    }, None


async def create_post_cli(cred: dict, title: str, content: str, status: str,
                          excerpt: str = "", date: str | None = None,
                          slug: str | None = None) -> tuple[dict | None, str | None]:
    """Create a post via `wp post create -` (content piped over STDIN). Returns (post, error)."""
    sess, err = await _cli_session(cred)
    if err:
        return None, err
    flags = [f"--post_title={shlex.quote(title)}", f"--post_status={shlex.quote(status)}", "--porcelain"]
    if excerpt:
        flags.append(f"--post_excerpt={shlex.quote(excerpt)}")
    if date:
        flags.append(f"--post_date={shlex.quote(date)}")
    if slug:
        flags.append(f"--post_name={shlex.quote(slug)}")
    cmd = f"wp post create - --path={sess['wp_path']} --allow-root " + " ".join(flags)

    async with (_key_file(sess["key"]) as kf,
                _known_hosts_file(sess["host_key"]) as khf,
                _askpass_file(bool(sess["password"])) as askpass):
        out, run_err = await _run(sess["host"], sess["port"], sess["user"], kf, cmd,
                                  known_hosts_path=khf, password=sess["password"],
                                  askpass_path=askpass, stdin_data=content or "")
    if out is None:
        return None, run_err or "SSH connection failed"
    post_id = out.strip()
    if not post_id.isdigit():
        return None, f"Unexpected wp-cli output: {post_id[:200]}"
    return {"id": post_id, "title": title, "status": status}, None


async def update_post_cli(cred: dict, post_id: str, title: str | None, content: str | None,
                          status: str | None, excerpt: str | None = None,
                          slug: str | None = None) -> tuple[dict | None, str | None]:
    """Update a post via `wp post update <id> -` (content piped over STDIN when given)."""
    sess, err = await _cli_session(cred)
    if err:
        return None, err
    if not str(post_id).isdigit():
        return None, "post_id must be a numeric WordPress post ID."
    flags = []
    if title is not None:
        flags.append(f"--post_title={shlex.quote(title)}")
    if status is not None:
        flags.append(f"--post_status={shlex.quote(status)}")
    if excerpt is not None:
        flags.append(f"--post_excerpt={shlex.quote(excerpt)}")
    if slug is not None:
        flags.append(f"--post_name={shlex.quote(slug)}")
    stdin_data = None
    content_flag = ""
    if content is not None:
        content_flag = "-"
        stdin_data = content
    cmd = (f"wp post update {shlex.quote(str(post_id))} {content_flag} "
          f"--path={sess['wp_path']} --allow-root " + " ".join(flags)).strip()

    async with (_key_file(sess["key"]) as kf,
                _known_hosts_file(sess["host_key"]) as khf,
                _askpass_file(bool(sess["password"])) as askpass):
        out, run_err = await _run(sess["host"], sess["port"], sess["user"], kf, cmd,
                                  known_hosts_path=khf, password=sess["password"],
                                  askpass_path=askpass, stdin_data=stdin_data)
    if out is None:
        return None, run_err or "SSH connection failed"
    return {"id": str(post_id), "title": title, "status": status}, None


async def list_posts_cli(cred: dict, limit: int = 20, search: str | None = None) -> tuple[list | None, str | None]:
    """List posts via `wp post list --format=json` (read-only, no REST needed)."""
    sess, err = await _cli_session(cred)
    if err:
        return None, err
    fields = "ID,post_title,post_status,post_date"
    flags = [f"--posts_per_page={int(limit)}", f"--fields={fields}", "--format=json"]
    if search:
        flags.append(f"--s={shlex.quote(search)}")
    cmd = f"wp post list --path={sess['wp_path']} --allow-root " + " ".join(flags)

    async with (_key_file(sess["key"]) as kf,
                _known_hosts_file(sess["host_key"]) as khf,
                _askpass_file(bool(sess["password"])) as askpass):
        out, run_err = await _run(sess["host"], sess["port"], sess["user"], kf, cmd,
                                  known_hosts_path=khf, password=sess["password"],
                                  askpass_path=askpass)
    if out is None:
        return None, run_err or "SSH connection failed"
    try:
        return json.loads(out) if out.strip() else [], None
    except Exception:
        return None, f"Unexpected wp-cli output: {out[:200]}"


_RANK_MATH_META_KEYS = {
    "description": "rank_math_description",
    "focus_keyword": "rank_math_focus_keyword",
}


async def set_post_meta_cli(cred: dict, post_id: str, meta_key: str, meta_value: str) -> tuple[bool, str | None]:
    """Set one WordPress post-meta field via `wp post meta update <id> <key> -`.

    meta_key is never attacker-controlled — callers pass one of a fixed,
    hardcoded set (see set_rank_math_meta_cli), never a value derived from
    user/article text. meta_value goes over STDIN like post content, so it
    is never placed on the command line regardless of its contents.
    """
    sess, err = await _cli_session(cred)
    if err:
        return False, err
    if not str(post_id).isdigit():
        return False, "post_id must be a numeric WordPress post ID."
    cmd = (f"wp post meta update {shlex.quote(str(post_id))} {shlex.quote(meta_key)} - "
          f"--path={sess['wp_path']} --allow-root")

    async with (_key_file(sess["key"]) as kf,
                _known_hosts_file(sess["host_key"]) as khf,
                _askpass_file(bool(sess["password"])) as askpass):
        out, run_err = await _run(sess["host"], sess["port"], sess["user"], kf, cmd,
                                  known_hosts_path=khf, password=sess["password"],
                                  askpass_path=askpass, stdin_data=meta_value)
    if out is None:
        return False, run_err or "SSH connection failed"
    return True, None


async def set_rank_math_meta_cli(cred: dict, post_id: str, description: str | None = None,
                                 focus_keyword: str | None = None) -> list[str]:
    """Write Rank Math SEO fields directly to wp_postmeta over SSH — the only reliable

    way to set them, since Rank Math does not register these fields for the
    WordPress REST API (show_in_rest is off by default; see Rank Math's own
    support guidance). Returns a list of human-readable error strings for any
    field that failed to write; empty list means everything succeeded.
    """
    errors = []
    if description is not None:
        ok, err = await set_post_meta_cli(cred, post_id, _RANK_MATH_META_KEYS["description"], description)
        if not ok:
            errors.append(f"meta description: {err}")
    if focus_keyword is not None:
        ok, err = await set_post_meta_cli(cred, post_id, _RANK_MATH_META_KEYS["focus_keyword"], focus_keyword)
        if not ok:
            errors.append(f"focus keyword: {err}")
    return errors


_SAFE_MEDIA_EXT = {"jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"}


async def upload_media_cli(cred: dict, b64_data: str, filename: str, title: str = "") -> tuple[dict | None, str | None]:
    """Upload media via `wp media import` for SSH-only sites (no REST/Application Password).

    The base64 payload is piped over STDIN and decoded server-side into a
    throwaway temp file (`mktemp`), imported with `wp media import`, then
    removed — the payload itself never appears as a shell argument. Only a
    whitelisted, non-attacker-controlled file extension (guessed from
    filename, falling back to a safe default) is used to build the mktemp
    suffix; nothing else derived from filename/title reaches the shell
    unescaped.
    """
    sess, err = await _cli_session(cred)
    if err:
        return None, err
    ext = (filename.rsplit(".", 1)[-1].lower() if "." in filename else "")
    ext = ext if ext in _SAFE_MEDIA_EXT else "img"
    title_flag = f" --title={shlex.quote(title)}" if title else ""
    cmd = (
        f"tmpfile=$(mktemp /tmp/wp_upload_XXXXXX.{ext}) && "
        f"base64 -d > \"$tmpfile\" && "
        f"wp media import \"$tmpfile\" --path={sess['wp_path']} --allow-root --porcelain{title_flag}; "
        f"rc=$?; rm -f \"$tmpfile\"; exit $rc"
    )

    async with (_key_file(sess["key"]) as kf,
                _known_hosts_file(sess["host_key"]) as khf,
                _askpass_file(bool(sess["password"])) as askpass):
        out, run_err = await _run(sess["host"], sess["port"], sess["user"], kf, cmd,
                                  known_hosts_path=khf, password=sess["password"],
                                  askpass_path=askpass, stdin_data=b64_data, timeout=60)
    if out is None:
        return None, run_err or "SSH connection failed"
    media_id = out.strip()
    if not media_id.isdigit():
        return None, f"Unexpected wp-cli output: {media_id[:200]}"
    return {"id": media_id, "title": title or filename}, None
