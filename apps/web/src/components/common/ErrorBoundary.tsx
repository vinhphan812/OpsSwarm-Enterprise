import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@heroui/react";
import i18n from "@/i18n";
import { RetryIcon } from "@/components/icons";

type ErrorBoundaryProps = {
  children: ReactNode;
  fallback?: ReactNode | ((error: Error, reset: () => void) => ReactNode);
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
};

type ErrorBoundaryState = {
  hasError: boolean;
  error: Error | null;
};

/**
 * Catches rendering and integration runtime errors safely, displaying a fallback UI
 * with retry controls and accessible feedback.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
    error: null,
  };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.props.onError?.(error, errorInfo);
  }

  resetErrorBoundary = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError && this.state.error) {
      if (typeof this.props.fallback === "function") {
        return this.props.fallback(this.state.error, this.resetErrorBoundary);
      }
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div className="flex flex-col items-center justify-center min-h-[200px] p-6 text-center bg-content1 rounded-lg border border-divider shadow-sm">
          <h2 className="text-lg font-semibold text-danger mb-2">
            {i18n.t("twin.loadFailed")}
          </h2>
          <p className="text-sm text-ink-muted mb-4 max-w-md">
            {this.state.error.message || i18n.t("errors.unknown")}
          </p>
          <Button
            color="primary"
            onPress={this.resetErrorBoundary}
            startContent={<RetryIcon className="h-4 w-4" />}
          >
            {i18n.t("twin.retry")}
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
