/** Snippet builders + tinting tokenizer for the landing page's builder guide.
 *
 *  One source of truth: each builder returns the RAW string that is (a) shown,
 *  (b) copied to the clipboard, and (c) tested. `tokenizeSnippet` splits that
 *  same string into display tokens (comment / string / chip / text) and is
 *  LOSSLESS — concatenating token values reproduces the input — so what the
 *  user sees is byte-identical to what the copy button gives them. */

export const KEY_PLACEHOLDER = "YOUR_API_KEY";

/** Step 1 — get OpenClaw. Onboarding is where you pick the model it will think
 *  with, so there is no separate "configure a model" step. */
export function openclawInstall(): string {
  return `# macOS and Linux alike — detects the OS and installs Node if needed.
# --no-onboard stops it before the setup wizard, which we run ourselves below
curl -fsSL --proto '=https' --tlsv1.2 https://openclaw.ai/install.sh | bash -s -- --no-onboard

# the wizard, once — everything a trading agent never uses is switched off,
# so the only question left is which model it thinks with
openclaw onboard --install-daemon --skip-channels --skip-search --skip-skills --skip-hooks --skip-ui`;
}

/** Step 2 — add the agent. One repository is one skill. */
export function openclawAddBot(): string {
  return `openclaw skills install git:https://github.com/skalenetwork/agentpit-examples`;
}

/** Step 4 — the two things the skill needs: who you are, and where to send it.
 *
 *  No restart here: nothing runs until step 5, which restarts once for all of
 *  the config written so far. */
export function openclawSetKey(key: string | null, base: string): string {
  return `openclaw config set skills.entries.agentpit-reference.env.AGENTPIT_API_KEY ${key ?? KEY_PLACEHOLDER}

# where its orders go. Quoted because a bare URL is not valid JSON and the
# parser reads values as JSON before checking them
openclaw config set skills.entries.agentpit-reference.env.AGENTPIT_HOST '"${base}"'`;
}

/** Step 5 — a dry run: arm it, watch it think, disarm it.
 *
 *  THE RESTARTS ARE LOAD-BEARING. `config set` prints "No gateway restart
 *  needed", which is about its own reload plan, not about a gateway that is
 *  already running: that one read the config at startup and will not see a
 *  later write. Removing these once cost three unintended orders — the flag
 *  was set after the restart, so the "dry" run traded for real. */
export function openclawDryRun(): string {
  return `# while this is set it prints what it WOULD trade and sends nothing.
# the quotes matter: values are read as JSON, and a bare 1 arrives as a number
openclaw config set skills.entries.agentpit-reference.env.AGENTPIT_DRY_RUN '"1"'

# the gateway reads config at startup, so it has to pick up everything above
# before anything runs. Skip this and the first run trades for real
openclaw daemon restart
openclaw agent --agent main --message "run the agentpit-reference skill"

# happy with what it picked? clear the flag, and restart so it takes
openclaw config unset skills.entries.agentpit-reference.env.AGENTPIT_DRY_RUN
openclaw daemon restart`;
}

/** Step 6 — for real, then on a schedule. No config changes, so no restart. */
export function openclawGoLive(): string {
  return `# this one places orders
openclaw agent --agent main --message "run the agentpit-reference skill"

# and every 15 minutes from here on
openclaw cron add --every 15m "run the agentpit-reference skill"`;
}

/** Every step as one paste.
 *
 *  Idempotent on purpose: re-running it is how someone recovers from a half
 *  finished attempt. It ends on a dry run and prints the two lines that make it
 *  live — a script from a web page should not quietly start placing orders. */
export function oneShotScript(key: string | null, base: string): string {
  return `#!/usr/bin/env bash
set -euo pipefail

KEY="${key ?? KEY_PLACEHOLDER}"

# 1. OpenClaw, only if it is not already here. A fresh install also needs
#    onboarding, which is where you pick the model your agent thinks with.
if ! command -v openclaw >/dev/null 2>&1; then
  curl -fsSL --proto '=https' --tlsv1.2 https://openclaw.ai/install.sh | bash -s -- --no-onboard
  openclaw onboard --install-daemon --skip-channels --skip-search --skip-skills --skip-hooks --skip-ui
fi

# 2. the agent itself
openclaw skills install git:https://github.com/skalenetwork/agentpit-examples --force

# 3. your key and where its orders go, scoped to this skill rather than the
#    whole machine. Quoted values stay strings: the parser reads them as JSON
openclaw config set skills.entries.agentpit-reference.env.AGENTPIT_API_KEY "$KEY"
openclaw config set skills.entries.agentpit-reference.env.AGENTPIT_HOST '"${base}"'

# 4. safety on for the first cycle
openclaw config set skills.entries.agentpit-reference.env.AGENTPIT_DRY_RUN '"1"'

# 5. the gateway reads config at startup, so it has to pick all of that up
#    before anything runs. Without this the "dry" run trades for real
openclaw daemon restart

# 6. show what it WOULD trade — nothing is sent. "main" is the default agent
#    id; openclaw agents list if yours is named otherwise
openclaw agent --agent main --message "run the agentpit-reference skill"

cat <<'NEXT'

That was a dry run. Happy with what it picked? Then let it trade every 15 min:

  openclaw config unset skills.entries.agentpit-reference.env.AGENTPIT_DRY_RUN
  openclaw daemon restart
  openclaw cron add --every 15m "run the agentpit-reference skill"

NEXT`;
}

/* ------------------------------------------------------------- copying --- */

/** A snippet with its explanatory comments removed, for the clipboard.
 *
 *  Interactive zsh does not set `interactive_comments`, so a pasted `#` line
 *  is not a comment — it is a command, and the shell answers
 *  `zsh: command not found: #` once per line. A comment containing `;` is
 *  worse: the shell splits there and tries to run the remainder as well.
 *
 *  So the block shows its comments and the clipboard carries only the
 *  commands. A shebang survives, because a script that loses it stops being
 *  a script; it is the one `#` line that is not commentary.
 */
export function commandsOnly(code: string): string {
  const lines = code.split("\n");
  const kept = lines.filter(
    (line, i) => (i === 0 && line.startsWith("#!")) || !/^\s*#/.test(line),
  );
  return kept
    .join("\n")
    .replace(/\n{2,}/g, "\n")   // the blanks the comments used to separate
    .trim();
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
