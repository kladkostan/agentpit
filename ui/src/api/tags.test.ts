import { beforeEach, describe, expect, it, vi } from "vitest";
import { listTags } from "./tags";
import { listEvents } from "./events";
import { apiFetch } from "@/api/client";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

describe("listTags", () => {
  beforeEach(() => vi.mocked(apiFetch).mockReset());

  it("requests /tags and returns the nested shape unchanged", async () => {
    const wire = {
      tags: [
        {
          slug: "politics",
          label: "Politics",
          count: 304,
          facets: [{ slug: "elections", label: "Elections", count: 161 }],
        },
      ],
    };
    vi.mocked(apiFetch).mockResolvedValueOnce(wire);
    await expect(listTags()).resolves.toEqual(wire);
    expect(vi.mocked(apiFetch).mock.calls[0]?.[0]).toBe("/tags");
  });
});

describe("listEvents tag params", () => {
  beforeEach(() => vi.mocked(apiFetch).mockReset().mockResolvedValue([]));

  function requestedPath(): string {
    return String(vi.mocked(apiFetch).mock.calls[0]?.[0]);
  }

  it("serialises tag", async () => {
    await listEvents({ limit: 20, offset: 0, tag: "politics" });
    expect(requestedPath()).toContain("tag=politics");
  });

  it("serialises each subtag as a repeated param", async () => {
    await listEvents({
      limit: 20,
      offset: 0,
      tag: "politics",
      subtags: ["trump", "midterms"],
    });
    const path = requestedPath();
    expect(path).toContain("subtag=trump");
    expect(path).toContain("subtag=midterms");
  });

  it("omits tag and subtag when absent or blank", async () => {
    await listEvents({ limit: 20, offset: 0, tag: "  ", subtags: [] });
    const path = requestedPath();
    expect(path).not.toContain("tag=");
    expect(path).not.toContain("subtag=");
  });

  it("still serialises category", async () => {
    await listEvents({ limit: 20, offset: 0, category: "Sports" });
    expect(requestedPath()).toContain("category=Sports");
  });
});
