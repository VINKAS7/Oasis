"""Paths and environment settings. Everything stateful lives under the repo's database/ folder."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from mcp.server.transport_security import TransportSecuritySettings

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

DATABASE_PATH = (BACKEND_DIR / os.getenv("DATABASE_PATH", "../database/agentready.sqlite")).resolve()
FILES_DIR = DATABASE_PATH.parent / "files"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

AUTH_URL = os.getenv("AUTH_URL", "http://127.0.0.1:3001").rstrip("/")
SECRETS_KEY = os.getenv("SECRETS_KEY", "").strip()
GEOCODER_CONTACT = os.getenv("GEOCODER_CONTACT", "").strip()
# Countries place names are looked up in first (ISO codes, comma-separated; empty: anywhere).
GEOCODE_COUNTRIES = os.getenv("GEOCODE_COUNTRIES", "ch").strip()
# The businesses' timezone: "open now" and "open at 19:00" are read in it.
TIMEZONE = os.getenv("TIMEZONE", "Europe/Zurich").strip()

# For automated tests of the recorder: run its browser without a window and let a test
# script drive it over the Chrome DevTools Protocol on this port.
RECORDER_HEADLESS = os.getenv("RECORDER_HEADLESS") == "1"
RECORDER_CDP_PORT = os.getenv("RECORDER_CDP_PORT", "").strip()

# Where AI assistants reach this server (shown to owners as their MCP address). Set it to a public
# https address (e.g. an ngrok domain) to add Oasis to ChatGPT or Claude as a connector.
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
# The MCP gateway the customer chat (/chat) uses, like any outside assistant would. Default: this
# server's own, reached directly rather than out through the public address and back.
CLIENT_MCP_URL = os.getenv("CLIENT_MCP_URL", "").strip().rstrip("/") or "http://127.0.0.1:8000/mcp"

# Web apps whose servers connect to MCP connectors (they may send these as Origin).
ASSISTANT_ORIGINS = ["https://chatgpt.com", "https://chat.openai.com", "https://claude.ai"]


def _env_list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


def mcp_security() -> TransportSecuritySettings:
    """Host and Origin checks for the MCP servers (DNS-rebinding protection): localhost, anything in
    MCP_ALLOWED_HOSTS / MCP_ALLOWED_ORIGINS, and the public address with the assistants' apps."""
    hosts = _env_list("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*")
    origins = _env_list("MCP_ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*")
    if is_public():
        public = urlsplit(PUBLIC_API_URL)
        hosts.append(public.netloc)
        origins += [f"{public.scheme}://{public.netloc}", *ASSISTANT_ORIGINS]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


def is_public() -> bool:
    """Whether PUBLIC_API_URL is reachable from outside this computer (ChatGPT, Claude...)."""
    return urlsplit(PUBLIC_API_URL).hostname not in (None, "localhost", "127.0.0.1")

USER_AGENT = "OasisBot/0.1 (+https://github.com/agentready)"
