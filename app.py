from imperal_sdk import Extension, ChatExtension

ext = Extension(
    "wp-site-connector",
    version="0.4.1",
    display_name="WP Site Connector",
    description="Securely connect WordPress sites, publish posts, upload media, and inspect site health.",
    icon="icon.svg",
    actions_explicit=True,
)

chat = ChatExtension(ext, tool_name="wp-site-connector", description="Connect, inspect, and publish to WordPress sites")


# ─── Secrets (app-scope: developer-owned, shared by all users) ────────────── #

ext.secret(
    name="wp_encryption_key",
    description=(
        "Fernet key used to encrypt WordPress Application Passwords and SSH "
        "credentials before they reach storage. Shared across all users; "
        "generate once with `Fernet.generate_key()` and set in Developer "
        "Portal → Secrets."
    ),
    scope="app",
    required=True,
    max_bytes=256,
)(lambda: None)


@ext.health_check
async def health_check(ctx) -> dict:
    """Liveness probe for the extension."""
    return {"status": "ok"}


