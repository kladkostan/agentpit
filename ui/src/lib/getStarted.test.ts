import { describe, expect, it } from "vitest";
import {
  openclawAddBot,
  openclawInstall,
  openclawSchedule,
  openclawSetKey,
  oneShotScript,
  KEY_PLACEHOLDER,
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

  it("the setup sequence names every piece a fresh machine needs", () => {
    expect(openclawInstall()).toContain("openclaw.ai/install.sh");
    // Piping a remote script into bash — pin the protocol at least.
    expect(openclawInstall()).toContain("--proto '=https'");
    expect(openclawInstall()).toContain("onboard");        // where the model is picked
    expect(openclawAddBot()).toContain("skalenetwork/agentpit-examples");
  });

  it("the key is scoped to the skill and the gateway is restarted", () => {
    const s = openclawSetKey("pk_live_123");
    expect(s).toContain("skills.entries.agentpit-reference.env.AGENTPIT_API_KEY");
    expect(s).toContain("pk_live_123");
    // Read at startup — without this the key silently does nothing.
    expect(s).toContain("daemon restart");
  });

  it("openclawSetKey falls back to the placeholder when logged out", () => {
    expect(openclawSetKey(null)).toContain(KEY_PLACEHOLDER);
  });

  it("the one-shot script does every step the manual path does", () => {
    const s = oneShotScript("pk_live_123");
    expect(s).toContain("openclaw.ai/install.sh");
    expect(s).toContain("skalenetwork/agentpit-examples");
    expect(s).toContain("AGENTPIT_API_KEY");
    expect(s).toContain("pk_live_123");
    expect(s).toContain("daemon restart");
  });

  it("the one-shot script never goes live by itself", () => {
    // A script pasted off a web page must not start placing orders. It ends on
    // a dry run and only PRINTS the lines that make it real.
    const s = oneShotScript("pk_live_123");
    expect(s).toContain("AGENTPIT_DRY_RUN");
    const live = s.indexOf("cron add");
    const printed = s.indexOf("cat <<'NEXT'");
    expect(printed).toBeGreaterThan(-1);
    expect(live).toBeGreaterThan(printed);   // inside the message, not executed
  });

  it("the one-shot script is safe to re-run", () => {
    const s = oneShotScript(null);
    expect(s).toContain("command -v openclaw");   // skips an existing install
    expect(s).toContain("--force");               // re-installing the skill is fine
    expect(s).toContain(KEY_PLACEHOLDER);
  });

  it("the dry run comes before the schedule, and is switched off after", () => {
    const s = openclawSchedule();
    expect(s.indexOf("AGENTPIT_DRY_RUN")).toBeGreaterThan(-1);
    expect(s.indexOf("AGENTPIT_DRY_RUN")).toBeLessThan(s.indexOf("cron add"));
    expect(s).toContain("config unset");   // otherwise it schedules a no-op
  });

  it("the agent run names its target agent", () => {
    // `openclaw agent --message ...` refuses to pick a session for you, even
    // when exactly one agent exists and is marked default:
    //   No target session selected. Use --agent <id>, --session-key <key>, ...
    // `main` is the built-in default agent id (`openclaw agents list --json`
    // reports it with isDefault: true on a stock install).
    for (const snippet of [openclawSchedule(), oneShotScript("pk_live_123")]) {
      expect(snippet).toContain("openclaw agent --agent main --message");
    }
  });

  it("the dry-run value is quoted so the config parser keeps it a string", () => {
    // `openclaw config set` parses the value as JSON before validating it, and
    // a skill's env map is string-to-string. An unquoted 1 arrives as a number
    // and the command fails outright with
    //   Invalid input: expected string, received number
    // which is where the first person to follow this guide got stuck. The
    // reference agent compares `os.environ["AGENTPIT_DRY_RUN"] == "1"`, so no
    // other value works either -- the quotes are the whole fix.
    for (const snippet of [openclawSchedule(), oneShotScript("pk_live_123")]) {
      expect(snippet).toContain(`AGENTPIT_DRY_RUN '"1"'`);
      expect(snippet).not.toMatch(/AGENTPIT_DRY_RUN 1\b/);
    }
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
      openclawInstall(),
      openclawAddBot(),
      openclawSetKey(key),
      openclawSchedule(),
      oneShotScript(key),
    ];
    for (const code of snippets) {
      const glued = tokenizeSnippet(code, [key, addr, KEY_PLACEHOLDER])
        .map((t) => t.value)
        .join("");
      expect(glued).toBe(code);
    }
  });
});
