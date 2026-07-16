import pytest
from imperal_sdk.testing import MockContext, MockSecretStore

import crypto_util


async def test_encrypt_then_decrypt_roundtrip():
    ctx = MockContext()
    plaintext = "s3cr3t-app-password"
    encrypted = await crypto_util.encrypt_value(ctx, plaintext)
    assert encrypted != plaintext
    assert await crypto_util.decrypt_value(ctx, encrypted) == plaintext


async def test_encrypt_empty_string_passes_through():
    ctx = MockContext()
    assert await crypto_util.encrypt_value(ctx, "") == ""
    assert await crypto_util.decrypt_value(ctx, "") == ""


async def test_decrypt_legacy_plaintext_value_falls_back_unchanged():
    """Values written before encryption was introduced are not valid Fernet
    tokens — decrypt_value must return them as-is rather than crash, so
    existing connected sites keep working until they're reconnected."""
    ctx = MockContext()
    legacy_plaintext = "old-password-stored-before-encryption"
    assert await crypto_util.decrypt_value(ctx, legacy_plaintext) == legacy_plaintext


async def test_encrypt_without_key_configured_raises():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})  # no wp_encryption_key set
    with pytest.raises(RuntimeError):
        await crypto_util.encrypt_value(ctx, "pw")
