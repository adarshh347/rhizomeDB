import { Link, Outlet } from "react-router-dom";

import { ErrorBoundary } from "./ErrorBoundary";

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
      </header>
      <ErrorBoundary>
        <Outlet />
      </ErrorBoundary>
    </div>
  );
}
