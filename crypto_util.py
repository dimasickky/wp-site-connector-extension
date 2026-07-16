"""Fernet encryption helpers for credentials at rest.

Mirrors the pattern already proven in sql-db (app.py encrypt_password):
an app-scope Fernet key lives in Developer Portal → Secrets
(``wp_encryption_key``), never in code. WP Application Passwords and SSH
credentials are encrypted before they reach ``ctx.store`` and decrypted
only in-memory when a request needs them.

``decrypt_value`` degrades gracefully for values written before this
module existed (plain text) — it tries Fernet first, and if the token is
not a valid Fernet token it returns the original string unchanged. This
lets an already-deployed site's stored credential keep working; the next
``set_credential``/``set_ssh_cred`` call re-encrypts it going forward.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


async def _fernet(ctx) -> Fernet:
    key = (await ctx.secrets.get("wp_encryption_key")) or ""
    if not key:
        raise RuntimeError("wp_encryption_key not set — configure it in Developer Portal → Secrets")
    return Fernet(key.encode())


async def encrypt_value(ctx, plaintext: str) -> str:
    """Encrypt a secret string for storage. Empty input passes through unchanged."""
    if not plaintext:
        return plaintext
    f = await _fernet(ctx)
    return f.encrypt(plaintext.encode()).decode()


async def decrypt_value(ctx, stored: str) -> str:
    """Decrypt a stored value. Falls back to returning it as-is for legacy
    plaintext values written before encryption was introduced."""
    if not stored:
        return stored
    try:
        f = await _fernet(ctx)
        return f.decrypt(stored.encode()).decode()
    except InvalidToken:
        return stored
    except Exception:
        # Key not configured yet, or any other decode issue — surface the
        # raw stored value rather than crash a read path; callers that need
        # the credential to actually work will fail downstream (e.g. WP
        # rejects a garbled password), which is a much safer failure mode
        # than losing the extension's ability to read anything at all.
        return stored
