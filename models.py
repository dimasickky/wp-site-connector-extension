from pydantic import BaseModel, Field
from imperal_sdk import sdl

VNEXT = "requires companion plugin (vNext)"


class ConnectSiteParams(BaseModel):
    url: str = Field(description="Full https:// URL of the WordPress site, e.g. https://example.com")
    username: str = Field(description="WordPress username that created the Application Password")
    app_password: str = Field(description="WordPress Application Password (from Users → Profile → Application Passwords)")


class SiteIdParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


class ListContentParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")
    search: str | None = Field(default=None, description="Optional search term")


class ListMediaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")


class _NoParams(BaseModel):
    pass


class AddSSHParams(BaseModel):
    site_id: str = Field(default="", description="Site id — set automatically by the panel form")
    ssh_host: str = Field(description="SSH hostname or IP address of the server")
    ssh_port: int = Field(default=22, description="SSH port (default 22)")
    ssh_user: str = Field(description="SSH username")
    wp_path: str = Field(description="Absolute path to the WordPress installation on the server, e.g. /var/www/html")
    ssh_key: str = Field(default="", description="SSH private key in PEM format. Use this OR ssh_password.")
    ssh_password: str = Field(default="", description="SSH password. Use this OR ssh_key.")


class ConnectSiteSSHParams(BaseModel):
    ssh_host: str = Field(description="SSH hostname or IP address of the server")
    ssh_port: int = Field(default=22, description="SSH port (default 22)")
    ssh_user: str = Field(description="SSH username")
    wp_path: str = Field(description="Absolute path to the WordPress installation on the server, e.g. /var/www/html")
    ssh_key: str = Field(default="", description="SSH private key in PEM format. Use this OR ssh_password.")
    ssh_password: str = Field(default="", description="SSH password. Use this OR ssh_key.")


class ListCommentsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    status: str = Field(default="hold", description="Comment status: 'hold' (pending moderation), 'approved', 'spam', or 'all'")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")


class ListCustomPostsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_type: str = Field(description="REST base slug of the custom post type, e.g. 'products', 'events', 'portfolio'")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")
    search: str | None = Field(default=None, description="Optional search term")


class CreatePostParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    title: str = Field(description="Post title")
    content: str = Field(default="", description="Post body as HTML. To place an image INSIDE the text at a specific spot, embed an <img src=\"...\"> tag (or a <figure class=\"wp-block-image\"><img .../></figure> block) at that exact position — use the url returned by a prior upload_media call. WordPress renders the content top-to-bottom exactly as given.")
    status: str = Field(default="draft", description="'draft', 'publish', 'pending', or 'future' (requires date)")
    excerpt: str = Field(default="", description="Optional short excerpt/summary")
    date: str | None = Field(default=None, description="ISO 8601 datetime for scheduled publication — required when status='future'")
    slug: str | None = Field(default=None, description="Custom URL slug (e.g. 'infinityfree-review-2026' to publish at https://site.com/infinityfree-review-2026/). Omit to let WordPress auto-generate one from the title.")
    categories: list[int] = Field(default_factory=list, description="Optional WordPress category IDs")
    tags: list[int] = Field(default_factory=list, description="Optional WordPress tag IDs")
    featured_media_id: int | None = Field(default=None, description="Media library id to use as the featured image (cover) — get this from a prior upload_media call. This sets the post's cover, separate from any images embedded in content.")


class UpdatePostParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: str = Field(description="WordPress post ID from a previous list_posts call — never invent it")
    title: str | None = Field(default=None, description="New title — omit to leave unchanged")
    content: str | None = Field(default=None, description="New body as HTML — omit to leave unchanged. To place an image INSIDE the text, embed <img src=\"...\"> at that exact position using a url from a prior upload_media call.")
    status: str | None = Field(default=None, description="New status: 'draft', 'publish', 'pending', 'future' — omit to leave unchanged")
    excerpt: str | None = Field(default=None, description="New excerpt — omit to leave unchanged")
    date: str | None = Field(default=None, description="New ISO 8601 scheduled datetime — omit to leave unchanged")
    slug: str | None = Field(default=None, description="New custom URL slug — omit to leave unchanged")
    featured_media_id: int | None = Field(default=None, description="New media library id for the featured image (cover) — omit to leave unchanged. Get this from a prior upload_media call.")


class UploadMediaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    files: object = Field(
        default=None,
        description="FileUpload payload (list[dict] with data_base64/name/content_type) — the image file to upload to the WordPress Media Library.",
    )
    alt_text: str = Field(default="", description="Optional alt text for accessibility/SEO")
    title: str = Field(default="", description="Optional media title — defaults to the filename")


# SDL entities. sdl.Entity already provides: id, title, kind, subtitle, description, status, url.
class Site(sdl.Entity):
    username: str = ""
    last_checked: str | None = None
    auth_mode: str = "app_password"  # "app_password" | "ssh" | "both"


class Post(sdl.Entity):
    link: str = ""
    date: str | None = None


class Page(sdl.Entity):
    link: str = ""
    date: str | None = None


class MediaItem(sdl.Entity):
    mime_type: str = ""


class Comment(sdl.Entity):
    author: str = ""
    snippet: str = ""
    post_id: str = ""


class WPUser(sdl.Entity):
    role: str = ""
    registered: str = ""


class Order(sdl.Entity):
    total: str = ""
    currency: str = ""


class ServerInfo(sdl.Entity):
    wp_version: str = ""
    php_version: str = ""
    plugin_updates: int = 0
    plugin_updates_list: list = Field(default_factory=list)
    theme_updates: int = 0
    theme_updates_list: list = Field(default_factory=list)
    core_update: bool = False
    core_update_version: str = ""
    cron_count: int = 0
    db_size_mb: str = ""


class RefreshAllResult(sdl.Entity):
    connected: int = 0
    total: int = 0


class SiteHealth(sdl.Entity):
    reachable: bool = False
    auth_ok: bool = False
    ssl_valid: bool = False
    content_counts: dict = Field(default_factory=dict)
    plugin_updates_available: str = VNEXT
    php_version: str = VNEXT
