// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";

vi.mock("./scene/StoreScene", () => ({
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

  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "The API is unreachable.");
  expect(screen.getByRole("heading", { name: "Agent Activity" })).toBeTruthy();
  expect(screen.getByRole("main")).toBeTruthy();
  expect(screen.getByRole("textbox", { name: "SKU" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Look up inventory" })).toBeTruthy();
});
