import { describe, expect, it } from "vitest";
import {
  ADDRESS_PLACEHOLDER,
  agentLoop,
  openclawInstall,
  bookCurl,
  KEY_PLACEHOLDER,
  marketsCurl,
  orderCurl,
  positionsCurl,
  registerCurl,
  tokenizeSnippet,
} from "./getStarted";

const BASE = "http://localhost:8000";

describe("snippet builders", () => {
  it("registerCurl posts email+password to /register", () => {
    const s = registerCurl(BASE);
    expect(s).toContain(`${BASE}/register`);
    expect(s).toContain('"email"');
    expect(s).toContain('"password"');
  });

  it("marketsCurl and bookCurl hit the right endpoints", () => {
    expect(marketsCurl(BASE)).toContain(`${BASE}/markets`);
    expect(bookCurl(BASE)).toContain(`${BASE}/book?token_id=`);
  });

  it("orderCurl interpolates a real key into the X-API-Key header", () => {
    const s = orderCurl(BASE, "pk_live_123");
    expect(s).toContain("X-API-Key: pk_live_123");
    expect(s).toContain(`${BASE}/order`);
    expect(s).toContain('"client_order_id"');
    expect(s).not.toContain(KEY_PLACEHOLDER);
  });

  it("orderCurl falls back to the placeholder without a key", () => {
    expect(orderCurl(BASE, null)).toContain(`X-API-Key: ${KEY_PLACEHOLDER}`);
  });

  it("positionsCurl uses the address (or placeholder) as the user param", () => {
    expect(positionsCurl(BASE, "0xAbC")).toContain("/positions?user=0xAbC");
    expect(positionsCurl(BASE, null)).toContain(
      `/positions?user=${ADDRESS_PLACEHOLDER}`,
    );
  });

  it("agentLoop is wired to the real API surface", () => {
    const s = agentLoop(BASE, "pk_live_123");
    expect(s).toContain(`BASE, KEY = "${BASE}"`);
    expect(s).toContain('"pk_live_123"');
    expect(s).toContain("X-API-Key");
    expect(s).toContain("clobTokenIds");
    expect(s).toContain("/events?limit=1");   // volume-ordered, not /markets
    expect(s).toContain("/order");
  });

  it("agentLoop keeps the model blind to the price", () => {
    // The whole point: a model shown the price re-derives the price.
    const s = agentLoop(BASE, "pk_live_123");
    const prompt = s.slice(s.indexOf("messages=["), s.indexOf("p_model ="));
    expect(prompt).toContain("question");
    expect(prompt).not.toContain("bestBid");
    expect(prompt).not.toContain("bestAsk");
    expect(prompt).not.toContain("edge");
  });

  it("agentLoop uses a placeholder when logged out", () => {
    expect(agentLoop(BASE, null)).toContain(`"${KEY_PLACEHOLDER}"`);
  });

  it("openclawInstall names the public repo and starts in dry run", () => {
    const s = openclawInstall("pk_live_123");
    expect(s).toContain("skalenetwork/agentpit-examples");
    expect(s).toContain("AGENTPIT_DRY_RUN=1");
    expect(s).toContain("pk_live_123");
  });
});

describe("tokenizeSnippet", () => {
  it("classifies a whole # line as one comment token, newline included", () => {
    const t = tokenizeSnippet("a\n# note\nb", []);
    expect(t).toContainEqual({ kind: "comment", value: "# note\n" });
  });

  it("wraps chip occurrences and keeps surrounding text", () => {
    const t = tokenizeSnippet("key=pk_1 end", ["pk_1"]);
    expect(t).toEqual([
      { kind: "text", value: "key=" },
      { kind: "chip", value: "pk_1" },
      { kind: "text", value: " end" },
    ]);
  });

  it("tints same-line quoted spans as strings", () => {
    const t = tokenizeSnippet('say "hi" now', []);
    expect(t).toContainEqual({ kind: "string", value: '"hi"' });
  });

  it("prefers chips over string tinting when a chip sits inside quotes", () => {
    const t = tokenizeSnippet('u = "0xAbC"', ["0xAbC"]);
    expect(t).toContainEqual({ kind: "chip", value: "0xAbC" });
    expect(t.filter((x) => x.kind === "string")).toEqual([]);
  });

  it("is LOSSLESS on every builder output (display == clipboard)", () => {
    const key = "pk_live_123";
    const addr = "0xAbC";
    const snippets = [
      registerCurl(BASE),
      marketsCurl(BASE),
      bookCurl(BASE),
      orderCurl(BASE, key),
      orderCurl(BASE, null),
      positionsCurl(BASE, addr),
      agentLoop(BASE, key),
      agentLoop(BASE, null),
      openclawInstall(key),
    ];
    for (const code of snippets) {
      const glued = tokenizeSnippet(code, [key, addr, KEY_PLACEHOLDER, ADDRESS_PLACEHOLDER])
        .map((t) => t.value)
        .join("");
      expect(glued).toBe(code);
    }
  });
});
