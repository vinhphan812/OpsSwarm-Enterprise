// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { AiChangesList } from "@/components/twin/AiChangesList";
import { aiChanges } from "@/core/twin/aiChanges";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useUiStore } from "@/state/ui.store";

const live = demoStoreState();
const changes = aiChanges(live, demoSimulation(live).state);

beforeEach(() => useUiStore.setState(useUiStore.getInitialState(), true));
afterEach(cleanup);

it("lists each group with its rows, as the diff has them", () => {
  render(<AiChangesList changes={changes} />);
  const region = screen.getByRole("region", { name: "AI changes" });
  expect(within(region).getByText("5 changes")).toBeTruthy();
  const rows = (group: string) =>
    within(screen.getByRole("list", { name: group }))
      .getAllByRole("button")
      .map((row) => row.textContent);
  expect(rows("Moved")).toEqual(["P005A03-S22 → B01-S22", "P007B02-S20 → B02-S22", "P008C01-S21 → A02-S22"]);
  expect(rows("Facings")).toEqual([`P004${changes.facings[0].before} → 4`]);
  expect(rows("Replenished")).toEqual([`P003${changes.replenished[0].before} → ${changes.replenished[0].after}`]);
});

it("selects the product of a row, so the camera flies to it", () => {
  render(<AiChangesList changes={changes} />);
  fireEvent.click(screen.getByRole("button", { name: "P007, Moved B02-S20 → B02-S22. Show it in 3D" }));
  expect(useUiStore.getState()).toMatchObject({ selectedEntityId: "P007", selectedEntityType: ENTITY_TYPE.Product });
});

it("shows nothing without a change", () => {
  const { container } = render(<AiChangesList changes={aiChanges(live, live)} />);
  expect(container.innerHTML).toBe("");
  render(<AiChangesList changes={null} />);
  expect(screen.queryByRole("region", { name: "AI changes" })).toBeNull();
});
