export type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "agentpit.theme";
const DARK_CLASS = "dark";
const SYSTEM_DARK_QUERY = "(prefers-color-scheme: dark)";

function readStoredTheme(): Theme | null {
    try {
        const value = localStorage.getItem(THEME_STORAGE_KEY);
        if (value === "light" || value === "dark") return value;
    } catch {
    }
    return null;
}

function getSystemTheme(): Theme {
    return window.matchMedia(SYSTEM_DARK_QUERY).matches ? "dark" : "light";
}

export function getResolvedTheme(): Theme {
    return readStoredTheme() ?? getSystemTheme();
}

export function setTheme(theme: Theme): void {
    try {
        localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
    }
    document.documentElement.classList.toggle(DARK_CLASS, theme === "dark");
}

export function initializeTheme(): void {
    setTheme(getResolvedTheme());
}