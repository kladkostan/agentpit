import { beforeEach, describe, expect, it, vi } from "vitest";

type FakeScript = {
  id: string;
  src: string;
  async: boolean;
  defer: boolean;
  onload: (() => void) | null;
  onerror: (() => void) | null;
};

function fakeDocument() {
  const scripts: FakeScript[] = [];
  const byId = new Map<string, FakeScript>();
  const doc = {
    getElementById: (id: string) => byId.get(id) ?? null,
    createElement: () =>
      ({
        id: "",
        src: "",
        async: false,
        defer: false,
        onload: null,
        onerror: null,
      }) as FakeScript,
    head: {
      appendChild: (node: FakeScript) => {
        scripts.push(node);
        byId.set(node.id, node);
      },
    },
  };
  return { doc: doc as unknown as Document, scripts };
}

// Each test needs a module whose loader promise has never been used: the
// singleton is the behaviour under test.
async function freshModule() {
  vi.resetModules();
  return await import("./googleAuth");
}

describe("readGoogleClientId", () => {
  it("returns the configured id", async () => {
    const { readGoogleClientId } = await freshModule();
    expect(readGoogleClientId({ VITE_GOOGLE_CLIENT_ID: "abc.apps.googleusercontent.com" }))
      .toBe("abc.apps.googleusercontent.com");
  });

  it("treats an unset variable as off", async () => {
    const { readGoogleClientId } = await freshModule();
    expect(readGoogleClientId({})).toBeNull();
  });

  it("treats an empty or blank variable as off", async () => {
    // A build arg that resolved to nothing must switch the feature off, not
    // render a button that initialises GIS with an empty client id.
    const { readGoogleClientId } = await freshModule();
    expect(readGoogleClientId({ VITE_GOOGLE_CLIENT_ID: "" })).toBeNull();
    expect(readGoogleClientId({ VITE_GOOGLE_CLIENT_ID: "   " })).toBeNull();
  });

  it("trims surrounding whitespace", async () => {
    const { readGoogleClientId } = await freshModule();
    expect(readGoogleClientId({ VITE_GOOGLE_CLIENT_ID: " abc \n" })).toBe("abc");
  });
});

describe("loadGoogleIdentity", () => {
  beforeEach(() => vi.resetModules());

  it("injects the script once, however many callers ask", async () => {
    const { loadGoogleIdentity } = await freshModule();
    const { doc, scripts } = fakeDocument();

    const first = loadGoogleIdentity(doc);
    const second = loadGoogleIdentity(doc);
    expect(scripts).toHaveLength(1);

    scripts[0]!.onload?.();
    await expect(first).resolves.toBeUndefined();
    await expect(second).resolves.toBeUndefined();
    expect(scripts).toHaveLength(1);
  });

  it("resolves once the script loads", async () => {
    const { loadGoogleIdentity } = await freshModule();
    const { doc, scripts } = fakeDocument();
    const loading = loadGoogleIdentity(doc);
    scripts[0]!.onload?.();
    await expect(loading).resolves.toBeUndefined();
  });

  it("rejects when the script fails, and lets a later caller retry", async () => {
    const { loadGoogleIdentity } = await freshModule();
    const { doc, scripts } = fakeDocument();

    const failing = loadGoogleIdentity(doc);
    scripts[0]!.onerror?.();
    await expect(failing).rejects.toThrow(/Google/);

    // A cached rejected promise would make one blocked network request
    // permanent for the tab; the next attempt gets a new script.
    const retry = loadGoogleIdentity(doc);
    expect(scripts).toHaveLength(2);
    scripts[1]!.onload?.();
    await expect(retry).resolves.toBeUndefined();
  });
});
