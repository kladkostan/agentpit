import { describe, expect, it } from "vitest";
import {
  DEFAULT_IDENTITY,
  equityPoints,
  lastTrade,
  rankAgents,
  resolveAgentIdentity,
  TIME_WINDOWS,
  windowAgent,
  type LeaderboardAgent,
  type LeaderboardData,
} from "./leaderboard";
import type { BotFeedItem } from "./botStatus";

function agent(over: Partial<LeaderboardAgent>): LeaderboardAgent {
  return {
    id: "x",
    name: "X",
    emoji: "❓",
    style: "",
    address: "0xX",
    realized_pnl: 0,
    unrealized_pnl: 0,
    trades: 0,
    open_positions: 0,
    equity: [{ t: 0, p: 0 }],
    total_pnl: 0,
    ...over,
  };
}

function feedItem(over: Partial<BotFeedItem>): BotFeedItem {
  return {
    ts: 0,
    cycle_id: "c",
    decision_id: "d-0",
    title: "Q?",
    direction: "UP",
    recent_move: 0,
    rationale: "",
    edge_source: "model",
    outcome: "traded",
    traded: true,
    demo: false,
    side: "BUY",
    price: 0.5,
    size: 10,
    ...over,
  };
}

describe("lastTrade", () => {
  it("returns null for an empty feed", () => {
    expect(lastTrade([])).toBeNull();
  });

  it("returns null when no item actually traded", () => {
    expect(
      lastTrade([feedItem({ traded: false, outcome: "no_trade" })]),
    ).toBeNull();
  });

  it("picks the newest traded item even from an unsorted feed, skipping non-trades", () => {
    const older = feedItem({ ts: 100, decision_id: "d-1" });
    const newest = feedItem({ ts: 300, decision_id: "d-2" });
    const heldLater = feedItem({
      ts: 400,
      decision_id: "d-3",
      traded: false,
      outcome: "no_trade",
    });
    expect(lastTrade([older, heldLater, newest])).toEqual(newest);
  });

  it("breaks equal timestamps by decision_id", () => {
    const a = feedItem({ ts: 100, decision_id: "d-1" });
    const b = feedItem({ ts: 100, decision_id: "d-9" });
    expect(lastTrade([a, b])).toEqual(b);
  });
});

describe("rankAgents", () => {
  it("orders by total_pnl descending and medals the top three", () => {
    const ranked = rankAgents([
      agent({ id: "a", name: "A", total_pnl: -10 }),
      agent({ id: "b", name: "B", total_pnl: 50 }),
      agent({ id: "c", name: "C", total_pnl: 5 }),
      agent({ id: "d", name: "D", total_pnl: -100 }),
    ]);
    expect(ranked.map((r) => r.id)).toEqual(["b", "c", "a", "d"]);
    expect(ranked.map((r) => r.rank)).toEqual([1, 2, 3, 4]);
    expect(ranked.map((r) => r.medal)).toEqual(["🥇", "🥈", "🥉", null]);
  });

  it("breaks ties by trades desc then name asc (stable at $0)", () => {
    const ranked = rankAgents([
      agent({ id: "z", name: "Zed", total_pnl: 0, trades: 2 }),
      agent({ id: "a", name: "Ann", total_pnl: 0, trades: 2 }),
      agent({ id: "m", name: "Moe", total_pnl: 0, trades: 9 }),
    ]);
    expect(ranked.map((r) => r.id)).toEqual(["m", "a", "z"]);
  });

  it("does not mutate the input array", () => {
    const input = [
      agent({ id: "a", total_pnl: 1 }),
      agent({ id: "b", total_pnl: 2 }),
    ];
    const snapshot = [...input];
    rankAgents(input);
    expect(input).toEqual(snapshot);
  });
});

describe("resolveAgentIdentity", () => {
  const data: LeaderboardData = {
    updated_at: 1,
    cycle_interval_minutes: 15,
    agents: [
      agent({
        id: "bold",
        name: "Bold",
        emoji: "🔥",
        style: "aggressive",
        address: "0xBold",
      }),
    ],
  };

  it("returns the single-bot default when no agentId is given", () => {
    const r = resolveAgentIdentity(data, undefined);
    expect(r.status).toBe("default");
    expect(r.identity).toEqual(DEFAULT_IDENTITY);
  });

  it("returns loading (null identity) while the leaderboard is undefined", () => {
    const r = resolveAgentIdentity(undefined, "bold");
    expect(r.status).toBe("loading");
    expect(r.identity).toBeNull();
  });

  it("resolves a matching agent's arena identity", () => {
    const r = resolveAgentIdentity(data, "bold");
    expect(r.status).toBe("resolved");
    expect(r.identity).toEqual({
      address: "0xBold",
      name: "Bold",
      emoji: "🔥",
      style: "aggressive",
      isArena: true,
    });
  });

  it("reports not-found for an unknown id in a loaded leaderboard", () => {
    const r = resolveAgentIdentity(data, "ghost");
    expect(r.status).toBe("not-found");
    expect(r.identity).toBeNull();
  });
});

describe("equityPoints", () => {
  it("passes through a curve that already has two or more points", () => {
    expect(
      equityPoints([
        { t: 0, p: 0 },
        { t: 5, p: 3 },
      ]),
    ).toEqual([
      { t: 0, p: 0 },
      { t: 5, p: 3 },
    ]);
  });

  it("pads a single point to a flat two-point line at its value", () => {
    expect(equityPoints([{ t: 0, p: 4 }])).toEqual([
      { t: 0, p: 4 },
      { t: 1, p: 4 },
    ]);
  });

  it("pads an empty curve to a flat zero line", () => {
    expect(equityPoints([])).toEqual([
      { t: 0, p: 0 },
      { t: 1, p: 0 },
    ]);
  });
});

describe("TIME_WINDOWS", () => {
  it("offers 24h/7d/30d/all with correct lengths", () => {
    expect(TIME_WINDOWS.map((w) => w.key)).toEqual(["24h", "7d", "30d", "all"]);
    expect(TIME_WINDOWS.map((w) => w.seconds)).toEqual([
      86_400, 604_800, 2_592_000, null,
    ]);
  });
});

describe("windowAgent", () => {
  const base = agent({
    realized_pnl: -20,
    unrealized_pnl: -5,
    trades: 3,
    total_pnl: -25,
    equity: [
      { t: 0, p: 0 },
      { t: 1000, p: -8 },
      { t: 2000, p: -12 },
      { t: 3000, p: -20 },
    ],
  });

  it("returns the same agent object for All time (null start)", () => {
    expect(windowAgent(base, null)).toBe(base);
  });

  it("re-scopes realized, total, trades, and equity to the window", () => {
    const w = windowAgent(base, 1500);
    expect(w.realized_pnl).toBe(-12); // -20 now minus -8 at window start
    expect(w.total_pnl).toBe(-17); // window realized + unrealized -5
    expect(w.trades).toBe(2); // closes at t=2000 and t=3000
    expect(w.equity).toEqual([
      { t: 1500, p: 0 },
      { t: 2000, p: -4 },
      { t: 3000, p: -12 },
    ]);
  });

  it("treats a close exactly at the boundary as before the window", () => {
    const w = windowAgent(base, 2000);
    expect(w.trades).toBe(1); // only t=3000
    expect(w.realized_pnl).toBe(-8); // -20 minus -12
    expect(w.equity).toEqual([
      { t: 2000, p: 0 },
      { t: 3000, p: -8 },
    ]);
  });

  it("keeps unrealized P&L in every window", () => {
    const w = windowAgent(base, 999_999); // window starts after all closes
    expect(w.realized_pnl).toBe(0);
    expect(w.total_pnl).toBe(-5);
    expect(w.trades).toBe(0);
    expect(w.equity).toEqual([{ t: 999_999, p: 0 }]);
  });

  it("handles a fresh agent that only has the zero anchor", () => {
    const fresh = agent({ equity: [{ t: 0, p: 0 }] });
    const w = windowAgent(fresh, 500);
    expect(w.realized_pnl).toBe(0);
    expect(w.total_pnl).toBe(0);
    expect(w.trades).toBe(0);
    expect(w.equity).toEqual([{ t: 500, p: 0 }]);
  });

  it("handles an empty equity series", () => {
    const empty = agent({ equity: [], unrealized_pnl: 2 });
    const w = windowAgent(empty, 500);
    expect(w.realized_pnl).toBe(0);
    expect(w.total_pnl).toBe(2);
    expect(w.trades).toBe(0);
    expect(w.equity).toEqual([{ t: 500, p: 0 }]);
  });

  it("does not mutate the input agent", () => {
    const snapshot = JSON.parse(JSON.stringify(base));
    windowAgent(base, 1500);
    expect(base).toEqual(snapshot);
  });
});
