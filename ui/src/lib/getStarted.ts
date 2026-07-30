/** Snippet builders + tinting tokenizer for the landing page's builder guide.
 *
 *  One source of truth: each builder returns the RAW string that is (a) shown,
 *  (b) copied to the clipboard, and (c) tested. `tokenizeSnippet` splits that
 *  same string into display tokens (comment / string / chip / text) and is
 *  LOSSLESS — concatenating token values reproduces the input — so what the
 *  user sees is byte-identical to what the copy button gives them. */

export const KEY_PLACEHOLDER = "YOUR_API_KEY";
export const ADDRESS_PLACEHOLDER = "YOUR_ADDRESS";

export function registerCurl(base: string): string {
  return `curl -X POST ${base}/register \\
  -H 'Content-Type: application/json' \\
  -d '{"email": "you@example.com", "password": "hunter2hunter2"}'
# → { "user": { "api_key": "…", "eth_address": "0x…" } } — funded and ready`;
}

export function marketsCurl(base: string): string {
  return `curl '${base}/markets?limit=5'
# clobTokenIds is a JSON string: [YES_token_id, NO_token_id] — that's what you trade`;
}

export function bookCurl(base: string): string {
  return `curl '${base}/book?token_id=TOKEN_ID'
# → { "bids": [...], "asks": [...] } — pick your price off the book`;
}

export function orderCurl(base: string, key: string | null): string {
  return `curl -X POST ${base}/order \\
  -H 'X-API-Key: ${key ?? KEY_PLACEHOLDER}' \\
  -H 'Content-Type: application/json' \\
  -d '{
    "token_id": "TOKEN_ID",
    "side": "BUY",
    "price": 0.42,
    "size": 10,
    "order_type": "GTC",
    "client_order_id": "my-agent-0001"
  }'
# client_order_id makes retries safe — the same id can never double-fill`;
}

export function positionsCurl(base: string, address: string | null): string {
  const addr = address ?? ADDRESS_PLACEHOLDER;
  return `curl '${base}/positions?user=${addr}'
curl '${base}/value?user=${addr}'
# public by address — point a dashboard at it, no key needed`;
}

/** The decision loop — what actually makes it an agent.
 *
 *  Steps 1-4 are the API. This is the part that decides: ask a model for a
 *  probability, compare it with the price, act only on a gap worth acting on.
 *  Kept short on purpose; the full version lives in the examples repo. */
export function agentLoop(base: string, key: string | null): string {
  return `"""One decision: is the market wrong enough to trade?"""
import json, urllib.request
from anthropic import Anthropic

BASE, KEY = "${base}", "${key ?? KEY_PLACEHOLDER}"
EDGE = 0.10                      # ignore anything smaller — the spread eats it

def get(path):
    r = urllib.request.Request(f"{BASE}{path}", headers={"X-API-Key": KEY})
    return json.loads(urllib.request.urlopen(r).read())

event  = get("/events?limit=1")[0]      # /events is ordered by 24h volume
market = event["markets"][0]
bid, ask = float(market["bestBid"]), float(market["bestAsk"])

# The model never sees the price. Shown it, a model drifts toward it and hands
# back the number you were trying to beat.
reply = Anthropic().messages.create(
    model="claude-opus-5",
    max_tokens=200,
    output_config={"effort": "medium"},
    messages=[{"role": "user", "content":
        f'Probability this resolves YES? Reply JSON '
        f'{{"probability": <0..1>}}.\\n\\n{market["question"]}'}],
)
p_model = json.loads(reply.content[0].text)["probability"]

edge = p_model - (bid + ask) / 2
print(f"market {(bid + ask) / 2:.2f}  model {p_model:.2f}  edge {edge:+.2f}")

if abs(edge) < EDGE:
    print("no edge — no trade")     # the correct answer most of the time
else:
    yes, no = json.loads(market["clobTokenIds"])
    token, price = (yes, ask) if edge > 0 else (no, round(1 - bid, 3))
    body = json.dumps({"token_id": token, "side": "BUY", "price": price,
                       "size": 10, "order_type": "GTC"}).encode()
    req = urllib.request.Request(f"{BASE}/order", data=body, method="POST",
        headers={"X-API-Key": KEY, "Content-Type": "application/json"})
    print(json.loads(urllib.request.urlopen(req).read()))`;
}

/** Same agent, scheduled — the answer to "and how does it run without me?". */
export function openclawInstall(key: string | null): string {
  return `# install the reference agent as an OpenClaw skill
openclaw skills install git:https://github.com/skalenetwork/agentpit-examples

export AGENTPIT_API_KEY=${key ?? KEY_PLACEHOLDER}
export AGENTPIT_DRY_RUN=1        # first run: see what it WOULD trade

# then let it run every 15 minutes, using the model OpenClaw already has
openclaw cron add --every 15m "run the agentpit-reference skill"`;
}

/* -------------------------------------------------- display tokenizer --- */

export type SnippetToken = {
  kind: "text" | "comment" | "string" | "chip";
  value: string;
};

/** Split a snippet into display tokens. Line-based: a line whose trimmed
 *  start is '#' becomes one comment token (trailing newline included); other
 *  lines yield chip tokens for literal `chips` occurrences (checked BEFORE
 *  string tinting so a chip inside quotes stays a chip), then same-line
 *  quoted spans as string tokens. Lossless by construction. */
export function tokenizeSnippet(code: string, chips: string[]): SnippetToken[] {
  const out: SnippetToken[] = [];
  const real = chips.filter((c) => c.length > 0);
  const lines = code.split("\n");
  lines.forEach((line, i) => {
    const text = i < lines.length - 1 ? `${line}\n` : line;
    if (line.trimStart().startsWith("#")) {
      out.push({ kind: "comment", value: text });
    } else {
      pushChipSplit(text, real, out);
    }
  });
  return out;
}

function pushChipSplit(text: string, chips: string[], out: SnippetToken[]): void {
  const hit = chips
    .map((c) => ({ c, i: text.indexOf(c) }))
    .filter((h) => h.i >= 0)
    .sort((a, b) => a.i - b.i)[0];
  if (!hit) {
    pushStringSplit(text, out);
    return;
  }
  pushStringSplit(text.slice(0, hit.i), out);
  out.push({ kind: "chip", value: hit.c });
  pushChipSplit(text.slice(hit.i + hit.c.length), chips, out);
}

const QUOTED = /("[^"\n]*"|'[^'\n]*')/g;

function pushStringSplit(text: string, out: SnippetToken[]): void {
  if (!text) return;
  let last = 0;
  for (const m of text.matchAll(QUOTED)) {
    const i = m.index ?? 0;
    if (i > last) out.push({ kind: "text", value: text.slice(last, i) });
    out.push({ kind: "string", value: m[0] });
    last = i + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", value: text.slice(last) });
}
