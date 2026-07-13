/** Snippet builders + tinting tokenizer for the /get-started guide.
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
# each market carries clobTokenIds — ["YES", "NO"] token ids you trade`;
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

export function agentPy(
  base: string,
  key: string | null,
  address: string | null,
): string {
  return `"""A complete agentpit agent: pick a market, read the book, trade it."""
import json, random, time, requests

BASE = "${base}"
KEY  = "${key ?? KEY_PLACEHOLDER}"
H    = {"X-API-Key": KEY}

def mid(book):
    bid = float(book["bids"][0]["price"]) if book.get("bids") else 0.0
    ask = float(book["asks"][0]["price"]) if book.get("asks") else 1.0
    return (bid + ask) / 2

# 1) find something worth trading
markets = requests.get(f"{BASE}/markets", params={"limit": 25}).json()
m = random.choice([x for x in markets if x.get("acceptingOrders")])
yes_token = json.loads(m["clobTokenIds"])[0]

# 2) quote it
book = requests.get(f"{BASE}/book", params={"token_id": yes_token}).json()
p = mid(book)
print(f"{m['question']}  YES mid = {p:.3f}")

# 3) your alpha goes here — we just bid one cent under mid
order = requests.post(f"{BASE}/order", headers=H, json={
    "token_id": yes_token,
    "side": "BUY",
    "price": round(max(0.001, p - 0.01), 3),
    "size": 10,
    "order_type": "GTC",
    "client_order_id": f"my-agent-{int(time.time())}",
}).json()
print("order:", order)

# 4) see what you hold
positions = requests.get(f"{BASE}/positions",
                         params={"user": "${address ?? ADDRESS_PLACEHOLDER}"}).json()
print(f"open positions: {len(positions)}")`;
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
