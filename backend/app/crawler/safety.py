"""URL rules for the crawler: http(s) only, same site only, and no private networks unless the
admin allows them (the crawler runs on our server, so an owner's URL must not reach our LAN)."""

import ipaddress
import socket
from urllib.parse import urldefrag, urlsplit, urlunsplit

SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif",
    ".mp4", ".mov", ".webm", ".mp3", ".wav", ".ogg",
    ".zip", ".rar", ".gz", ".7z", ".dmg", ".exe",
    ".css", ".js", ".json", ".xml", ".rss", ".woff", ".woff2", ".ttf",
}
# Linked files worth telling the owner about (a PDF menu, say), but not crawled as pages.
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".ics", ".csv", ".txt"}


class UnsafeURL(ValueError):
    pass


def normalize(url: str) -> str:
    url = urldefrag(url.strip())[0]
    parts = urlsplit(url)
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def site_key(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, root: str) -> bool:
    return site_key(url) == site_key(root)


def extension(url: str) -> str:
    path = urlsplit(url).path.lower()
    name = path.rsplit("/", 1)[-1]
    return name[name.rfind(".") :] if "." in name else ""


def _is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


def check(url: str, allow_private: bool) -> str:
    """Return the normalised URL or raise UnsafeURL."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("Only http:// and https:// addresses can be crawled")
    if not parts.hostname:
        raise UnsafeURL("The address has no host name")
    if parts.username or parts.password:
        raise UnsafeURL("Addresses with a user name or password are not allowed")
    if not allow_private:
        try:
            infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        except socket.gaierror as exc:
            raise UnsafeURL(f"Could not find the host {parts.hostname}") from exc
        for info in infos:
            if _is_private(ipaddress.ip_address(info[4][0])):
                raise UnsafeURL(
                    f"{parts.hostname} points to a private or local network address. "
                    "An admin can allow this under Admin → Crawler (for a local demo site)."
                )
    return normalize(url)
