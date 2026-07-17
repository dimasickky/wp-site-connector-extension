"""Tests for wp_cli.normalize_ssh_key — repairing/validating a pasted SSH
private key BEFORE attempting an SSH connection, so a broken paste fails
fast with a clear message instead of a 15+ second opaque libcrypto error."""
import wp_cli

_VALID_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "QyNTUxOQAAACA2vn3wuvnb/k32o/FeKimkt/62Sa73fNrXi7SmvjmHUwAAAKBlgFc7ZYBX\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)


def test_valid_key_passes_through_unchanged_in_content():
    normalized, err = wp_cli.normalize_ssh_key(_VALID_KEY)
    assert err is None
    assert "-----BEGIN OPENSSH PRIVATE KEY-----" in normalized
    assert "-----END OPENSSH PRIVATE KEY-----" in normalized


def test_valid_key_gets_exactly_one_trailing_newline():
    normalized, err = wp_cli.normalize_ssh_key(_VALID_KEY + "\n\n\n")
    assert err is None
    assert normalized.endswith("\n")
    assert not normalized.endswith("\n\n")


def test_literal_backslash_n_gets_repaired_into_real_linebreaks():
    """The classic form-paste bug: real line breaks collapse into literal '\\n' text."""
    mangled = _VALID_KEY.replace("\n", "\\n")
    normalized, err = wp_cli.normalize_ssh_key(mangled)
    assert err is None
    assert "\\n" not in normalized
    assert "-----BEGIN OPENSSH PRIVATE KEY-----\n" in normalized
    assert "-----END OPENSSH PRIVATE KEY-----" in normalized


def test_crlf_line_endings_get_normalized_to_lf():
    crlf_key = _VALID_KEY.replace("\n", "\r\n")
    normalized, err = wp_cli.normalize_ssh_key(crlf_key)
    assert err is None
    assert "\r" not in normalized


def test_trailing_whitespace_per_line_is_stripped():
    padded = "\n".join(line + "   " for line in _VALID_KEY.strip().split("\n"))
    normalized, err = wp_cli.normalize_ssh_key(padded)
    assert err is None
    assert "   \n" not in normalized


def test_empty_key_is_rejected_with_clear_message():
    normalized, err = wp_cli.normalize_ssh_key("")
    assert normalized is None
    assert "empty" in err.lower()


def test_whitespace_only_key_is_rejected():
    normalized, err = wp_cli.normalize_ssh_key("   \n  \n")
    assert normalized is None
    assert err is not None


def test_missing_begin_end_markers_is_rejected_with_actionable_message():
    normalized, err = wp_cli.normalize_ssh_key("just some random text, not a key at all")
    assert normalized is None
    assert "private key" in err.lower()
    assert "BEGIN" in err


def test_public_key_pasted_by_mistake_is_rejected():
    pub_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDa+ffC6+dv+Tfaj8V4qKaS3 wp-site-connector@imperal"
    normalized, err = wp_cli.normalize_ssh_key(pub_key)
    assert normalized is None
    assert err is not None


def test_key_file_context_manager_writes_normalized_content(tmp_path, monkeypatch):
    """_key_file should self-heal a mangled key (literal \\n) before writing it to disk,
    so even a credential stored before this fix existed works on next use."""
    import asyncio

    async def _check():
        mangled = _VALID_KEY.replace("\n", "\\n")
        async with wp_cli._key_file(mangled) as path:
            assert path is not None
            with open(path) as f:
                written = f.read()
            assert "\\n" not in written
            assert "-----BEGIN OPENSSH PRIVATE KEY-----\n" in written

    asyncio.run(_check())


def test_key_file_context_manager_none_when_no_key():
    import asyncio

    async def _check():
        async with wp_cli._key_file("") as path:
            assert path is None

    asyncio.run(_check())
