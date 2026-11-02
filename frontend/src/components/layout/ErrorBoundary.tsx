import { Component, type ErrorInfo, type ReactNode } from 'react';
import i18n from '@/i18n';

interface State {
  error: Error | null;
}

/** Keeps one broken page from blanking the whole app; resets when the route changes. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('render_error', error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div
        role="alert"
        className="rounded-card border border-danger bg-danger-tint p-4 text-small text-danger"
      >
        <p className="font-semibold">{i18n.t('app.renderError')}</p>
        <p className="mt-1">{i18n.t('app.renderErrorHelp')}</p>
      </div>
    );
  }
}
