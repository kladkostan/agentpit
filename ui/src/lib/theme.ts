import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "agentpit.theme";
const DARK_CLASS = "dark";
const SYSTEM_DARK_QUERY = "(prefers-color-scheme: dark)";

function readStoredTheme(): Theme | null {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    if (value === "light" || value === "dark") return value;
  } catch {
    /* private mode etc. — fall back to system */
  }
  return null;
}

function getSystemTheme(): Theme {
  return window.matchMedia(SYSTEM_DARK_QUERY).matches ? "dark" : "light";
}

function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle(DARK_CLASS, theme === "dark");
}

export function getResolvedTheme(): Theme {
  return readStoredTheme() ?? getSystemTheme();
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* private mode etc. — preference won't persist */
  }
  applyTheme(theme);
}

export function initializeTheme(): void {
  applyTheme(getResolvedTheme());
}

export function useTheme(): {
  theme: Theme;
  setTheme: (next: Theme) => void;
  toggleTheme: () => void;
} {
  const [theme, setThemeState] = useState<Theme>(() => getResolvedTheme());

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== THEME_STORAGE_KEY) return;
      const resolved = getResolvedTheme();
      setThemeState(resolved);
      applyTheme(resolved);
    };
    window.addEventListener("storage", onStorage);

    const media = window.matchMedia(SYSTEM_DARK_QUERY);
    const onSystemChange = () => {
      if (readStoredTheme() !== null) return;
      const next: Theme = media.matches ? "dark" : "light";
      setThemeState(next);
      applyTheme(next);
    };
    media.addEventListener("change", onSystemChange);

    return () => {
      window.removeEventListener("storage", onStorage);
      media.removeEventListener("change", onSystemChange);
    };
  }, []);

  return {
    theme,
    setTheme: (next) => {
      setTheme(next);
      setThemeState(next);
    },
    toggleTheme: () => {
      const next: Theme = theme === "dark" ? "light" : "dark";
      setTheme(next);
      setThemeState(next);
    },
  };
}
