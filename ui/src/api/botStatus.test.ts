import { describe, expect, it } from "vitest";
import { botStatusUrl } from "./botStatus";

describe("botStatusUrl", () => {
  it("returns the legacy single-bot path with no agentId", () => {
    expect(botStatusUrl()).toBe("/bot-status.json");
  });

  it("returns the per-agent path for an arena agentId", () => {
    expect(botStatusUrl("bold")).toBe("/bot-status-bold.json");
    expect(botStatusUrl("contrarian")).toBe("/bot-status-contrarian.json");
  });
});
