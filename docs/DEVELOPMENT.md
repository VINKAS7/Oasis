# Oasis

Turns any business website into tools AI assistants can use: local shops, salons, practices, studios, tradespeople, restaurants, hotels, schools, agencies, and online businesses (BaselHack 2026, Adobe "The Post-Website Business"). The full design is in `Oasis Platform Architecture (BaselHack 2026).md`.

**Built so far:** sign-up and login, workspaces, the website crawler with AI analysis (Part B), the Chrome extension recorder (Part C), the tool registry with versions and safe merge (Part D), security checks and test runs with badges (Part E), the MCP gateway (Part F), and an admin panel that controls which AI provider, model and API key every AI request uses.

## Run it

You need Node 22+, [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
npm install
npm run setup     # creates auth/.env + backend/.env with fresh secrets, installs everything, downloads Chromium
npm run dev       # auth :3001, API :8000, UI http://localhost:5173
```

**The recorder extension.** Owners record bookings in their own Chrome with the extension in `extension/`. In the web app, open **Recorder extension** in the sidebar to download it, then go to `chrome://extensions`, turn on Developer mode, and choose **Load unpacked** on the unzipped folder. Its **Log in** button opens the website's `/extension/connect` page, which hands it the signed-in session. The extension talks to `http://localhost:5173` by default; change this under its Settings.

**Connecting an AI assistant.** The MCP gateway is at `http://localhost:8000/mcp` (streamable HTTP). For Claude Desktop on the same computer, add `{"mcpServers": {"agentready": {"command": "npx", "args": ["-y", "mcp-remote", "http://localhost:8000/mcp"]}}}` to `claude_desktop_config.json`. On a public server, set `PUBLIC_API_URL` and `MCP_ALLOWED_HOSTS` in `backend/.env` and add the URL as a custom connector.

**Each business's own MCP server.** When an owner's tools have passed their checks, **Publish MCP server** (in the workspace, under *MCP server*) lists the business in the directory and customer chat and turns on its own server at `http://localhost:8000/mcp/b/<business_id>`. That server exposes the business's tools directly (`get_menu`, `get_projects`, … plus `about_business`), with the same checks, owner rules, confirmation and signing as the shared gateway. Admins see every server, its owner and its tools under **Admin → MCP servers**. Pages that only fill in their content with JavaScript (React or Vue sites, for example) are rendered in a headless browser when tools read them.

**Menus, products and orders.** When the crawl finds a list of things customers choose or buy (a menu, a product grid, services, rooms...) or that a site shows off (projects, skills, experience), the analysis turns it into a `get_<kind>` tool of kind `item_list`. It reads the items as data (name, description, price, picture, link) and never copies the site's HTML. The list can be repeated cards or rows in any markup, schema.org JSON-LD, or a JavaScript-rendered page (`backend/app/catalog.py`). The customer chat shows the items as picture cards. If the owner switches on **Take orders through Oasis** (workspace → *Orders*), customers pick quantities, review and send an order. It lands in the owner's order inbox, where they accept or decline it, and the chat shows the answer. Prices always come from the business's own catalog. Any assistant can order too, with the `request_order` and `get_order_status` tools on the gateway or the business's own MCP server.

**The customer chat.** `http://localhost:5173/chat` is a public, ChatGPT-style page for customers (no login; rate-limited per visitor by *AI requests per minute*). Ask "What's the nearest restaurant?" and it answers through the MCP gateway, like any outside assistant: `find_nearby`, then the business's own tools. It uses the AI that the admin routes to the **Customer chat** task. Bookings and orders never go through on the model's say-so: the page shows a Confirm button, and only that click sends `user_confirmed=true`. Share your location from the pill at the top right, or type a place. Only published (live) businesses show up. Set `CLIENT_MCP_URL` in `backend/.env` to point it at another gateway.

**Becoming admin.** Put your email in `ADMIN_EMAILS` in `auth/.env` before you sign up. Or sign up first, then run `npm --prefix auth run make-admin -- you@example.com` and sign in again.

**First steps as admin:**

1. Go to **Admin → AI providers** and add one. The first one becomes the default for every task.
2. To crawl a site on `localhost` (the demo restaurant), go to **Admin → Crawler** and turn on *Allow local and private network addresses*.

## Any business, any website

`backend/app/categories.py` lists the kinds of business: shop, beauty, health, fitness, home services, professional services, education, activities, events, rentals, restaurant, café, bar, hotel, hostel, online, and other. Each says which read-only tools a customer's assistant will expect (prices, services, schedule...) and which actions the owner will probably record (an appointment, an order, a quote request...). The crawl analysis uses these only as a starting point. Owners can also describe the business in their own words ("bike repair shop"), and assistants match on those words too.

A business can be **online only**: it needs no address, map or opening hours, it gets a `get_contact` tool instead of `get_location_and_contact`, and it is found through `search_businesses` rather than `find_nearby`. Sensitive tools wait for `user_confirmed=true`, whatever the action is.

## How it fits together

```
browser ──/api/auth/*──▶ auth/      Node + better-auth (email/password, admin plugin)
        └─/api/*───────▶ backend/   FastAPI: workspaces, crawler, AI gateway, admin API
                           both use database/agentready.sqlite
```

- **Users.** better-auth owns the `user`, `session`, `account` and `verification` tables. Each user gets a unique id like `usr_…`. The API checks every request by asking the auth service who the cookie belongs to (`backend/app/auth.py`).
- **Workspaces.** One per business, with an id like `biz_rheinblick_01`. Saving a workspace with a website starts a crawl.
- **Crawler** (`backend/app/crawler/`). Playwright visits up to 30 same-site pages. For each page it stores the text, headings, forms, buttons, JSON-LD and a screenshot (screenshots go in `database/files/`). It respects robots.txt and blocks private network addresses unless the admin allows them.
- **AI analysis** (`crawler/analyze.py`):
  - The AI reads each page and sorts what it finds into *information* and *actions*.
  - A second call proposes **Tools ready** (read-only), **To-do** (flows the owner must record) and **Missing** items.
  - The platform code, not the AI, makes the final call: anything that books, orders or pays always goes to To-do. Hours and contact details the owner entered become tools.
  - Page text is treated as untrusted. Text aimed at AI assistants is flagged as possible prompt injection.
- **AI gateway** (`backend/app/ai/`). Every AI call goes through `gateway.run(task, …)`:
  - It looks up the admin's route for that task, falling back to the default route.
  - It decrypts the key, calls the provider and logs the call to `ai_calls`.
  - Supported providers: Anthropic (official SDK), OpenAI, and any OpenAI-compatible endpoint (Gemini, OpenRouter, Groq, Ollama…).
  - API keys are stored Fernet-encrypted with `SECRETS_KEY` and are never sent to the browser.
  - The app reaches AI only through `POST /api/ai/complete` (task `assistant`), which is rate-limited per user.
- **Chrome extension recorder** (`extension/`, Manifest V3, Part C). The owner records in their own Chrome tab.
  - `content.js` reports clicks, typing and submits, and shows the step panel.
  - `background.js` captures network requests through Chrome's debugging interface. It pauses write requests (Fetch domain) so their answer is kept even when the page navigates away. It starts a new step on every page change and takes a screenshot per step, with the panel hidden and personal fields covered.
  - `clean.js` masks everything in the browser, before upload.
  - On Finish it uploads to `POST /api/workspaces/{id}/recordings/upload` (with a bearer token from better-auth's `bearer` plugin); the server cleans it again. The owner continues in the web app.
  - The extension gets its token from the website's `/extension/connect` page, through `window.postMessage` and its content script. It accepts tokens only from the Oasis address set in its settings.
- **Server-side recorder** (`backend/app/recorder/`). The older recorder opens a browser window on the API computer; it is off by default (Admin → Platform settings). Its cleaning, comparison and storage are shared with the extension:
  - `capture.js` reports clicks, typing, choices and submits from every frame. It also shows the owner a panel to write one sentence per step and press Finish.
  - A new step starts whenever the page changes. Network requests and step screenshots are captured along the way.
  - `clean.py` masks passwords, tokens and personal details as they arrive: in values, request and response bodies, URLs and notes, with grey boxes over personal fields in screenshots. Images, fonts and trackers are dropped.
  - Each recording is one JSON file in `database/files/<business>/recordings/<id>/`, downloadable and re-uploadable (uploads are cleaned again).
  - **Record twice:** `compare.py` diffs two recordings of a flow. What changes becomes an input (date, people, name…), what stays the same is fixed, and it points at the request that most likely made the booking.
  - Admins can switch live recording off on a shared server; uploads still work.
- **Tool registry** (`backend/app/registry/`, Part D). Tools and every version of them live in `tools` and `tool_versions`.
  - A tool is a declarative runner, not code: `http_request` (send the recorded request with the guest's values), `browser_replay` (replay the recorded steps), `page_extract` (read a page) or `owner_data` (answer from the workspace).
  - **Proposals.** Changes always arrive as a proposal of *add / update / no change* per tool, with a reason. From a recording, the admin-chosen AI writes it (task `tool_proposal`), given the recording, its record-twice comparison and the current tools (read-only). Without a working AI provider, the platform drafts it from the comparison. From a crawl, the read-only tools the analysis found become a proposal directly.
  - **Rulebook** (`rules.py`). The platform, not the AI, decides:
    - The AI cannot delete a tool.
    - Same name or same job means a clash the owner resolves (keep separate or make it a new version).
    - Placeholders must be declared inputs, and masked personal values can never be literals.
    - Data may only go to addresses seen in the recording.
    - Sensitivity can only be raised.
  - **Versions** (`store.py`). A new tool is v1 and in use. An update is a new version that waits for the checks (Part E) while the old one stays in use, unless the owner switches. Every version is kept, and rollback is one click.
- **Checks and badges** (`backend/app/checks/`, `backend/app/runner/`, Part E). Every new version is checked straight away, and every tool in use is re-checked daily, by one background worker.
  - **Security** (`security.py`): right address only (the site, its test copy, hosts from the recording); no dangerous powers (known runner kinds, http(s) only); no secrets or guest details written into the tool; inputs match. It also sets the sensitivity label and a calls-per-minute limit. Any failure means **blocked**.
  - **Test run** (`pipeline.py`, using the runner in `runner/engine.py`). The runner executes the declarative spec inside a network allow-list. Read-only tools run for real. Booking tools run against the workspace's *test copy of the booking system* if set, or book and cancel straight away with the business's `cancel_…` tool, or make one real booking when the owner asks ("Run a real test"). Otherwise they get a dry run that sends nothing, which earns **Needs a test run**, never a pass. Daily checks never book for real.
  - **Prompt-injection scan** (`injection.py`) of whatever the tool returns: pattern rules plus the admin-chosen AI (task `safety_scan`).
  - **Badges:** Safe and working · Sensitive · Not working (with "Please re-record step N") · Blocked · Needs a test run. Blocked and broken tools raise alerts for the owner and the admins.
  - A newer approved version replaces the one in use only once it passes with a real test.
- **MCP gateway** (`backend/app/gateway/`, Part F, official MCP Python SDK v2 `MCPServer`, mounted at `/mcp`):
  - `find_nearby` searches live businesses with a place by distance, kind (a category or plain words like "barber"), opening time and keywords; `search_businesses` finds any live business, local or online, by what it offers. The location is used for one search and never stored. Keywords a nearby business doesn't offer are counted as **demand you missed**.
  - `get_business_info` and `list_business_tools` describe one business.
  - `call_business_tool` runs a tool through the same runner as the checks. It only allows published tools (enabled, passed with a real test, business live). It applies the owner's rules (`owner_rules`, e.g. people at most 8) and makes sensitive tools wait for `user_confirmed=true`. It enforces the per-tool limit, logs to `calls_log` with personal values masked, and signs the answer with the business's Ed25519 key (`signing.py`, valid 15 minutes).
  - Owners **Go live** on the workspace page and see the gateway address, published tools, agent activity and missed demand.
- **Look.** The web app is Notion-like: a sidebar with workspaces and admin pages, breadcrumbs, large page titles, property lists, callouts.
- **Admin panel** (`/admin`). Admins only: the UI hides it and the API returns 403 to everyone else. It covers:
  - AI providers and keys, with a connection test
  - Task routing: provider, model, effort and max tokens per task
  - Platform settings: crawler, recorder and AI
  - Users: make admin, ban (through better-auth's admin plugin)
  - All workspaces
  - The AI usage log

## Next

The P0 chain from the architecture doc runs end to end: workspace → crawl → read-only tools → recorded booking → `book_table` → checks and badges → gateway → an assistant finds and books → the booking is in the restaurant's system. Next from P1: a test chat for the owner, and a second business so `find_nearby` returns a real choice.

## Testing the recorder without a window

`RECORDER_HEADLESS=1` runs the recording browser without a window, and `RECORDER_CDP_PORT=9339` lets a test script drive it with Playwright's `connect_over_cdp`. Both are for automated tests only.
