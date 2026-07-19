import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import * as RTooltip from "@radix-ui/react-tooltip";
import { Contrast, Moon, Sun } from "lucide-react";

import { ErrorBoundary } from "./ErrorBoundary";
import { Tip } from "./reader/Tip";

type Theme = "auto" | "light" | "dark";
const NEXT: Record<Theme, Theme> = { auto: "light", light: "dark", dark: "auto" };
const ICON: Record<Theme, typeof Sun> = { auto: Contrast, light: Sun, dark: Moon };

// Light/dark/auto toggle. Tokens key off :root[data-theme] (via color-scheme);
// "auto" removes the attribute so the OS preference wins.
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
  const Icon = ICON[theme];
  return (
    <Tip label={`Theme: ${theme} — click to change`}>
      <button
        className="btn-ghost icon theme-toggle"
        onClick={() => setTheme((t) => NEXT[t])}
        aria-label={`Theme: ${theme}`}
      >
        <Icon size={17} strokeWidth={1.75} aria-hidden />
      </button>
    </Tip>
  );
}

// The shell: a sticky brand bar and the routed surface beneath it. The reader
// route paints its own full-height layout inside the outlet. One tooltip
// provider covers the whole app.
export function App() {
  return (
    <RTooltip.Provider delayDuration={400} skipDelayDuration={200}>
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
    </RTooltip.Provider>
  );
}
