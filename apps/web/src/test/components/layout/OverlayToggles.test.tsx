// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { OverlayLegend } from "@/components/layout/OverlayLegend";
import { OverlayToggles } from "@/components/layout/OverlayToggles";
import { OVERLAY } from "@/enums/ui.enum";
import { useUiStore } from "@/state/ui.store";

const at = (url: string) => window.history.replaceState(null, "", url);

function Overlays() {
  return (
    <>
      <OverlayLegend />
      <OverlayToggles />
    </>
  );
}

beforeEach(() => useUiStore.setState(useUiStore.getInitialState(), true));
afterEach(() => {
  cleanup();
  at("/");
});

describe("Overlays", () => {
  it("starts with AI changes on and Stockout risk off, and turns each on or off on its own", () => {
    render(<Overlays />);
    const risk = screen.getByRole("button", { name: "Stockout risk" });
    const changes = screen.getByRole("button", { name: "AI changes" });
    expect(risk.getAttribute("aria-pressed")).toBe("false");
    expect(changes.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(risk);
    expect(risk.getAttribute("aria-pressed")).toBe("true");
    expect(changes.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(changes);
    expect(useUiStore.getState().overlays).toEqual({ [OVERLAY.StockoutRisk]: true, [OVERLAY.AiChanges]: false });
  });

  it("shows the legend only while Stockout risk is on: the four bands and the horizon on the demo", () => {
    at("/?twin=demo");
    render(<Overlays />);
    expect(screen.queryByRole("region", { name: "Stockout risk" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Stockout risk" }));
    const legend = screen.getByRole("region", { name: "Stockout risk" });
    for (const band of ["under 5%", "5–15%", "15–30%", "over 30%"]) expect(legend.textContent).toContain(band);
    expect(legend.textContent).toContain("next 24 h");
    expect(legend.textContent).toContain("Demo forecast, not live store data.");
  });

  it("says on Live that no stockout risk is served yet, with no bands", () => {
    render(<Overlays />);
    fireEvent.click(screen.getByRole("button", { name: "Stockout risk" }));
    const legend = screen.getByRole("region", { name: "Stockout risk" });
    expect(legend.textContent).toContain("Not served on Live yet");
    expect(legend.textContent).not.toContain("under 5%");
  });
});
