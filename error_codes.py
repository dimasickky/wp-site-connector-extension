"""App-declared structured error codes for wp-site-connector.

These pair with the platform taxonomy (`imperal_sdk.chat.error_codes`) for
cases that taxonomy doesn't cover — problems specific to reaching a *user's*
WordPress site over REST/SSH, not the Imperal backend itself. Every code
here matches the SDK's app-declared pattern `^[A-Z][A-Z0-9_]{2,63}$`
(imperal_sdk.types.action_result.ActionResult.error).

Platform codes (imported directly where they apply — permission, rate
limit, backend 5xx, validation, internal) are used as-is; these WP_* codes
only exist where no platform code honestly fits.
"""

WP_SITE_NOT_CONNECTED = "WP_SITE_NOT_CONNECTED"       # no site record / stored credential for this site_id
WP_NO_SITES_CONNECTED = "WP_NO_SITES_CONNECTED"       # refresh_all_sites with zero connected sites
WP_SITE_UNREACHABLE = "WP_SITE_UNREACHABLE"           # network/transport failure reaching the site
WP_SSH_CONNECTION_FAILED = "WP_SSH_CONNECTION_FAILED"  # SSH handshake/auth failure
WP_SSH_COMMAND_FAILED = "WP_SSH_COMMAND_FAILED"       # SSH connected but a WP-CLI command failed
WP_SSH_KEY_INVALID = "WP_SSH_KEY_INVALID"             # pasted private key malformed
WP_SSH_NOT_CONFIGURED = "WP_SSH_NOT_CONFIGURED"       # SSH-only feature requested, no SSH credential stored
WP_POST_NOT_FOUND = "WP_POST_NOT_FOUND"               # post/page id doesn't exist on the site
WP_WOOCOMMERCE_NOT_INSTALLED = "WP_WOOCOMMERCE_NOT_INSTALLED"  # list_orders on a non-WooCommerce site
WP_SEO_FIELDS_REST_UNSUPPORTED = "WP_SEO_FIELDS_REST_UNSUPPORTED"  # Rank Math fields requested on a REST-only site
