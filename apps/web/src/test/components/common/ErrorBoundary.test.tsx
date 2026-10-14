// @vitest-environment jsdom
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";

afterEach(() => {
  cleanup();
});

function ThrowingComponent({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error("Test explosion");
  }
  return <div>Healthy content</div>;
}

describe("ErrorBoundary", () => {
  it("renders children when there is no error", () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Healthy content")).toBeDefined();
  });

  it("catches errors and renders fallback UI with retry", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const onError = vi.fn();
    const { rerender } = render(
      <ErrorBoundary onError={onError}>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(onError).toHaveBeenCalled();
    expect(screen.getByText("Test explosion")).toBeDefined();
    const retryButton = screen.getByRole("button", { name: /try again/i });
    expect(retryButton).toBeDefined();

    // Reset error state by re-rendering with shouldThrow = false and clicking retry
    rerender(
      <ErrorBoundary onError={onError}>
        <ThrowingComponent shouldThrow={false} />
      </ErrorBoundary>,
    );

    fireEvent.click(retryButton);
    expect(screen.getByText("Healthy content")).toBeDefined();
    consoleError.mockRestore();
  });
});
