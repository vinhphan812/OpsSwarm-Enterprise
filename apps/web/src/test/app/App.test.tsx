// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { notify } from "@/core/notify";
import { App } from "@/app/App";

vi.mock("@/core/notify", () => ({
  errorMessage: (error: unknown) => (error instanceof Error ? error.message : String(error)),
  notify: { error: vi.fn(), warning: vi.fn(), success: vi.fn() },
}));

vi.mock("@/scene/StoreScene", () => ({
  StoreScene: () => null,
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("the app shows an API failure without crashing", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new TypeError("offline");
    }),
  );

  render(<App />);

  await waitFor(() => {
    expect(notify.error).toHaveBeenCalledWith(
      "The API request failed.",
      expect.objectContaining({ message: "The API is unreachable." }),
    );
  });
  expect(screen.getByRole("heading", { name: "Agent Activity" })).toBeTruthy();
  expect(screen.getByRole("main")).toBeTruthy();
  expect(screen.getByRole("textbox", { name: "SKU" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Look up inventory" })).toBeTruthy();
});
