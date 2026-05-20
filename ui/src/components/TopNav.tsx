import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { AuthButtons } from "@/components/auth/AuthButtons";
import { useSearch } from "@/lib/searchContext";

export function TopNav() {
  const { pathname } = useLocation();
  const showSearch = pathname === "/" || pathname.startsWith("/events/");

  return (
    <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
      <div className="container flex h-14 items-center gap-6">
        <NavLink to="/" className="flex shrink-0 items-center gap-2">
          <span className="inline-block size-6 rounded-full bg-primary" />
          <span className="text-base font-semibold tracking-tight">
            AgentPit
          </span>
        </NavLink>
        {showSearch ? <SearchBar /> : null}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <AuthButtons />
        </div>
      </div>
    </header>
  );
}

function SearchBar() {
  const { query, setQuery } = useSearch();
  const { pathname } = useLocation();
  const navigate = useNavigate();

  const onChange = (next: string) => {
    setQuery(next);
    // The results grid lives on the home route, so searching from an event
    // page jumps back home where matches can render.
    if (pathname !== "/") navigate("/");
  };

  return (
    <div className="group flex max-w-md flex-1 items-center gap-2.5 rounded-lg bg-muted px-3 py-2 text-muted-foreground transition-colors focus-within:bg-background focus-within:text-foreground focus-within:ring-1 focus-within:ring-border">
      <span aria-hidden className="text-muted-foreground/70">
        <SearchGlyph />
      </span>
      <input
        type="search"
        value={query}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search markets"
        className="min-w-0 flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none"
      />
    </div>
  );
}

function SearchGlyph() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-4"
      aria-hidden
    >
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M20 20l-4.65-4.65" />
    </svg>
  );
}
