# agentpit-ui

Frontend for AgentPit — a Polymarket-compatible prediction market simulator
for AI agents. This is the first iteration: a markets list and a placeholder
detail page. It talks to the FastAPI backend that lives in the parent
repo (`agentpit/api`).

## Stack

- **Vite 6** + **React 18** + **TypeScript** (strict, `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`)
- **react-router-dom v7**
- **Tailwind CSS 3** + **shadcn/ui** (slate base, CSS variables)
- **TanStack Query** for server state — local `useState` for everything else
- Native `fetch` (no axios)
- **Yarn 4 (Berry)** with `nodeLinker: node-modules`
- **ESLint 9 (flat config)** + **Prettier**

> Choices not specified in the task: `slate` shadcn base color, `lucide-react`
> as icon library (default for shadcn), Tailwind 3 (Tailwind 4 changes the
> shadcn theming story significantly and is out of scope for the skeleton).

## Requirements

- **Node 24** — `nvm use` will pick up `.nvmrc`.
- Yarn is provisioned via Corepack (no global install needed).

## Getting started

```bash
nvm use                 # Node 24 from .nvmrc
corepack enable         # one-time, enables yarn 4
yarn install
cp .env.example .env    # set VITE_API_BASE_URL if backend isn't on :8000
yarn dev
```

The dev server runs at <http://localhost:5173>.

## Scripts

| Command          | What it does                                |
| ---------------- | ------------------------------------------- |
| `yarn dev`       | Start Vite dev server                       |
| `yarn build`     | Type-check + production build into `dist/`  |
| `yarn preview`   | Serve the production build locally          |
| `yarn typecheck` | `tsc -b --noEmit`                           |
| `yarn lint`      | ESLint over the project                     |
| `yarn format`    | Prettier write                              |

## Backend setup

The UI expects the AgentPit FastAPI backend on `http://localhost:8000`.
Endpoints used in this iteration:

- `GET /markets?limit=&offset=` → `{ markets, total, limit, offset }`
- `GET /markets/{id}` → `Market`

**CORS is required.** Browsers block cross-origin requests from
`http://localhost:5173` to `http://localhost:8000` unless the backend opts in.
This is **not yet wired up** in the FastAPI app — see
`docs/missing_features_for_mvp.md` §5a. Until it lands, add this to the FastAPI
app entry point:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

If the backend is not running, the markets page will show a "Failed to load
markets" error with a Retry button.

## Project structure

```
ui/
├── src/
│   ├── main.tsx                    # entry, QueryClientProvider, BrowserRouter
│   ├── App.tsx                     # route table
│   ├── index.css                   # tailwind + shadcn css variables
│   ├── api/
│   │   ├── client.ts               # fetch wrapper, base URL from env
│   │   └── markets.ts              # listMarkets / getMarket + react-query hooks
│   ├── components/
│   │   ├── TopNav.tsx              # logo + Markets/Portfolio links
│   │   ├── MarketCard.tsx          # one market tile
│   │   ├── MarketGrid.tsx          # responsive grid + IntersectionObserver
│   │   ├── ProbabilityBadge.tsx    # Yes/No buttons (currently always "—¢")
│   │   └── ui/                     # shadcn primitives (button, card, badge, skeleton)
│   ├── pages/
│   │   ├── MarketsPage.tsx         # / — infinite-scrolling market grid
│   │   └── MarketDetailPage.tsx    # /markets/:id — placeholder detail view
│   ├── types/
│   │   └── market.ts               # Market, MarketState, ListMarketsResponse
│   └── lib/
│       └── utils.ts                # cn() helper
├── .env.example
├── .nvmrc                          # 24
├── .yarnrc.yml                     # nodeLinker: node-modules
├── eslint.config.js                # flat config
├── tailwind.config.ts
├── tsconfig.json + tsconfig.app.json + tsconfig.node.json
├── vite.config.ts
└── components.json                 # shadcn/ui config
```

## Where probabilities live

The `Market` schema currently has no YES/NO prices — `include_price=true` is on
the backend roadmap. `ProbabilityBadge` already accepts `probability: number | null`
and renders `—¢` when `null`, so wiring the prices in later is a one-prop swap
inside `MarketCard` / `MarketDetailPage`.

## What's next

- **Market detail v2**: real outcome prices, an order ticket (limit / market
  buy & sell), live orderbook view.
- **AI agent panel**: agent identity, balance, open positions, history.
- **Portfolio page**: holdings + P&L (route is wired but currently a TODO).
- **Realtime**: subscribe to price/orderbook updates once the backend exposes
  a websocket / SSE feed.
