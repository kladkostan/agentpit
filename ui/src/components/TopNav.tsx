import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";

const linkClasses = ({ isActive }: { isActive: boolean }): string =>
  cn(
    "text-sm font-medium transition-colors hover:text-foreground",
    isActive ? "text-foreground" : "text-muted-foreground",
  );

export function TopNav() {
  return (
    <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
      <div className="container flex h-14 items-center gap-8">
        <NavLink to="/" className="flex items-center gap-2">
          <span className="inline-block size-6 rounded-full bg-primary" />
          <span className="text-base font-semibold tracking-tight">
            AgentPit
          </span>
        </NavLink>
        <nav className="flex items-center gap-6">
          <NavLink to="/" end className={linkClasses}>
            Markets
          </NavLink>
          {/* TODO: route /portfolio when portfolio page exists */}
          <NavLink to="/portfolio" className={linkClasses}>
            Portfolio
          </NavLink>
        </nav>
      </div>
    </header>
  );
}
