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

/** Step 4 — who it trades as, where it sends orders, and the one restart.
 *
 *  The restart is load-bearing and there is exactly one place it can go. A
 *  running gateway read its config at startup and will not see a later write
 *  — `config set`'s "No gateway restart needed" describes the CLI's own reload
 *  plan, not a process already running. The gateway is installed in step 2, so
 *  it is always older than these writes. */
export function openclawSetKey(key: string | null, base: string): string {
  return `openclaw config set skills.entries.agentpit-reference.env.AGENTPIT_API_KEY ${key ?? KEY_PLACEHOLDER}

# where its orders go. Quoted because a bare URL is not valid JSON and the
# parser reads values as JSON before checking them
openclaw config set skills.entries.agentpit-reference.env.AGENTPIT_HOST '"${base}"'

# the gateway reads config at startup, so it has to pick both of those up
# before anything runs
openclaw daemon restart`;
}

/** Step 5 — run it, then hand it to the scheduler.
 *
 *  There is no dry-run step. The balance is paper and the top-up restores it
 *  daily, so a first run that trades badly costs nothing and shows strictly
 *  more than a rehearsal would. The skill still honours AGENTPIT_DRY_RUN for
 *  anyone who starts changing the prompt — it is just not a step you must walk
 *  through to get a bot running. */
export function openclawGoLive(): string {
  return `# "main" is your agent — openclaw agents list, if yours is named otherwise
openclaw agent --agent main --message "run the agentpit-reference skill"

# happy with what it did? every 15 minutes from here on
openclaw cron add --every 15m "run the agentpit-reference skill"`;
}

/** Every step as one paste.
 *
 *  Idempotent on purpose: re-running it is how someone recovers from a half
 *  finished attempt. It runs one cycle and stops there, printing the line that
 *  schedules it — a script off a web page may spend paper money, but it should
 *  not leave a recurring job on your machine you did not ask for. */
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
