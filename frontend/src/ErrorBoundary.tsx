import { Component, type ReactNode } from "react";

// Keeps a render error in one renderer from blanking the whole app, and shows
// what actually failed (a plain white page tells you nothing).
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: unknown) {
    console.error("[reader] render error:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="center-note">
          <p>Something broke while rendering this view.</p>
          <pre
            style={{
              textAlign: "left",
              whiteSpace: "pre-wrap",
              fontSize: "0.8rem",
              color: "var(--ink-soft)",
              background: "var(--paper-sunken)",
              padding: "1rem",
              borderRadius: "8px",
              overflow: "auto",
            }}
          >
            {this.state.error.message}
            {"\n\n"}
            {this.state.error.stack}
          </pre>
          <p>
            <a href="/">← back to the library</a>
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
