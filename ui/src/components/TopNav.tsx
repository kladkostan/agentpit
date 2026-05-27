import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { AuthButtons } from "@/components/auth/AuthButtons";
import { useAuth } from "@/auth/useAuth";
import { getAvatarStyle } from "@/lib/avatarColor";
import { useSearch } from "@/lib/searchContext";
import { useTheme } from "@/lib/theme";
import { useState } from "react";
import { Menu, MenuItem, IconButton } from "@mui/material";
import { LogOut, Moon, Settings, Sun, User } from "lucide-react";

const menuPaperSx = {
  width: 220,
  borderRadius: 2.5,
  mt: 1,
  border: "1px solid hsl(var(--border) / 0.7)",
  backgroundColor: "hsl(var(--popover))",
  color: "hsl(var(--popover-foreground))",
  boxShadow:
    "0 16px 40px -20px hsl(var(--foreground) / 0.45), 0 2px 12px -4px hsl(var(--foreground) / 0.25)",
  overflow: "hidden",
};

const menuListSx = { p: 0.75 };

const menuItemSx = {
  minHeight: 38,
  borderRadius: 1.5,
  px: 1.5,
  py: 0.75,
  fontSize: "0.875rem",
  color: "hsl(var(--foreground))",
  "&:hover": {
    backgroundColor: "hsl(var(--muted))",
  },
};

const logoutItemSx = {
  ...menuItemSx,
  color: "rgb(220 38 38)",
  "&:hover": {
    backgroundColor: "rgb(239 68 68 / 0.1)",
  },
};

export function TopNav() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const isDarkMode = theme === "dark";
  const showSearch = pathname === "/" || pathname.startsWith("/events/");
  const avatarStyle = user
    ? getAvatarStyle(user.eth_address || user.email)
    : undefined;
  const avatarLabelSource = user?.handle || user?.email || "?";

  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const open = Boolean(anchorEl);

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleMenuClose = () => {
    setAnchorEl(null);
  };

  const handleLogout = () => {
    handleMenuClose();
    logout();
  };

  const handleProfile = () => {
    handleMenuClose();
    navigate("/profile");
  };

  const handleSettings = () => {
    handleMenuClose();
    navigate("/settings");
  };

  const handleToggleDarkMode = (
    event: React.MouseEvent<HTMLLIElement>,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    toggleTheme();
  };

  return (
    <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
      <div className="container flex h-14 items-center gap-6">
        <NavLink to="/" className="flex shrink-0 items-center gap-2">
          <AgentLogo />
          <span className="text-base font-semibold tracking-tight">
            AgentPit
          </span>
        </NavLink>
        {showSearch ? <SearchBar /> : null}
        <div className="ml-auto flex shrink-0 items-center gap-3">
          {user ? (
            <>
              <IconButton
                aria-controls={open ? "profile-menu" : undefined}
                aria-haspopup="true"
                aria-expanded={open ? "true" : undefined}
                onClick={handleMenuOpen}
              >
                <div
                  className="flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white"
                  style={avatarStyle}
                >
                  {avatarLabelSource.slice(0, 1).toUpperCase()}
                </div>
              </IconButton>
              <Menu
                id="profile-menu"
                anchorEl={anchorEl}
                open={open}
                onClose={handleMenuClose}
                anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
                transformOrigin={{ vertical: "top", horizontal: "center" }}
                slotProps={{
                  paper: { sx: menuPaperSx },
                  list: { sx: menuListSx },
                }}
              >
                <MenuItem onClick={handleProfile} sx={menuItemSx}>
                  <User className="mr-2 size-4" /> Profile
                </MenuItem>
                         <MenuItem
                  sx={menuItemSx}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    handleToggleDarkMode(event);
                  }}
                >
                  <Moon className="mr-2 size-4" />
                  <span className="mr-3">Dark mode</span>
                  <span
                    className={`ml-auto inline-flex h-5 w-9 items-center rounded-full transition-colors ${isDarkMode ? "bg-primary" : "bg-muted-foreground/40"}`}
                    aria-hidden
                  >
                    <span
                      className={`inline-block size-4 rounded-full bg-white transition-transform ${isDarkMode ? "translate-x-4" : "translate-x-0.5"}`}
                    />
                  </span>
                </MenuItem>
                <MenuItem onClick={handleSettings} sx={menuItemSx}>
                  <Settings className="mr-2 size-4" /> Settings
                </MenuItem>
                <MenuItem onClick={handleLogout} sx={logoutItemSx}>
                  <LogOut className="mr-2 size-4" /> Logout
                </MenuItem>
              </Menu>
            </>
          ) : null}
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

function AgentLogo() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 25 25"
      fill="currentColor"
      className="size-6 shrink-0 text-primary"
      aria-hidden
    >
      <ellipse cx="12.42" cy="22" rx="2.57" ry="2.73" />
      <path d="M13.18,1.04l-.19-.12c-.63-.39-1.44-.16-1.81.51L.6,20.9c-.37.67-.15,1.53.48,1.92l.19.12c.63.39,1.44.16,1.81-.51L13.67,2.95c.37-.67.15-1.53-.48-1.92Z" />
      <path d="M11.66,1.04l.19-.12c.63-.39,1.44-.16,1.81.51l10.59,19.46c.37.67.15,1.53-.48,1.92l-.19.12c-.63.39-1.44.16-1.81-.51L11.18,2.95c-.37-.67-.15-1.53.48-1.92Z" />
    </svg>
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
