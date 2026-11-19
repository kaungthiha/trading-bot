import { Component, type ErrorInfo, type ReactNode } from "react";

interface State { error: Error | null }

/** A render error in one view shows a message instead of blanking the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("View crashed:", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="warning-box">
          <strong>This view hit an error and was stopped.</strong>{" "}
          <span className="small">{this.state.error.message}</span>{" "}
          <button type="button" className="link-button" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
