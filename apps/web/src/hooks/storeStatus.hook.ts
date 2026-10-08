import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "@/core/notify";
import type { HealthResponse, RetailTwinClient } from "@/types/api.type";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";

/** API health and store loaded once per client, plus a SKU lookup form. Failures show as toasts. */
export function useStoreStatus(client: RetailTwinClient) {
  const { t } = useTranslation();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [store, setStore] = useState<StoreResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [sku, setSku] = useState("");
  const [inventory, setInventory] = useState<ProductInventory | null>(null);
  const [lookupPending, setLookupPending] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      const [healthResult, storeResult] = await Promise.allSettled([client.health(), client.store()]);
      if (cancelled) return;

      setHealth(healthResult.status === "fulfilled" ? healthResult.value : null);
      setStore(storeResult.status === "fulfilled" ? storeResult.value : null);

      const failure: unknown =
        healthResult.status === "rejected"
          ? healthResult.reason
          : storeResult.status === "rejected"
            ? storeResult.reason
            : null;
      if (failure) notify.error(t("storeStatus.loadFailed"), failure);
      setLoading(false);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [client, t]);

  async function onLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = sku.trim();
    if (!query) {
      setInventory(null);
      notify.warning(t("storeStatus.enterSku"));
      return;
    }
    setLookupPending(true);
    try {
      setInventory(await client.inventory(query));
    } catch (error) {
      setInventory(null);
      notify.error(t("storeStatus.lookupFailed"), error);
    } finally {
      setLookupPending(false);
    }
  }

  return { health, store, loading, sku, setSku, inventory, lookupPending, onLookup };
}
