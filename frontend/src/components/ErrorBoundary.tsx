import { Component, type ErrorInfo, type ReactNode } from "react";

/** Catches a render error so one broken panel doesn't blank the whole app.
 *
 *  React unmounts the entire tree when a render throws and nothing catches it,
 *  which turns a small mistake in one page into a white screen with no way
 *  back. This keeps the rest of the app usable and offers a way out.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode; label?: string },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Nothing collects these yet; the console is what a developer has.
    console.error("Render error", this.props.label ?? "", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="mx-auto max-w-lg px-6 py-16 text-center">
        <h1 className="text-[20px] font-extrabold tracking-tight">This page hit an error</h1>
        <p className="mt-2 text-[14px] leading-relaxed text-ink-secondary">
          Nothing was lost. Reload to try again, or go back to the rest of the app.
        </p>
        <p className="mx-auto mt-3 max-w-md truncate text-[12px] text-ink-muted" title={error.message}>
          {error.message}
        </p>
        <div className="mt-6 flex justify-center gap-2">
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            Reload
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => {
              this.setState({ error: null });
              window.location.assign("/");
            }}
          >
            Go home
          </button>
        </div>
      </div>
    );
  }
}
