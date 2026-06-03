import { useEffect, useMemo, useState } from "react";
import { useEventCategories, useEventsInfinite } from "@/api/events";
import { Button } from "@/components/ui/button";
import {
  Bitcoin,
  BriefcaseBusiness,
  Check,
  ChevronDown,
  Clapperboard,
  Cpu,
  FlaskConical,
  Globe2,
  Landmark,
  LayoutGrid,
  Tag,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import {
  EventGrid,
  EventGridSkeleton,
} from "@/components/EventGrid";
import { useSearch } from "@/lib/searchContext";
import type { EventWithMarkets } from "@/types/event";

const POLYMARKET_CATEGORY_ORDER = [
  "Politics",
  "Sports",
  "Crypto",
  "Business",
  "Science",
  "Technology",
  "World",
  "Pop Culture",
] as const;

function normalizeCategoryKey(category: string): string {
  return category.trim().toLowerCase();
}

function buildCategoryList(rawCategories: string[]): string[] {
  const normalizedToRaw = new Map<string, string>();
  for (const category of rawCategories) {
    const trimmed = category.trim();
    if (!trimmed) continue;
    const key = normalizeCategoryKey(trimmed);
    if (!normalizedToRaw.has(key)) {
      normalizedToRaw.set(key, trimmed);
    }
  }

  const ordered: string[] = [];
  for (const canonical of POLYMARKET_CATEGORY_ORDER) {
    const existing = normalizedToRaw.get(normalizeCategoryKey(canonical));
    ordered.push(existing ?? canonical);
    normalizedToRaw.delete(normalizeCategoryKey(canonical));
  }

  const extras = [...normalizedToRaw.values()].sort((a, b) =>
    a.localeCompare(b),
  );
  return [...ordered, ...extras];
}

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  all: LayoutGrid,
  politics: Landmark,
  sports: Trophy,
  crypto: Bitcoin,
  business: BriefcaseBusiness,
  science: FlaskConical,
  technology: Cpu,
  world: Globe2,
  "pop culture": Clapperboard,
};

function getCategoryIcon(category: string): LucideIcon {
  return CATEGORY_ICONS[normalizeCategoryKey(category)] ?? Tag;
}

interface SubcategoryOption {
  id: string;
  label: string;
  keywords: string[];
}

const CATEGORY_SUBCATEGORIES: Record<string, SubcategoryOption[]> = {
  politics: [
    {
      id: "us-elections",
      label: "US Elections",
      keywords: ["election", "vote", "primary", "president"],
    },
    {
      id: "congress",
      label: "Congress",
      keywords: ["senate", "house", "congress"],
    },
    {
      id: "geopolitics",
      label: "Geopolitics",
      keywords: ["war", "conflict", "geopolitics", "diplomacy"],
    },
  ],
  sports: [
    {
      id: "soccer",
      label: "Soccer",
      keywords: ["soccer", "football", "fifa", "uefa", "champions league"],
    },
    {
      id: "nba",
      label: "NBA",
      keywords: ["nba", "basketball"],
    },
    {
      id: "nfl",
      label: "NFL",
      keywords: ["nfl", "super bowl", "football"],
    },
    {
      id: "combat",
      label: "MMA/Boxing",
      keywords: ["ufc", "boxing", "mma"],
    },
  ],
  crypto: [
    {
      id: "bitcoin",
      label: "Bitcoin",
      keywords: ["bitcoin", "btc"],
    },
    {
      id: "ethereum",
      label: "Ethereum",
      keywords: ["ethereum", "eth"],
    },
    {
      id: "solana",
      label: "Solana",
      keywords: ["solana", "sol"],
    },
    {
      id: "airdrops",
      label: "Airdrops",
      keywords: ["airdrop", "token launch"],
    },
  ],
  business: [
    {
      id: "markets",
      label: "Markets",
      keywords: ["stocks", "s&p", "nasdaq", "dow"],
    },
    {
      id: "earnings",
      label: "Earnings",
      keywords: ["earnings", "revenue", "guidance"],
    },
    {
      id: "macro",
      label: "Macro",
      keywords: ["inflation", "fed", "rate", "recession"],
    },
  ],
  science: [
    {
      id: "space",
      label: "Space",
      keywords: ["space", "mars", "nasa", "rocket"],
    },
    {
      id: "health",
      label: "Health",
      keywords: ["health", "drug", "trial", "fda"],
    },
    {
      id: "climate",
      label: "Climate",
      keywords: ["climate", "temperature", "emissions"],
    },
  ],
  technology: [
    {
      id: "ai",
      label: "AI",
      keywords: ["ai", "artificial intelligence", "model"],
    },
    {
      id: "hardware",
      label: "Hardware",
      keywords: ["chip", "gpu", "cpu", "semiconductor"],
    },
    {
      id: "apps",
      label: "Consumer Tech",
      keywords: ["app", "platform", "launch", "iphone", "android"],
    },
  ],
  world: [
    {
      id: "europe",
      label: "Europe",
      keywords: ["europe", "eu", "uk"],
    },
    {
      id: "asia",
      label: "Asia",
      keywords: ["asia", "china", "japan", "india"],
    },
    {
      id: "latam",
      label: "LatAm",
      keywords: ["latam", "latin america", "brazil", "mexico"],
    },
  ],
  "pop culture": [
    {
      id: "movies",
      label: "Movies",
      keywords: ["movie", "film", "oscar"],
    },
    {
      id: "music",
      label: "Music",
      keywords: ["music", "album", "grammy"],
    },
    {
      id: "celebs",
      label: "Celebrities",
      keywords: ["celebrity", "celeb", "actor", "artist"],
    },
  ],
};

function getSubcategories(category: string): SubcategoryOption[] {
  return CATEGORY_SUBCATEGORIES[normalizeCategoryKey(category)] ?? [];
}

function getSubcategorySelectionKey(
  category: string,
  subcategoryId: string,
): string {
  return `${normalizeCategoryKey(category)}::${subcategoryId}`;
}

function eventMatchesKeywords(
  event: EventWithMarkets["event"],
  markets: EventWithMarkets["markets"],
  keywords: string[],
): boolean {
  const text = `${event.title} ${markets
    .map((m) => m.outcome_label ?? m.question)
    .join(" ")}`.toLowerCase();
  return keywords.some((keyword) => text.includes(keyword.toLowerCase()));
}

export function MarketsPage() {
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [expandedSubcategories, setExpandedSubcategories] = useState<
    Record<string, boolean>
  >({});
  const [selectedSubcategories, setSelectedSubcategories] = useState<string[]>([]);
  const { data: categoriesData } = useEventCategories();
  const {
    data,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    refetch,
  } = useEventsInfinite(selectedCategory);

  const categories = useMemo(
    () => buildCategoryList(categoriesData?.categories ?? []),
    [categoriesData?.categories],
  );
  const categoriesWithAll = useMemo(
    () => ["All", ...categories],
    [categories],
  );

  const events = useMemo<EventWithMarkets[]>(
    () => data?.pages.flatMap((page) => page.events) ?? [],
    [data],
  );
  const { query, setQuery } = useSearch();
  const trimmedQuery = query.trim().toLowerCase();

  // When the user starts searching, eagerly pull remaining pages so the
  // client-side filter sees the whole dataset rather than only the loaded
  // window.
  useEffect(() => {
    if (trimmedQuery.length > 0 && hasNextPage && !isFetchingNextPage) {
      void fetchNextPage();
    }
  }, [trimmedQuery, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const selectedSubcategoryOptions = useMemo(() => {
    if (!selectedCategory) return [];

    return getSubcategories(selectedCategory).filter((subcategory) =>
      selectedSubcategories.includes(
        getSubcategorySelectionKey(selectedCategory, subcategory.id),
      ),
    );
  }, [selectedCategory, selectedSubcategories]);

  const filtered = useMemo(() => {
    const queryFiltered =
      trimmedQuery.length === 0
        ? events
        : events.filter(({ event, markets }) => {
          if (event.title.toLowerCase().includes(trimmedQuery)) return true;
          return markets.some((m) =>
            (m.outcome_label ?? m.question).toLowerCase().includes(trimmedQuery),
          );
        });

    if (selectedSubcategoryOptions.length === 0) return queryFiltered;

    return queryFiltered.filter(({ event, markets }) =>
      selectedSubcategoryOptions.some((subcategory) =>
        eventMatchesKeywords(event, markets, subcategory.keywords),
      ),
    );
  }, [events, selectedSubcategoryOptions, trimmedQuery]);

  const activeCount = useMemo(
    () =>
      events.reduce(
        (acc, ev) =>
          acc +
          ev.markets.filter((m) => m.market_state === "ACTIVE").length,
        0,
      ),
    [events],
  );

  const isSearching = trimmedQuery.length > 0;

  function handleCategorySelect(nextCategory: string | null) {
    setSelectedCategory(nextCategory);

    if (nextCategory === null) {
      setSelectedSubcategories([]);
      return;
    }

    const categoryKey = normalizeCategoryKey(nextCategory);
    setExpandedSubcategories((prev) => ({ ...prev, [categoryKey]: true }));
    setSelectedSubcategories((prev) =>
      prev.filter((selectionKey) => selectionKey.startsWith(`${categoryKey}::`)),
    );
  }

  function handleSubcategoryToggle(category: string, subcategoryId: string) {
    const key = getSubcategorySelectionKey(category, subcategoryId);
    const categoryKey = normalizeCategoryKey(category);

    if (selectedCategory !== category) {
      setSelectedCategory(category);
      setSelectedSubcategories((prev) => {
        const currentCategorySelections = prev.filter((selectionKey) =>
          selectionKey.startsWith(`${categoryKey}::`),
        );
        if (currentCategorySelections.includes(key)) return currentCategorySelections;
        return [...currentCategorySelections, key];
      });
    } else {
      setSelectedSubcategories((prev) =>
        prev.includes(key)
          ? prev.filter((selectionKey) => selectionKey !== key)
          : [...prev, key],
      );
    }

    setExpandedSubcategories((prev) => ({ ...prev, [categoryKey]: true }));
  }

  return (
    <section className="space-y-8">
      <div className="flex gap-2 overflow-x-auto pb-1 lg:hidden">
        {categoriesWithAll.map((category) => {
          const isAll = category === "All";
          const isSelected = isAll
            ? selectedCategory === null
            : selectedCategory === category;
          const Icon = getCategoryIcon(category);
          return (
            <Button
              key={category}
              type="button"
              variant={isSelected ? "default" : "outline"}
              size="sm"
              className="shrink-0 gap-1.5"
              onClick={() => handleCategorySelect(isAll ? null : category)}
            >
              <Icon className="size-4" aria-hidden />
              {category}
            </Button>
          );
        })}
      </div>

      {selectedCategory ? (
        <div className="space-y-2 lg:hidden">
          <div className="flex items-center justify-between rounded-xl border bg-card/40 px-3 py-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Subcategories
            </span>

            {getSubcategories(selectedCategory).length > 0 ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 hover:bg-transparent hover:text-inherit"
                onClick={() => {
                  const categoryKey = normalizeCategoryKey(selectedCategory);
                  setExpandedSubcategories((prev) => ({
                    ...prev,
                    [categoryKey]: !prev[categoryKey],
                  }));
                }}
                aria-label="Toggle subcategories"
              >
                <ChevronDown
                  className={`size-4 transition-transform ${expandedSubcategories[normalizeCategoryKey(selectedCategory)]
                    ? "rotate-180"
                    : ""
                    }`}
                  aria-hidden
                />
              </Button>
            ) : null}
          </div>

          {expandedSubcategories[normalizeCategoryKey(selectedCategory)] ? (
            <div className="border-l border-border/70 pl-3 flex flex-col gap-1.5">
              {getSubcategories(selectedCategory).map((subcategory) => {
                const isSubSelected = selectedSubcategories.includes(
                  getSubcategorySelectionKey(selectedCategory, subcategory.id),
                );

                return (
                  <Button
                    key={subcategory.id}
                    type="button"
                    variant={isSubSelected ? "default" : "outline"}
                    size="sm"
                    className="h-9 w-full justify-start gap-1.5"
                    onClick={() =>
                      handleSubcategoryToggle(selectedCategory, subcategory.id)
                    }
                  >
                    {isSubSelected ? <Check className="size-3.5" aria-hidden /> : null}
                    {subcategory.label}
                  </Button>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-8 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="hidden lg:block">
          <div className="sticky top-20 rounded-2xl border bg-card/40 p-3">
            <p className="px-2 font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
              Categories
            </p>
            <nav className="mt-3 flex flex-col gap-1">
              {categoriesWithAll.map((category) => {
                const isAll = category === "All";
                const isSelected = isAll
                  ? selectedCategory === null
                  : selectedCategory === category;
                const Icon = getCategoryIcon(category);
                const subcategories = isAll ? [] : getSubcategories(category);
                const categoryKey = normalizeCategoryKey(category);
                const isExpanded = expandedSubcategories[categoryKey];
                const arrowColorClass = isSelected
                  ? "text-primary-foreground"
                  : "text-foreground";
                const selectedCount = subcategories.filter((subcategory) =>
                  selectedSubcategories.includes(
                    getSubcategorySelectionKey(category, subcategory.id),
                  ),
                ).length;

                return (
                  <div key={category} className="space-y-1">
                    <div className="relative">
                      <Button
                        type="button"
                        variant={isSelected ? "default" : "ghost"}
                        size="sm"
                        className="min-w-0 w-full justify-start gap-1.5 pr-8"
                        onClick={() => handleCategorySelect(isAll ? null : category)}
                      >
                        <Icon className="size-4" aria-hidden />
                        <span className="truncate">{category}</span>

                        {selectedCount > 0 ? (
                          <span className="ml-auto rounded-full bg-background/70 px-1.5 py-0.5 text-[10px] leading-none">
                            {selectedCount}
                          </span>
                        ) : null}
                      </Button>

                      {subcategories.length > 0 ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="absolute right-1 top-1/2 h-6 w-6 -translate-y-1/2 p-0 hover:bg-transparent hover:text-inherit"
                          onClick={() => {
                            setExpandedSubcategories((prev) => ({
                              ...prev,
                              [categoryKey]: !prev[categoryKey],
                            }));
                          }}
                          aria-label={`Toggle ${category} subcategories`}
                        >
                          <ChevronDown
                            className={`size-4 transition-transform ${arrowColorClass} ${isExpanded ? "rotate-180" : ""
                              }`}
                            aria-hidden
                          />
                        </Button>
                      ) : null}
                    </div>

                    {isExpanded && subcategories.length > 0 ? (
                      <div className="ml-5 border-l border-border/70 pl-3 flex flex-col gap-1 pb-1">
                        {subcategories.map((subcategory) => {
                          const isSubSelected = selectedSubcategories.includes(
                            getSubcategorySelectionKey(category, subcategory.id),
                          );

                          return (
                            <Button
                              key={subcategory.id}
                              type="button"
                              variant={isSubSelected ? "default" : "outline"}
                              size="sm"
                              className="h-8 w-full justify-start gap-1 px-2 text-xs"
                              onClick={() =>
                                handleSubcategoryToggle(category, subcategory.id)
                              }
                            >
                              {isSubSelected ? (
                                <Check className="size-3" aria-hidden />
                              ) : null}
                              {subcategory.label}
                            </Button>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </nav>
          </div>
        </aside>

        <div className="space-y-8">
          <header className="flex items-center justify-end gap-6 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="size-1.5 animate-pulse-dot rounded-full bg-emerald-500"
              />
              {activeCount} live
            </span>
          </header>

          {isLoading ? (
            <EventGridSkeleton />
          ) : error ? (
            <div className="rounded-2xl border border-destructive/30 bg-destructive/5 p-8">
              <p className="text-xl font-semibold tracking-tight">
                Failed to load markets
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                {error instanceof Error ? error.message : "Unknown error"}
              </p>
              <Button
                variant="outline"
                size="sm"
                className="mt-4"
                onClick={() => {
                  void refetch();
                }}
              >
                Retry
              </Button>
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState query={query} onClear={() => setQuery("")} />
          ) : (
            <EventGrid
              events={filtered}
              hasNextPage={!isSearching && hasNextPage}
              isFetchingNextPage={isFetchingNextPage}
              onLoadMore={() => {
                void fetchNextPage();
              }}
            />
          )}
        </div>
      </div>
    </section>
  );
}

function EmptyState({
  query,
  onClear,
}: {
  query: string;
  onClear: () => void;
}) {
  return (
    <div className="rounded-2xl border border-dashed bg-muted/20 px-8 py-16 text-center">
      <p className="text-2xl font-semibold tracking-tight">No matches</p>
      <p className="mt-2 text-sm text-muted-foreground">
        Nothing matches “{query}”. Try a different question.
      </p>
      <Button
        variant="outline"
        size="sm"
        className="mt-6"
        onClick={onClear}
      >
        Clear filter
      </Button>
    </div>
  );
}
