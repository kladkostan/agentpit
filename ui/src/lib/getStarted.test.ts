import { describe, expect, it } from "vitest";
import {
  commandsOnly,
  openclawAddBot,
  openclawDryRun,
  openclawGoLive,
  openclawInstall,
  openclawSetKey,
  oneShotScript,
  KEY_PLACEHOLDER,
  tokenizeSnippet,
} from "./getStarted";

const BASE = "http://localhost:8000";

describe("snippet builders", () => {
  it("no snippet ever asks for a password", () => {
    // Registration used to be a curl with email and password inline, which put
    // the password in ~/.zsh_history for anyone who later read the file. The
    // browser signup does not, so the terminal path is gone.
    for (const snippet of [
      openclawInstall(), openclawAddBot(), openclawSetKey("k", BASE),
      openclawDryRun(), openclawGoLive(), oneShotScript("k", BASE),
    ]) {
      expect(snippet.toLowerCase()).not.toContain("password");
    }
  });

  it("the setup sequence names every piece a fresh machine needs", () => {
    expect(openclawInstall()).toContain("openclaw.ai/install.sh");
    // Piping a remote script into bash — pin the protocol at least.
    expect(openclawInstall()).toContain("--proto '=https'");
    expect(openclawInstall()).toContain("onboard");        // where the model is picked
    expect(openclawAddBot()).toContain("skalenetwork/agentpit-examples");
  });

  it("the key is scoped to the skill, not the whole machine", () => {
    const s = openclawSetKey("pk_live_123", BASE);
    expect(s).toContain("skills.entries.agentpit-reference.env.AGENTPIT_API_KEY");
    expect(s).toContain("pk_live_123");
  });

  it("copying a terminal step yields commands only", () => {
    // Interactive zsh does not enable `interactive_comments`, so a pasted `#`
    // line is run as a command: `zsh: command not found: #`. Worse, a comment
    // containing `;` splits there and zsh tries to run the remainder too.
    // The block still SHOWS its comments; only the clipboard drops them.
    for (const snippet of [openclawInstall(), openclawSetKey("pk_live_123", BASE), openclawDryRun(), openclawGoLive()]) {
      const copied = commandsOnly(snippet);
      expect(copied).not.toMatch(/^\s*#/m);
      expect(copied).not.toMatch(/^\s*$/m);          // no blank runs left behind
      expect(copied.startsWith("openclaw") || copied.startsWith("curl")).toBe(true);
    }
    // and the commands themselves survive intact
    expect(commandsOnly(openclawGoLive())).toContain("openclaw cron add --every 15m");
  });

  it("commandsOnly keeps a shebang, so a script is still a script", () => {
    const script = "#!/usr/bin/env bash\n# explain\nset -eu\n";
    expect(commandsOnly(script)).toBe("#!/usr/bin/env bash\nset -eu");
  });

  it("the setup.sh block is copied verbatim — it is a file, not a paste", () => {
    // Stripping comments out of a script would also strip its shebang's
    // meaning as documentation and could cut lines inside the heredoc.
    const s = oneShotScript("pk_live_123", BASE);
    expect(s).toContain("#!/usr/bin/env bash");
    expect(s).toMatch(/^# \d\./m);
  });

  it("the wizard runs once, and only asks what this guide needs", () => {
    // The installer onboards by default (install.sh: `exec "$claw" onboard`),
    // so a second `openclaw onboard` walked the whole wizard twice. Install
    // with --no-onboard and run it once, with the answers already given:
    // the background service on, and the parts a trading agent never touches
    // -- chat channels, a search provider, hooks, the control UI -- off.
    // Model choice stays: without it the agent has nothing to think with.
    const s = openclawInstall();
    expect(s).toContain("bash -s -- --no-onboard");
    expect(s.match(/openclaw onboard/g)).toHaveLength(1);
    for (const flag of ["--install-daemon", "--skip-channels", "--skip-search", "--skip-skills"]) {
      expect(s).toContain(flag);
    }
    // --skip-skills skips onboarding's skills SETUP — the screen that offers to
    // install dependencies for every skill on the machine (1Password, Sonos,
    // Philips Hue, Apple Notes...). It does not disable the skills subsystem:
    // `openclaw skills install` in the next step is its own command, and the
    // reference skill declares no package dependencies, only `bins: [python3]`.
    // The workspace bootstrap must still run — the skill is installed into it.
    expect(s).not.toContain("--skip-bootstrap");
  });

  it("openclawSetKey falls back to the placeholder when logged out", () => {
    expect(openclawSetKey(null, BASE)).toContain(KEY_PLACEHOLDER);
  });

  it("the one-shot script does every step the manual path does", () => {
    const s = oneShotScript("pk_live_123", BASE);
    expect(s).toContain("openclaw.ai/install.sh");
    expect(s).toContain("skalenetwork/agentpit-examples");
    expect(s).toContain("AGENTPIT_API_KEY");
    expect(s).toContain("pk_live_123");
  });

  it("the one-shot script never goes live by itself", () => {
    // A script pasted off a web page must not start placing orders. It ends on
    // a dry run and only PRINTS the lines that make it real.
    const s = oneShotScript("pk_live_123", BASE);
    expect(s).toContain("AGENTPIT_DRY_RUN");
    const live = s.indexOf("cron add");
    const printed = s.indexOf("cat <<'NEXT'");
    expect(printed).toBeGreaterThan(-1);
    expect(live).toBeGreaterThan(printed);   // inside the message, not executed
  });

  it("the one-shot script is safe to re-run", () => {
    const s = oneShotScript(null, BASE);
    expect(s).toContain("command -v openclaw");   // skips an existing install
    expect(s).toContain("--force");               // re-installing the skill is fine
    expect(s).toContain(KEY_PLACEHOLDER);
  });

  it("the dry run arms and disarms itself inside one step", () => {
    // The flag used to be set two steps before it was cleared, so anyone who
    // stopped reading in between scheduled a muted agent. Now it cannot leak
    // past its own step: set, run, unset, in that order and nowhere else.
    const s = openclawDryRun();
    expect(s.indexOf("config set")).toBeLessThan(s.indexOf("openclaw agent"));
    expect(s.indexOf("openclaw agent")).toBeLessThan(s.indexOf("config unset"));
    expect(openclawSetKey("pk_live_123", BASE)).not.toContain("AGENTPIT_DRY_RUN");
    expect(openclawGoLive()).not.toContain("AGENTPIT_DRY_RUN");
  });

  it("the key step also says where orders go", () => {
    const s = openclawSetKey("pk_live_123", BASE);
    expect(s).toContain(`AGENTPIT_HOST '"${BASE}"'`);
  });

  it("only the last step can place an order", () => {
    expect(openclawGoLive()).toContain("openclaw cron add --every 15m");
    expect(openclawDryRun()).not.toContain("cron add");
  });

  it("a restart sits between the last config write and every run", () => {
    // Measured, at the cost of three unintended orders: the gateway reads its
    // config at startup and does not see a later write, whatever
    // `config set`'s "No gateway restart needed" says — that line is about the
    // CLI's own reload plan, not about a process already running. So the flag
    // must be in place BEFORE the restart, and the restart BEFORE the run.
    const s = openclawDryRun();
    const set = s.indexOf("AGENTPIT_DRY_RUN '\"1\"'");
    const restart = s.indexOf("daemon restart");
    const run = s.indexOf("openclaw agent");
    expect(set).toBeLessThan(restart);
    expect(restart).toBeLessThan(run);

    // and clearing the flag is followed by a restart too, or step 6 stays muted
    const unset = s.indexOf("config unset");
    expect(unset).toBeLessThan(s.lastIndexOf("daemon restart"));
    expect(s.match(/daemon restart/g)).toHaveLength(2);
  });

  it("the script restarts before it runs, for the same reason", () => {
    const s = oneShotScript("pk_live_123", BASE);
    const executed = s.slice(0, s.indexOf("cat <<'NEXT'"));
    expect(executed.indexOf("AGENTPIT_DRY_RUN")).toBeLessThan(executed.indexOf("daemon restart"));
    expect(executed.indexOf("daemon restart")).toBeLessThan(executed.indexOf("openclaw agent"));
  });

  it("the agent run names its target agent", () => {
    // `openclaw agent --message ...` refuses to pick a session for you, even
    // when exactly one agent exists and is marked default:
    //   No target session selected. Use --agent <id>, --session-key <key>, ...
    // `main` is the built-in default agent id (`openclaw agents list --json`
    // reports it with isDefault: true on a stock install).
    for (const snippet of [openclawDryRun(), oneShotScript("pk_live_123", BASE)]) {
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
    for (const snippet of [openclawDryRun(), oneShotScript("pk_live_123", BASE)]) {
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
      openclawInstall(),
      openclawAddBot(),
      openclawSetKey(key, BASE),
      openclawDryRun(),
      openclawGoLive(),
      oneShotScript(key, BASE),
    ];
    for (const code of snippets) {
      const glued = tokenizeSnippet(code, [key, addr, KEY_PLACEHOLDER])
        .map((t) => t.value)
        .join("");
      expect(glued).toBe(code);
    }
  });
});
