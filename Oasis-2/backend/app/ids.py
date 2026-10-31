"""Readable unique ids: biz_rheinblick_01, aip_k3x9..."""

import re
import secrets
import sqlite3
import unicodedata

# Words that say what kind of place it is rather than which one.
_GENERIC = {
    "restaurant", "hotel", "hostel", "cafe", "bar", "shop", "store", "salon", "studio", "spa", "clinic", "practice",
    "gmbh", "ag", "sa", "sarl", "ltd", "llc", "inc", "co", "the", "and", "das", "der", "die", "le", "la", "les",
}


def slugify(name: str, max_len: int = 20) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", ascii_name)
    specific = [w for w in words if w not in _GENERIC] or words or ["business"]
    return "_".join(specific)[:max_len].strip("_") or "business"


def new_business_id(conn: sqlite3.Connection, name: str) -> str:
    slug = slugify(name)
    taken = {r[0] for r in conn.execute("SELECT id FROM businesses WHERE id LIKE ?", (f"biz_{slug}_%",))}
    n = 1
    while f"biz_{slug}_{n:02d}" in taken:
        n += 1
    return f"biz_{slug}_{n:02d}"


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"
