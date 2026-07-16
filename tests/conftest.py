"""Shared pytest fixtures / patches for wp-site-connector tests.

Patches ``imperal_sdk.testing.MockContext`` so every ``MockContext()`` call
in the test suite gets a working ``ctx.secrets`` (a MockSecretStore seeded
with a valid Fernet key under ``wp_encryption_key``) — mirroring what the
real kernel attaches in production after ``ext.secret(...)`` is configured
in Developer Portal → Secrets. Without this, storage.py's encrypt/decrypt
helpers would raise AttributeError in every test that touches credentials.

This module is imported by pytest automatically (conftest.py convention)
before test modules are collected, so the patched MockContext is what
``from imperal_sdk.testing import MockContext`` binds to in each test file.
"""
from cryptography.fernet import Fernet

import imperal_sdk.testing as _testing_mod
from imperal_sdk.testing import MockContext as _RealMockContext, MockSecretStore

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _mock_context_with_secrets(*args, **kwargs):
    ctx = _RealMockContext(*args, **kwargs)
    ctx.secrets = MockSecretStore({"wp_encryption_key": TEST_FERNET_KEY})
    return ctx


_testing_mod.MockContext = _mock_context_with_secrets
