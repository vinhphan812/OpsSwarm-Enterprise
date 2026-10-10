import ReactThreeTestRenderer from "@react-three/test-renderer";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { TwinStoreContents } from "@/scene/StoreScene";
import { sceneOf } from "@/scene/layout";
import { VIEW_MODE } from "@/enums/ui.enum";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { demoAnomalies } from "@/fixtures/demo/anomalies";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useAnomalyStore } from "@/state/anomaly.store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

type Renderer = Awaited<ReturnType<typeof ReactThreeTestRenderer.create>>;

const slotOf = (renderer: Renderer, sku: string) => renderer.scene.instance.getObjectByName(sku)?.parent?.name;
const halos = (renderer: Renderer) => {
  const names: string[] = [];
  renderer.scene.instance.traverse((object) => {
    if (object.name.startsWith("stock-anomaly-")) names.push(object.name);
  });
  return names;
};

describe("the scene in the Live and Simulation views", () => {
  const live = demoStoreState();
  let renderer: Renderer | undefined;

  beforeEach(() => {
    useTwinStore.setState({ ...useTwinStore.getInitialState(), live, status: TWIN_STATUS.Ready }, true);
    useTwinStore.getState().setSimulation(demoSimulation(live));
    useAnomalyStore.getState().setAll(demoAnomalies(live));
    useUiStore.getState().setViewMode(VIEW_MODE.Live);
  });

  afterEach(async () => {
    await renderer?.unmount();
    renderer = undefined;
    useAnomalyStore.setState({ anomalies: [] });
  });

  it("the demo simulation places every product", () => {
    expect(sceneOf(demoSimulation().state).issues).toEqual([]);
  });

  it("draws Live in the Live view, the proposal in the Simulation view, and Live again after", async () => {
    renderer = await ReactThreeTestRenderer.create(<TwinStoreContents interactive={false} />);
    expect(slotOf(renderer, "P007")).toBe("B02-S20");
    expect(halos(renderer).length).toBeGreaterThan(0);

    await ReactThreeTestRenderer.act(async () => useUiStore.getState().setViewMode(VIEW_MODE.Simulation));
    expect(slotOf(renderer, "P007")).toBe("B02-S22");
    expect(halos(renderer)).toEqual([]);
    expect(useTwinStore.getState().live).toBe(live);

    await ReactThreeTestRenderer.act(async () => useUiStore.getState().setViewMode(VIEW_MODE.Live));
    expect(slotOf(renderer, "P007")).toBe("B02-S20");
  });
});
