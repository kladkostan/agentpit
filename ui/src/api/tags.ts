import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

/** A subcategory: a tag co-occurring with a top-level one. */
export interface TagFacet {
  slug: string;
  label: string;
  count: number;
}

/** A top-level category and the subcategories beneath it. */
export interface TagNavEntry {
  slug: string;
  label: string;
  count: number;
  facets: TagFacet[];
}

export interface ListTagsResponse {
  tags: TagNavEntry[];
}

export async function listTags(): Promise<ListTagsResponse> {
  return apiFetch<ListTagsResponse>("/tags");
}

export function useTags() {
  return useQuery({
    queryKey: ["tags"],
    queryFn: listTags,
    // The taxonomy only moves when the hourly sync runs, and the server caches
    // it for 30s anyway. Refetching on every mount buys nothing.
    staleTime: 60_000,
  });
}
