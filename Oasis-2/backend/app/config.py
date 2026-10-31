"""Paths and environment settings. Everything stateful lives under the repo's database/ folder."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

DATABASE_PATH = (BACKEND_DIR / os.getenv("DATABASE_PATH", "../database/agentready.sqlite")).resolve()
FILES_DIR = DATABASE_PATH.parent / "files"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

AUTH_URL = os.getenv("AUTH_URL", "http://127.0.0.1:3001").rstrip("/")
SECRETS_KEY = os.getenv("SECRETS_KEY", "").strip()
GEOCODER_CONTACT = os.getenv("GEOCODER_CONTACT", "").strip()

# For automated tests of the recorder: run its browser without a window and let a test
# script drive it over the Chrome DevTools Protocol on this port.
RECORDER_HEADLESS = os.getenv("RECORDER_HEADLESS") == "1"
RECORDER_CDP_PORT = os.getenv("RECORDER_CDP_PORT", "").strip()

# Where AI assistants reach this server (shown to owners as their MCP address).
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
# The MCP gateway the customer chat (/chat) uses, like any outside assistant would. Default: this server's own.
CLIENT_MCP_URL = os.getenv("CLIENT_MCP_URL", "").strip().rstrip("/") or f"{PUBLIC_API_URL}/mcp"

USER_AGENT = "AgentReadyBot/0.1 (+https://github.com/agentready)"
