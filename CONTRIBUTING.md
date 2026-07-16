# Contributing

Thanks for helping improve WordPress Site Connector.

## Before opening a pull request

1. Keep changes focused and document user-visible behavior.
2. Never include credentials, SSH keys, Fernet keys, API tokens, `.env` files, production logs, or real customer content.
3. Add or update tests for changed behavior.
4. Run the checks from the repository root:

   ```bash
   pytest tests/ -q
   imperal validate .
   ```

5. Regenerate the manifest when decorators, models, panels, or extension metadata change:

   ```bash
   imperal build .
   ```

## Code guidelines

- Use `ctx.http`; do not add `requests` or direct `httpx` usage.
- Keep secrets in Imperal’s secret store. Do not read them from source files or log them.
- Keep write operations explicit and use the correct `action_type`.
- Preserve the split between connection, read, publish, and WP-CLI handlers where practical.
- Keep public documentation accurate whenever an end-user flow changes.

## Reporting security issues

Do not use public issues for vulnerabilities. Follow [SECURITY.md](SECURITY.md).
