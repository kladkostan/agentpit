import { useEffect, useMemo, useRef, useState } from "react";
import { useEventCategories, useEventsInfinite } from "@/api/events";
import { useMarketStats } from "@/api/markets";
import { useDismissOnOutside } from "@/lib/useDismissOnOutside";
import { ScrollToTop } from "@/components/ScrollToTop";
import { Button } from "@/components/ui/button";
import {
  ArrowUpRight,
  Bitcoin,
  BriefcaseBusiness,
  CircleDollarSign,
  Check,
  ChevronDown,
  Clapperboard,
  Clock3,
  Cpu,
  Droplets,
  FlaskConical,
  Globe2,
  Landmark,
  LayoutGrid,
  Sparkles,
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

  // POLYMARKET_CATEGORY_ORDER is an ORDERING hint only, never a source of
  // categories: rendering a canonical label the backend never reported
  // advertises a filter that is guaranteed to yield an empty grid (and it
  // would render all 8 even when /events/categories is empty or errors).
  const ordered: string[] = [];
  for (const canonical of POLYMARKET_CATEGORY_ORDER) {
    const key = normalizeCategoryKey(canonical);
    const existing = normalizedToRaw.get(key);
    if (existing === undefined) continue;
    ordered.push(existing);
    normalizedToRaw.delete(key);
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

type SortMode =
  | "volume24h"
  | "totalVolume"
  | "liquidity"
  | "newest"
  | "endingSoon"
  | "competitive";

const SORT_OPTIONS: {
  key: SortMode;
  label: string;
  icon: LucideIcon;
}[] = [
    { key: "volume24h", label: "24hr Volume", icon: ArrowUpRight },
    { key: "totalVolume", label: "Total Volume", icon: CircleDollarSign },
    { key: "liquidity", label: "Liquidity", icon: Droplets },
    { key: "newest", label: "Newest", icon: Sparkles },
    { key: "endingSoon", label: "Ending Soon", icon: Clock3 },
    { key: "competitive", label: "Competitive", icon: Trophy },
  ];

const DEFAULT_SORT_OPTION = SORT_OPTIONS[0] ?? {
  key: "volume24h" as SortMode,
  label: "24hr Volume",
  icon: ArrowUpRight,
};

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
  const [showSortMenu, setShowSortMenu] = useState(false);
  // Each menu closes on a press outside it or on Escape; without this they
  // stayed open until their own trigger was clicked again.
  const sortMenuRef = useRef<HTMLDivElement>(null);
  useDismissOnOutside(sortMenuRef, () => setShowSortMenu(false), showSortMenu);
  const [sortMode, setSortMode] = useState<SortMode>("volume24h");
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
  const tabTriggerClassName = "h-9 rounded-full px-3 text-sm";
  const tabMenuSurfaceClassName =
    "absolute left-0 z-20 mt-2 rounded-3xl border bg-background p-2 shadow-xl";
  const tabMenuItemClassName =
    "flex w-full items-center gap-2.5 rounded-2xl px-3 py-2 text-left text-sm hover:bg-muted/40";
  const tabSelectedIndicatorClassName =
    "size-2.5 rounded-full bg-muted-foreground/70";

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

    const withSubcategories =
      selectedSubcategoryOptions.length === 0
        ? queryFiltered
        : queryFiltered.filter(({ event, markets }) =>
          selectedSubcategoryOptions.some((subcategory) =>
            eventMatchesKeywords(event, markets, subcategory.keywords),
          ),
        );

    const sorted = [...withSubcategories];
    sorted.sort((a, b) => {
      if (sortMode === "volume24h" || sortMode === "totalVolume") {
        // "24hr Volume" sorts on the figure the server ranks by
        // (ORDER BY VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC), so the client
        // ordering agrees with the server's instead of silently reverting the
        // page to roughly newest-first. "Total Volume" sorts on the all-time
        // figure — until it existed, the two menu entries were the same sort.
        const key = sortMode === "totalVolume" ? "volume" : "volume_24hr";
        const aVolume = a.event[key] ?? 0;
        const bVolume = b.event[key] ?? 0;
        if (bVolume !== aVolume) return bVolume - aVolume;
        const aLiveCount = a.markets.filter((m) => m.market_state === "ACTIVE").length;
        const bLiveCount = b.markets.filter((m) => m.market_state === "ACTIVE").length;
        if (bLiveCount !== aLiveCount) return bLiveCount - aLiveCount;
        return b.event.event_id - a.event.event_id;
      }

      if (sortMode === "liquidity") {
        if (b.markets.length !== a.markets.length) {
          return b.markets.length - a.markets.length;
        }
        return b.event.event_id - a.event.event_id;
      }

      if (sortMode === "endingSoon") {
        const aEnd = a.event.end_date ?? Number.MAX_SAFE_INTEGER;
        const bEnd = b.event.end_date ?? Number.MAX_SAFE_INTEGER;
        if (aEnd !== bEnd) return aEnd - bEnd;
        return b.event.event_id - a.event.event_id;
      }

      if (sortMode === "competitive") {
        const aOutcomes = a.markets.length;
        const bOutcomes = b.markets.length;
        if (bOutcomes !== aOutcomes) return bOutcomes - aOutcomes;
        return b.event.event_id - a.event.event_id;
      }

      const aStart = a.event.start_date ?? 0;
      const bStart = b.event.start_date ?? 0;
      if (bStart !== aStart) return bStart - aStart;
      return b.event.event_id - a.event.event_id;
    });

    return sorted;
  }, [
    events,
    selectedSubcategoryOptions,
    sortMode,
    trimmedQuery,
  ]);

  // Platform-wide, from the server. Counting the loaded pages instead reports
  // how far the user has scrolled — it read "93 live" on the first page while
  // 1928 markets were actually active, and climbed as you scrolled.
  const { data: marketStats } = useMarketStats();
  const activeCount = marketStats?.active ?? null;

  const isSearching = trimmedQuery.length > 0;
  const hasClientSideFilter =
    isSearching || selectedSubcategoryOptions.length > 0;

  // Any filter that runs client-side only sees the pages already loaded, so
  // eagerly pull the remaining pages while one is active. The
  // `filtered.length === 0` clause is the important one: listEvents hides
  // fully-resolved events, so a full wire page can render zero rows while
  // hasNextPage is true — and the infinite-scroll sentinel lives inside
  // EventGrid, so without this the grid would be a permanent dead end.
  useEffect(() => {
    if (!hasNextPage || isFetchingNextPage) return;
    if (hasClientSideFilter || filtered.length === 0) {
      void fetchNextPage();
    }
  }, [
    hasClientSideFilter,
    filtered.length,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  ]);

  function clearAllFilters() {
    setQuery("");
    setSelectedCategory(null);
    setSelectedSubcategories([]);
  }

  const selectedSortOption =
    SORT_OPTIONS.find((option) => option.key === sortMode) ?? DEFAULT_SORT_OPTION;
  const SelectedSortIcon = selectedSortOption.icon;

  function handleCategorySelect(nextCategory: string | null) {
    // Re-clicking the active category should clear category filters.
    if (nextCategory !== null && selectedCategory === nextCategory) {
      const categoryKey = normalizeCategoryKey(nextCategory);
      setSelectedCategory(null);
      setSelectedSubcategories([]);
      setExpandedSubcategories((prev) => ({ ...prev, [categoryKey]: false }));
      return;
    }

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
      <ScrollToTop />
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
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <div className="relative" ref={sortMenuRef}>
                  <Button
                    type="button"
                    variant="outline"
                    className={tabTriggerClassName}
                    onClick={() => setShowSortMenu((prev) => !prev)}
                  >
                    <SelectedSortIcon className="size-4" aria-hidden />
                    {selectedSortOption.label}
                    <ChevronDown
                      className={`size-4 transition-transform ${showSortMenu ? "rotate-180" : ""
                        }`}
                      aria-hidden
                    />
                  </Button>

                  {showSortMenu ? (
                    <div className={`${tabMenuSurfaceClassName} w-64`}>
                      {SORT_OPTIONS.map((option) => {
                        const OptionIcon = option.icon;
                        const isSelected = sortMode === option.key;

                        return (
                          <button
                            key={option.key}
                            type="button"
                            className={tabMenuItemClassName}
                            onClick={() => {
                              setSortMode(option.key);
                              setShowSortMenu(false);
                            }}
                          >
                            <OptionIcon className="size-4 text-current" aria-hidden />
                            <span className="flex-1">{option.label}</span>
                            {isSelected ? (
                              <span className={tabSelectedIndicatorClassName} aria-hidden />
                            ) : null}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}
                </div>

              </div>

              <span className="ml-auto flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                <span
                  aria-hidden
                  className="size-1.5 animate-pulse-dot rounded-full bg-emerald-500"
                />
                {activeCount === null ? "—" : activeCount.toLocaleString()} live
              </span>
            </div>
          </div>

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
          ) : filtered.length === 0 && !hasNextPage && !isFetchingNextPage ? (
            // Only a genuinely exhausted list is "empty" — while more pages
            // exist the grid keeps rendering (and keeps its sentinel/spinner)
            // so paging can continue past an all-filtered-out page.
            <EmptyState query={query} onClear={clearAllFilters} />
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
  const trimmed = query.trim();
  return (
    <div className="rounded-2xl border border-dashed bg-muted/20 px-8 py-16 text-center">
      <p className="text-2xl font-semibold tracking-tight">No matches</p>
      <p className="mt-2 text-sm text-muted-foreground">
        {trimmed.length > 0
          ? `Nothing matches “${trimmed}”. Try a different question.`
          : "No events match your current filters."}
      </p>
      <Button variant="outline" size="sm" className="mt-6" onClick={onClear}>
        Clear filters
      </Button>
    </div>
  );
}
