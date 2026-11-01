# Projects

## Oasis
[Download](https://github.com/VINKAS7/Oasis/archive/refs/heads/main.zip)
[GitHub Repository](https://github.com/VINKAS7/Oasis)
VINKAS7/Oasis

Oasis turns a local business website into tools that ChatGPT, Claude and Gemini can use to find the business, show what it offers and take orders.

People have started asking their AI assistant instead of searching the web. "Where is the nearest pizza?", "Find me a black hoodie in size L", "Book a room near Basel for Friday". The assistant can read a website, but it cannot really use it: it can't open the menu as something you can pick from, it can't place an order, and it often doesn't know the shop exists at all. Small businesses are the ones who lose out, because they don't have the time or money to build an app for every new platform.

Oasis fixes that from the business side. The owner signs up and either gives us their website or builds a small shop directly in Oasis. We read the site, work out what a customer would want to know or do (the menu, prices, opening hours, booking a table), and turn each of those into a tool. Every tool is checked for security and tested against the real site before it goes live. With one click the business gets its own MCP server and also appears in the shared Oasis directory that any assistant can connect to.

On the customer side nothing new has to be installed. You add the Oasis connector to ChatGPT, Claude or Gemini once, and from then on you just ask. The answer comes back as cards inside the chat: places on a live Google map, menus and products with photos and prices, questions you answer with one tap. When you want something, the order goes straight to the owner's inbox and they accept or decline it. There is also a public chat page on the Oasis site for people who don't use an assistant yet.

### Motivation
Shopping and booking are moving into the chat. People no longer open ten tabs to compare a pizza place, a hoodie, or a weekend room. They ask ChatGPT or Claude and take the first answer that feels usable. Big platforms will show up there. A bakery in Kleinbasel or a family shop with a good website will not, unless someone makes their business something an assistant can actually use: find it, show what it sells, and take the order.

Oasis is that layer. Owners keep the site they already have, or open a light shop in Oasis. We turn menus, products, hours and bookings into tools, check them for security, test them against the real site, and publish them. The MCP server does not run on the owner’s laptop or their old hosting. It lives on our platform. That hosted MCP is what ChatGPT, Claude and Gemini connect to, and it is why businesses pay a subscription: continuous uptime, the shared directory, order inbox, versioned tools they can roll back, and a place in the agent conversation without building or running any of that themselves.

We are not asking small shops to rebuild for every new AI app, or to buy ads just to be mentioned. We want the same job Shopify did for the web, make selling simple, but for the agent era: pay once a month, stay discoverable and orderable inside the assistants people already use. That is the “Post-Website Business” we set out to build at BaselHack 2026, and Switzerland’s mix of German, French, Italian and English made the bar clear from day one. If the assistant cannot find the right shop and the right item in the customer’s language, it has failed.

### How it works
**For the owner**
- **Website reading.** A Playwright crawler visits up to 30 pages of the site (respecting robots.txt), and an AI model sorts what it finds into *tools ready* (read only: menu, prices, hours, contact) and a *to-do list* of actions only the owner can show us, like a booking form.
- **Recorder.** For those actions there is a Chrome extension. The owner does the task once on their own site and the recording becomes a tool.
- **Shops without a website.** Four templates (clothing, food menu, services, general shop). Products with photos, prices, sizes, colours and stock per variant.
- **Checks before going live.** Every tool gets a security scan (allowed hosts, personal data, prompt injection in the page text) and a real test run. Only tools that pass are published. Every change is a new version you can roll back.
- **Publishing.** One click gives the business its own MCP server at `/mcp/b/<business_id>` and lists it in the shared directory at `/mcp`. Orders land in an inbox where the owner accepts or declines them.

**For the customer**
- **Search by meaning and by words.** Businesses and items are found with BM25 keyword search plus embeddings (qwen3-embedding on a local Ollama). The keyword side knows synonyms in English, German, French and Italian ("Haarschnitt", "coupe de cheveux" and "taglio" all mean haircut), so search keeps working even if the embedding model is down.
- **No guessing.** If a name could mean two businesses ("Café Central" or "Café Centrale"), the assistant is told it's ambiguous instead of being given the wrong one. Item names typed in any case or with or without accents are matched, and sizes and colours are checked against stock.
- **Cards in the chat (MCP Apps).** Places with an interactive Google map and numbered pins, catalogs with search, filters and a photo viewer, a business card with "open now" and the week's hours, and question cards (yes/no, choices, budget sliders, ratings, dates).
- **The Oasis chat.** A public chat page with its own agent. It repairs bad model answers instead of failing, never claims an order was placed unless a tool really did it, and every order still needs the customer's click on a confirm button.
- **Quality you can see.** The admin panel has a Chat quality page with success rate, AI calls and time per answer, and a step by step trace of every answer.

We test all of this with 118 automated tests and a live evaluation of 29 conversations in four languages. On the last run Oasis found the right business and the right item every time, got every order to the confirm step, and answered in 3.4 seconds (median).

### Technologies Used
- Python, FastAPI, SQLite
- MCP Python SDK with the MCP Apps extension (cards inside ChatGPT, Claude and Gemini Enterprise)
- React, TypeScript, Vite, Tailwind CSS
- better-auth (Node) for accounts and sessions
- Playwright for crawling and for the recorder replays
- Google Maps JavaScript API for the interactive maps
- Ollama with qwen3-embedding for search by meaning
- Any OpenAI compatible or Anthropic model for the AI tasks, chosen per task in the admin panel (we used GLM 5.3 Flash on the KIT AI Toolbox)
- ngrok to give the local server a public address for the assistants

### Setup Instructions
You need Node 22+, Python 3.11+ and [uv](https://docs.astral.sh/uv/).

1. Install everything. This also creates `auth/.env` and `backend/.env` with fresh secrets and downloads Chromium for the crawler.
```
npm install
npm run setup
```
2. Start the auth service, the API and the web app. The app runs at http://localhost:5173 and the customer chat at http://localhost:5173/chat.
```
npm run dev
```
3. Optional: to use Oasis from ChatGPT, Claude or Gemini, put your public ngrok address in `PUBLIC_API_URL` in `backend/.env` and start with the tunnel. Add your Google Maps key as `GOOGLE_MAPS_API_KEY` in the same file for the interactive maps.
```
npm run dev:public
```

After signing up, make yourself admin with `npm --prefix auth run make-admin -- you@example.com`, then add an AI provider under **Admin, AI providers**. The connector address for the assistants is `<PUBLIC_API_URL>/mcp`. More details about the architecture and every part of the system are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

To run the tests:
```
uv --directory backend run pytest -q
```

### Demo/Screenshots
A customer asks for the nearest pizza and then for the menu, all inside a chat.

![Customer chat finding the nearest pizza](docs/screenshots/customer-chat.png)
![The menu shown as cards in the chat](docs/screenshots/customer-chat-menu.png)
![Reviewing an order before sending it](docs/screenshots/customer-chat-order.png)

The same results as cards inside Claude or ChatGPT: places on a live Google map, a business card with today's hours, and questions you answer with a tap.

![Places card with an interactive Google map](docs/screenshots/card-places-map.png)
![Business card with opening hours and map](docs/screenshots/card-business.png)
![Question cards](docs/screenshots/card-questions.png)

For the owner: Oasis reads a real guesthouse website and suggests tools, a shop goes live as its own MCP server, and a restaurant's menu in its workspace.

![What Oasis found on the Pension Rohrbach website](docs/screenshots/workspace-website-analysis.png)
![A shop published as an MCP server](docs/screenshots/shop-mcp-live.png)
![Trattoria Basilico's workspace with its menu](docs/screenshots/workspace-menu.png)

The connect page for assistants and the Chat quality page for admins.

![The Oasis MCP connect page](docs/screenshots/mcp-connect-page.png)
![Chat quality in the admin panel](docs/screenshots/admin-chat-quality.png)

- The customer chat answers in English, French, Italian or German and remembers the language you pick.
- The connect page at `/mcp` shows how to add Oasis to ChatGPT, Claude, Gemini or Claude Code, and has example prompts to try.

### Awards/Achievements
Built at BaselHack 2026 for the Adobe challenge "The Post-Website Business".

### Contributors
Vinayak Kashyap, Sameer Phaniraj Kumble, Tomas Strnadel, Jonas Rohrbach

### Additional Notes
The public address in this repo is a free ngrok domain that only works while one of us has the server running. For real use, Oasis should run on a server with its own domain, and the Google Maps key should be restricted to the Maps JavaScript API.

Next we want to let owners record bookings and orders for more types of sites, add payments for orders, and get Oasis into the official app directories of ChatGPT and Claude so customers can add it without developer mode. Cards don't show in the regular Gemini app yet, so there Oasis answers in plain text.
