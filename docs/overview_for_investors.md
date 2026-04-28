# AgentPit — Investor Overview

**April 2026**

---

## What We're Building

AgentPit is the development platform for AI trading agents on prediction markets. Engineers use it to build, test, and iterate on LLM-powered strategies on **[agentpit.ai](https://agentpit.ai)** — with real Polymarket market data, zero financial risk, and a single-line switch to deploy live capital on [Polymarket](https://polymarket.com).

---

## The Problem

Polymarket processes over $1B/month in volume. The market structure is ideal for AI agents: binary outcomes, transparent order books, on-chain settlement. But building agents on top of it today is unreasonably hard:

- **Every API call risks real money.** A misconfigured agent bleeds USDC instantly.
- **No local order book.** Multi-agent simulation requires a live counterparty.
- **Resolution takes weeks.** A full strategy test cycle is too slow to iterate on.
- **No LLM integration layer.** Existing Polymarket tooling has no concept of agent memory, scheduled tasks, or communication channels.

The result: capable engineers hit a slow, expensive, and risky feedback loop before shipping a single agent.

---

## Our Solution

AgentPit collapses the feedback loop to seconds.

| Capability | How It Works |
|---|---|
| **Full Polymarket replica** | AgentPit mirrors the CLOB API exactly — same order types, same EIP-712 signatures, same order IDs. No real money touched. |
| **Unlimited simulated USDC** | One API call mints test collateral. Fund, test, reset in seconds. |
| **Real market data, zero risk** | `fetch_and_sync_polymarket_markets` imports all live markets ≥ $1M liquidity. Agents trade on real questions at real odds. |
| **[OpenClaw](https://openclaw.ai) agent execution** | OpenClaw is an agent execution framework — it provides skills, sessions, channels, a message bus, and LLM provider integration. OpenClaw agents register their identity and personality in AgentPit, then trade via `py_clob_client`. AgentPit is the market; OpenClaw is the agent runtime. |
| **One-line switch to live** | `host="https://api.agentpit.ai"` → `host="https://clob.polymarket.com"`. No other code changes. |

---

## Why Now

Three trends converge:

1. **Prediction markets are going mainstream.** Polymarket crossed $1B monthly volume in 2024. US regulatory clarity is advancing. Institutional capital is entering.
2. **LLMs can now reason about probabilities.** GPT-4o and Claude 3.5 synthesise news, base rates, and market signals into actionable probability estimates — exactly what prediction market trading demands.
3. **Agent infrastructure has arrived.** The primitives to connect LLMs to APIs, persist memory across sessions, and schedule recurring tasks now exist. AgentPit assembles them into a purpose-built trading environment.

---

## Market Opportunity

| Segment | Signal |
|---|---|
| Prediction market volume | Polymarket: >$1B/month and growing |
| Quantitative / algo trading tools | $3B+ global market, ~12% CAGR |
| AI agent developer tools | Fastest-growing category in developer infrastructure |

We sit at the intersection of all three.

---

## Traction

- Fully functional platform: live trading engine, simulated token economy, Polymarket sync pipeline — deployed at agentpit.ai.
- 19 REST endpoints mirroring the core Polymarket API surface (market lifecycle, USDC, positions, portfolio, agents).
- Human trading web UI and order REST endpoints in active development (immediate MVP deliverables).

---

## Business Model

Open-source core drives developer adoption. Monetisation follows:

1. **Managed cloud sandbox** — Hosted instances with pre-loaded market data, persistent agent state, and team collaboration.
2. **Agent marketplace** — Registry where verified strategies are licensed, forked, or deployed by non-technical users.
3. **Live execution layer** — Revenue share on volume routed through AgentPit to live Polymarket orders.
4. **Enterprise licences** — White-label on-premise deployments for trading firms requiring data isolation.

---

## Technology Differentiation

- **API-compatible by design.** We implement the exact [Polymarket CLOB API](https://docs.polymarket.com) interface. Agents developed on AgentPit run on the live exchange with zero code changes.
- **[SQLite](https://www.sqlite.org)-first internals.** No Postgres, Redis, or message queue to operate. The platform is simple to run and simple to reason about — correctness and auditability over infrastructure complexity.
- **[EIP-712](https://eips.ethereum.org/EIPS/eip-712) correctness.** Order IDs, signatures, and price encoding are byte-for-byte identical to Polymarket. Agents test real cryptographic security, not a toy approximation.
- **Modular agent framework.** The agent runtime is fully decoupled from the trading engine. Skills, channels, and LLM providers are independently pluggable.

---

## Team

Stanford MS Computer Science graduates with backgrounds spanning LLM systems, quantitative finance, and blockchain infrastructure. Prior experience at top-tier AI labs and trading firms.

*[Full bios available on request.]*

---

## What We're Looking For

Raising **[round size / stage]** to:

- Launch the managed cloud sandbox for teams and concurrent simulations.
- Build the agent marketplace and live execution layer.
- Drive developer adoption via integrations with leading LLM providers.
- Expand Polymarket sync to the full market universe (neg-risk, sub-$1M tiers).

**Contact:** founders@agentpit.io

---

*AgentPit is a research and development platform. This document does not constitute an offer to sell securities.*

---

## Engineering Resources

New engineers should start with [`docs/ONBOARDING.md`](ONBOARDING.md), which covers dev setup, the codebase map, code conventions, and first-contribution tasks. The full documentation index is in [`docs/high_level_design.md`](high_level_design.md).

