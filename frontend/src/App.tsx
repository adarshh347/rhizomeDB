import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";

import { ErrorBoundary } from "./ErrorBoundary";

type Theme = "auto" | "light" | "dark";
const NEXT: Record<Theme, Theme> = { auto: "light", light: "dark", dark: "auto" };
const ICON: Record<Theme, string> = { auto: "◐", light: "☀", dark: "☾" };

// Light/dark/auto toggle. Tokens key off :root[data-theme]; "auto" removes the
// attribute so the OS preference (prefers-color-scheme) wins.
function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("theme") as Theme) || "auto",
  );
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);
  return (
    <button
      className="btn theme-toggle"
      onClick={() => setTheme((t) => NEXT[t])}
      title={`Theme: ${theme} — click to change`}
      aria-label={`Theme: ${theme}`}
    >
      {ICON[theme]}
    </button>
  );
}

// The shell: a sticky brand bar and the routed surface beneath it. The reader
// route paints its own full-height layout inside the outlet.
export function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <span className="brand">
          <Link to="/">Rhizome Reader</Link>
        </span>
        <span className="spacer" />
        <span className="muted">native reading over the spine</span>
        <ThemeToggle />
      </header>
      <ErrorBoundary>
        <Outlet />
      </ErrorBoundary>
    </div>
  );
}
