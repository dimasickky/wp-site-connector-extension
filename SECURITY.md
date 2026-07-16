# Security Policy

## Supported version

Security fixes are made on the latest version of this repository.

| Version | Supported |
| --- | --- |
| 0.4.x | Yes |
| Earlier releases | No |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for suspected vulnerabilities or expose credentials, application passwords, private keys, or vulnerable production URLs in an issue, pull request, or discussion.

Instead, report the issue privately to the repository owner through GitHub:

1. Open the repository owner’s GitHub profile: [@dimasickky](https://github.com/dimasickky).
2. Use GitHub’s private contact route available there, or report through the relevant Imperal Cloud support channel.
3. Include a concise description, affected version, reproduction steps, and impact. Redact all secrets before sending.

A report will be acknowledged as soon as practical. If confirmed, a fix will be prepared and coordinated before public disclosure.

## Secret-handling rules

This is a public repository. Never commit or paste any of the following:

- WordPress Application Passwords;
- SSH passwords or private keys;
- Fernet encryption keys, including `wp_encryption_key`;
- API tokens, cookies, authorization headers, or `.env` files;
- production database dumps, logs, or user content.

The extension expects its `wp_encryption_key` to be configured as a secret in the Imperal Developer Portal. It must not appear in source code, tests, documentation, issue reports, or CI logs.
