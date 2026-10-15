import { beforeEach, expect, test } from "vitest";
import { demoAnomalies } from "@/fixtures/demo/anomalies";
import { useAnomalyStore } from "@/state/anomaly.store";

beforeEach(() => useAnomalyStore.setState({ anomalies: [], readError: null }));

test("a failed read keeps the last list and records why; the next good read clears it", () => {
  const response = demoAnomalies();
  useAnomalyStore.getState().setAll(response);

  useAnomalyStore.getState().fail("GET /anomalies returned 503.");
  expect(useAnomalyStore.getState().readError).toBe("GET /anomalies returned 503.");
  expect(useAnomalyStore.getState().anomalies).toEqual(response.anomalies);

  useAnomalyStore.getState().setAll({ ...response, anomalies: [] });
  expect(useAnomalyStore.getState()).toMatchObject({ anomalies: [], readError: null });
});
