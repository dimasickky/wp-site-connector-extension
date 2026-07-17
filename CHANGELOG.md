# Changelog

## v0.6.0 — 2026-07-17 — Declared capabilities + richer connected-sites context

### Added
- **Declared `capabilities` on the extension** (`read`/`write`) so the platform's
  per-tool access checks have an explicit capability set to enforce against,
  instead of falling back to an unrestricted default.
- **`sites_overview` background context now includes the connected sites
  themselves** (id, title, URL) — not just a count — so the assistant can
  answer site-scoped questions without re-listing sites on every turn.
  Refreshes automatically after a site is connected or disconnected, and
  surfaces a short alert when the site list changes.

## v0.5.2 — 2026-07-17 — Rank Math SEO meta (meta_description, focus_keyword)

### Added
- **`meta_description`** and **`focus_keyword`** fields on `create_post` and
  `update_post` — write directly into Rank Math's own SEO fields
  (`rank_math_description`, `rank_math_focus_keyword`) so the meta
  description actually shows up in Google's search snippet and Rank Math's
  on-page analysis picks up the right focus keyword.
- **SSH-only, by design**: Rank Math does not register these fields for the
  WordPress REST API (`show_in_rest` is off by default), so there is no
  reliable way to set them over REST at all. On SSH-connected sites we write
  them straight into `wp_postmeta` via `wp post meta update <id> <key> -`
  (value piped over STDIN, key always one of a fixed hardcoded pair — never
  attacker-controlled — same injection-safety pattern as every other WP-CLI
  call in this extension).
- On Application-Password/REST sites, passing `meta_description`/
  `focus_keyword` now returns a **clear, honest message** explaining they
  were not saved and why (rather than silently dropping them) — with a
  pointer to connect over SSH instead.

### Tests
- +11 new tests: WP-CLI meta command construction/injection-safety, Rank
  Math key mapping, REST-side honest-rejection message. Full suite:
  **121/121 passing**. `imperal validate .`: 0 errors, 0 warnings.


## v0.5.1 — 2026-07-17 — Custom post slug

### Added
- **`slug`** field on `create_post` and `update_post` — set a custom URL slug
  (e.g. `slug="infinityfree-review-2026"` to publish at
  `https://yoursite.com/infinityfree-review-2026/`) instead of letting
  WordPress auto-derive one from the title. Works on both auth paths: sent
  as the standard WP REST API `slug` field for Application-Password sites,
  and as WP-CLI's `--post_name` flag (shell-quoted, same injection-safety
  guarantees as every other interpolated field) for SSH-only sites.
- Omit `slug` entirely to keep the previous default behaviour (WordPress
  auto-generates one from the title).

### Tests
- +5 new tests covering slug on both REST and WP-CLI create/update paths,
  including quoting safety for slugs containing shell metacharacters. Full
  suite: **110/110 passing**. `imperal validate .`: 0 errors, 0 warnings.


## v0.5.0 — 2026-07-17 — Connect via SSH only (no Application Password)

### Added
- **`connect_site_ssh`** — a second, independent way to connect a site:
  SSH host/port/user/path + a private key or password, and nothing else.
  No WordPress Application Password is required or stored for these sites.
  Validated over WP-CLI (`wp core version`, then `wp option get siteurl` to
  learn the real site URL and give the connected site a proper name/id) —
  no REST call is made anywhere in this path.
- **`Site.auth_mode`** field (`"app_password"` | `"ssh"`) records which way a
  site was connected, so every other handler knows which client to use
  without guessing.
- **`create_post` / `update_post` / `upload_media`** now branch on
  `auth_mode`: Application-Password sites still go through the REST API
  exactly as before; SSH-only sites publish entirely through WP-CLI
  (`wp post create`, `wp post update`, `wp media import`) via new
  `wp_cli.create_post_cli` / `update_post_cli` / `upload_media_cli` /
  `list_posts_cli` helpers. Existing REST-connected sites are completely
  unaffected — this is additive, not a replacement.
- Panel: a new **"Connect via SSH"** button next to "Connect via Password"
  in the sidebar, its own form (no Application Password field at all), and
  a dedicated SSH-only detail view (server health + Posts via WP-CLI)
  instead of the old REST-only detail view falsely reporting "Credential
  missing" for these sites.

### Security
- Post title/excerpt/search terms are always shell-quoted with
  `shlex.quote()` before being interpolated into any remote WP-CLI command.
- Post **content** is never placed on the command line at all — it is piped
  over STDIN to `wp post create -` / `wp post update <id> -` (WP-CLI's own
  documented mechanism for this), which sidesteps shell-escaping edge cases
  entirely rather than trying to escape arbitrarily large/special text.
- Media bytes for `upload_media_cli` are likewise piped over STDIN
  (base64, decoded server-side into a throwaway `mktemp` file that is
  removed after `wp media import` runs) — never a command-line argument.
- `wp_cli.test_connection` / `get_server_info`'s pre-existing `wp_path`
  interpolation is now also `shlex.quote()`-wrapped (was previously
  unquoted — a latent injection surface via a crafted `wp_path`, closed
  as part of this pass since the new CLI helpers share the same command
  -building pattern).

### Tests
- 22 new tests: SSH-only connect (success, missing credential, connection
  failure, site-url failure cleanup), publish/update/upload branching by
  `auth_mode` (`tests/test_publish_ssh.py`), WP-CLI command-construction
  injection safety (`tests/test_wp_cli_publish.py`), and panel rendering
  for the new SSH connect form + SSH-only detail view.
- Full suite: **105/105 passing**.
- `imperal validate .`: **0 errors, 0 warnings**, 1 informational lifecycle
  suggestion (pre-existing, unrelated).

### Not done yet (still open)
- SSH-only sites' detail view only lists Posts via WP-CLI for now — pages,
  media library browsing, comments, users, and WooCommerce orders still
  require the Application Password/REST connection method.
- No page (`create_page`) equivalent on either auth path.

## v0.4.1 — 2026-07-16 — SSH password authentication

### Fixed
- SSH password authentication now works end-to-end in both the initial
  WP-CLI connection test and subsequent server-info commands. Earlier code
  exposed `ssh_password` in the public model but rejected every credential
  that did not contain a private key.
- Passwords are provided to the system `ssh` process through a short-lived
  `SSH_ASKPASS` helper and child-only environment variable. They are never
  placed in command-line arguments or written into the helper file.
- Password mode uses `BatchMode=no` and explicitly requests
  password/keyboard-interactive authentication; key mode retains
  `BatchMode=yes`.
- Strict pinned host-key verification remains unchanged for both auth modes.

### Tests
- Added password-mode command, askpass secrecy, connection, and server-info
  tests. Full suite: **80/80 passing**.
- `imperal validate .`: **0 errors, 0 warnings**, 1 informational lifecycle
  suggestion.

## v0.4.0 — 2026-07-16 — Media upload + cover image (Phase 2)

### Added
- **`upload_media`** — uploads a file (image) to the connected site's Media
  Library via `POST /wp/v2/media`. Accepts a `FileUpload`-style payload
  (`data_base64` + `name` + `content_type`, same shape `notes.upload_attachment`
  already uses) rather than a raw external URL — `ctx.http`'s response body
  is text/JSON-decoded and not a reliable byte-for-byte channel for binary
  downloads, so re-uploading straight from an external link was judged
  unsafe; the caller (user or an upstream tool like article-writer) supplies
  the image bytes directly instead. Returns the new WordPress media id and
  its public `source_url` — feed the id into `create_post`/`update_post`'s
  new `featured_media_id` for a cover image, or splice the returned url into
  `content` as an `<img>` tag to place it anywhere inside the post body.
- **`featured_media_id`** — new optional field on both `create_post` and
  `update_post`. Maps to WordPress's own `featured_media` REST field (the
  cover-image slot, separate from the post body).
- New `wp_client.wp_upload_media()` (raw-bytes POST with
  `Content-Disposition: attachment; filename=...`, not JSON) and
  `guess_image_content_type()` helper.
- New model `UploadMediaParams`; `MediaItem`/media-related response reuses
  existing SDL entity.
- 5 new tests in `tests/test_media.py` (no file provided, invalid base64,
  unknown site, success returns id+url, bad-credentials) — full suite now
  76/76 passing.

### How "picture anywhere" actually works (documented, no new mechanism needed)
`content` on `create_post`/`update_post` is plain HTML — WordPress renders it
top-to-bottom exactly as given. So placing an image at a specific spot inside
the text is just: upload it first (`upload_media` → get `source_url`), then
embed `<img src="...">` at that position in the `content` string you send.
No separate "insert into content" tool was needed; documented this directly
in the two params' field descriptions so the model doesn't have to guess.

### Not done yet (still open)
- No `create_page` equivalent — posts only for now.
- No image resizing/optimization before upload — sends bytes as given.

## v0.3.0 — 2026-07-16 — Publish capability (Phase 1)

### Added
- **`create_post`** — creates a new post on a connected site via
  `POST /wp/v2/posts`. Defaults to `status="draft"`; pass `status="publish"`
  to publish immediately, or `status="future"` + `date` to schedule.
  Validates status against the allowed WordPress values and requires `date`
  when scheduling. Supports optional `excerpt`, `categories`, `tags`.
- **`update_post`** — partially updates an existing post via
  `POST /wp/v2/posts/<id>` (WordPress accepts POST for updates, no PUT/PATCH
  needed). Only fields explicitly passed are changed; rejects a call with no
  fields at all, and surfaces a clear "not found" error on a 404 post id.
- New module `handlers_publish.py` (kept separate from the read-only
  `handlers_read.py` to preserve the connect/read/publish/cli module split).
- New `wp_client.wp_post()` helper (Basic Auth POST, mirrors `wp_get`).
- New Pydantic models `CreatePostParams` / `UpdatePostParams` in `models.py`.
- 9 new tests in `tests/test_publish.py` (invalid status, missing schedule
  date, unknown site, success, bad credentials, no-op update, not-found,
  successful update) — full suite now 70/70 passing.

### Not done yet (still open)
- No media upload endpoint (`create_post` cannot attach a featured image in
  one call yet — would need a separate `/wp/v2/media` POST + attach step).
- No page (`create_page`) equivalent — posts only for now.
- The pre-existing SSH-password bug noted in v0.2.0 is still unfixed (out of
  scope for this pass too).

## v0.2.0 — 2026-07-16 — Security hardening

### Fixed — credentials at rest
- **WordPress Application Passwords and SSH credentials (key/password/host_key)
  are now encrypted at rest** via Fernet, mirroring the pattern already
  proven in the `sql-db` extension (`app.encrypt_password`). Previously these
  were stored as plaintext strings in `ctx.store`.
  - New module `crypto_util.py`: `encrypt_value` / `decrypt_value`.
  - New app-scope secret `wp_encryption_key` (declared via `ext.secret(...)`,
    set once in Developer Portal → Secrets — never in code).
  - `decrypt_value` degrades gracefully for legacy plaintext values written
    before this release (returns them unchanged instead of crashing) — an
    already-connected site keeps working, and gets re-encrypted on its next
    `set_credential`/`set_ssh_cred` write.

### Fixed — SSH host key verification
- Removed `StrictHostKeyChecking=no` / `UserKnownHostsFile=/dev/null`, which
  accepted any server identity silently (MITM risk) on every SSH/WP-CLI call.
- New **TOFU (trust-on-first-use) host key pinning**: `add_ssh` now scans the
  server's SSH host key once via `ssh-keyscan` (`wp_cli.scan_host_key`),
  stores it alongside the (now-encrypted) SSH credential, and every
  subsequent connection verifies strictly against that pinned key
  (`StrictHostKeyChecking=yes` + a single-entry `known_hosts` file).
  - If a server's host key ever changes after pinning, the connection is
    hard-rejected with a message pointing at the two real causes (server
    rebuild vs. possible MITM) instead of silently trusting the new key.
  - Legacy SSH credentials saved before this release (no pinned `host_key`
    yet) fall back to `StrictHostKeyChecking=accept-new` — strictly safer
    than the old disabled-checking behavior, and self-heals to a pinned key
    on the next successful connection.

### Changed
- `imperal-sdk` bumped `5.4.2` → `5.9.6` (matches the SDK version actually
  installed/validated; `requirements.txt` was previously unpinned).
- `requirements.txt`: pinned `imperal-sdk==5.9.6`, added `cryptography>=42.0.0`.
- Manifest (`imperal.json`) regenerated via `imperal build` — now lists the
  `wp_encryption_key` secret and the auto-registered Secrets panel.

### Known limitation (not fixed in this pass — flagging, not silently working
around)
- `wp_cli.test_connection` / `get_server_info` require `cred["key"]`
  (SSH private key) even though `AddSSHParams`/`add_ssh` accept
  `ssh_password` as an alternative auth method — password-based SSH is
  currently always rejected by the client regardless of what the user
  provides. Pre-existing behavior, unrelated to this security pass; left
  as-is to keep this changeset scoped to security hardening.

### Tests
- Added `tests/test_crypto_util.py` (encrypt/decrypt roundtrip, empty-value
  passthrough, legacy-plaintext fallback, missing-key error).
- Added `tests/test_wp_cli_hostkey.py` (pinned vs. accept-new SSH flag
  selection, `scan_host_key` error path).
- Added `tests/conftest.py` patching `MockContext` to seed `ctx.secrets`
  with a test Fernet key — required so the existing 54 tests didn't have to
  be rewritten individually to know about the new secret.
- Full suite: **61/61 passing.**
- `imperal validate .` (SDK 5.9.6): **0 errors, 0 warnings**, 1 info
  (missing `@ext.on_install` — not addressed, out of scope).

## v0.1.0 — initial fork snapshot
- Connect WordPress sites by URL + Application Password (Basic auth).
- Read: posts, pages, media, comments, scheduled posts, users, WooCommerce
  orders, custom post types.
- SSH mode (`add_ssh`/`get_server_info`) for WP-CLI diagnostics: PHP/WP
  version, pending plugin/theme/core updates, cron count, DB size.
- Publishing not implemented.
