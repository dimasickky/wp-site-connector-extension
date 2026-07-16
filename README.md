# WordPress Site Connector

[![Imperal SDK](https://img.shields.io/badge/Imperal%20SDK-5.9.6-6c5ce7?logo=python&logoColor=white)](https://imperal.io)
[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL--2.1-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)

> Secure WordPress connector for Imperal Cloud — connect sites, manage content, upload media, and publish AI-generated articles without leaving your workspace.

**WordPress Site Connector** connects your WordPress sites to [Imperal Cloud](https://imperal.io), the ICNLI AI Cloud OS. It uses WordPress Application Passwords and the native REST API: no WordPress plugin is required.

## What it can do

| Area | Capabilities |
| --- | --- |
| 🔌 **Connect** | Connect one or more HTTPS WordPress sites with a WordPress username and Application Password |
| 📚 **Read** | Browse posts, pages, media, comments, scheduled posts, users, WooCommerce orders, and custom post types |
| ✍️ **Publish** | Create drafts, publish immediately, schedule posts, and update existing posts |
| 🖼️ **Media** | Upload images to the WordPress Media Library, set a featured image, and place images anywhere in article content |
| 🩺 **Health** | Check API reachability, authentication, SSL status, and content counts |
| 🖥️ **Optional SSH** | Use WP-CLI for server information, update checks, cron status, and database-size checks |

## Quick start

### 1. Install the extension

Install **WordPress Site Connector** from Imperal Cloud when it is available in your workspace.

### 2. Create a WordPress Application Password

On your WordPress site, sign in as the account that should manage content:

1. Open **Users → Profile**.
2. Find **Application Passwords**.
3. Add a name such as `Imperal Cloud` and click **Add New Application Password**.
4. Copy the generated password. WordPress shows it only once.

> WordPress Application Passwords are built into WordPress 5.6 and later. They are scoped credentials, so you can revoke this connector’s access at any time from the same Profile screen.

### 3. Connect the site

Ask Webbee in Imperal Cloud to connect your site, providing:

- the full HTTPS URL, for example `https://example.com`;
- the WordPress username that created the Application Password;
- the Application Password from the previous step.

The connector verifies the credentials through WordPress’s REST API before saving the connection.

## Publishing an article with images

The publish flow is deliberately simple and follows WordPress’s own model.

### Cover image

1. Upload the image with `upload_media`.
2. The result contains a WordPress `media_id` and public `source_url`.
3. Pass that `media_id` as `featured_media_id` to `create_post` or `update_post`.

WordPress stores the cover separately as the post’s **Featured Image**.

### Image inside the article

1. Upload the image with `upload_media`.
2. Take the returned `source_url`.
3. Put an image tag exactly where it belongs in the article HTML:

```html
<p>Introductory paragraph.</p>
<figure class="wp-block-image">
  <img src="https://example.com/wp-content/uploads/2026/07/diagram.png"
       alt="Architecture diagram">
</figure>
<p>The paragraph that follows the image.</p>
```

Pass this HTML as `content` to `create_post` or `update_post`. WordPress renders content top-to-bottom, so the image appears precisely at that location.

## Security model

Security is not an afterthought here:

- WordPress Application Passwords and SSH credentials are encrypted at rest with Fernet before storage.
- The encryption key is an Imperal Developer Portal secret (`wp_encryption_key`), never committed to this repository.
- Existing plaintext credentials from earlier releases remain readable for a safe migration and are encrypted on their next write.
- SSH host keys are pinned on first connection (TOFU). Future SSH/WP-CLI sessions verify the host identity instead of silently accepting a changed server key.
- The connector requires `https://` site URLs.
- Secrets, passwords, private SSH keys, and user content are never logged by the extension.

Read [SECURITY.md](SECURITY.md) for vulnerability reporting guidance.

## Optional SSH / WP-CLI connection

The REST API connection is enough for content and publishing. SSH is optional and only needed for server-level diagnostics through WP-CLI, such as PHP version, pending updates, cron status, and database size.

To add it, provide the host, port, SSH username, absolute WordPress path, and either an SSH private key or password. On first use, the connector captures and pins the server’s SSH host key.

## Development

### Requirements

- Python 3.11+
- [Imperal SDK](https://github.com/imperalcloud/imperal-sdk) 5.9.6

### Install and test

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e /path/to/imperal-sdk
pip install -r requirements.txt pytest pytest-asyncio

pytest tests/ -q
imperal validate .
imperal build .
```

Expected current result:

- test suite: all tests pass;
- validator: 0 errors, 0 warnings.

## Roadmap

- [x] Secure WordPress REST API connection
- [x] Content discovery and site health
- [x] WordPress publishing: create and update posts
- [x] Media upload, featured images, and inline images
- [x] Optional SSH / WP-CLI diagnostics with key or password authentication and host-key pinning
- [ ] Static-page publishing
- [ ] Image resize/optimization before upload

## Project origin and attribution

This repository is an independently maintained fork of the original
[`ivanco-bluebeeweb-com/imperal-ext-wp_site_connector`](https://github.com/ivanco-bluebeeweb-com/imperal-ext-wp_site_connector)
project. The public repository preserves clear upstream attribution while starting from a curated, security-reviewed snapshot. This fork adds credential-at-rest encryption, SSH host-key pinning, working key/password authentication, post publishing, and media workflows.

## License

Licensed under the [GNU Lesser General Public License v2.1](LICENSE).
