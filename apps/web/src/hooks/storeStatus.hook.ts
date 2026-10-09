import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import { notify } from "@/core/notify";
import type { HealthResponse, RetailTwinClient } from "@/types/api.type";
import type { ProductInventory } from "@/types/twin.type";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { useTwinStore } from "@/state/twin.store";

const healthLoads = new WeakMap<RetailTwinClient, Promise<HealthResponse | null>>();
const healthLoaded = new WeakMap<RetailTwinClient, HealthResponse>();

/**
 * `GET /health`, read once per client and shared by every mount, so reopening the
 * Operations lens does not call the API again. A failed read is dropped and retried
 * on the next mount; its toast shows once.
 */
function loadHealth(client: RetailTwinClient): Promise<HealthResponse | null> {
  let load = healthLoads.get(client);
  if (!load) {
    load = client.health().then(
      (health) => {
        healthLoaded.set(client, health);
        return health;
      },
      (error: unknown) => {
        healthLoads.delete(client);
        notify.error(i18n.t("storeStatus.loadFailed"), error);
        return null;
      },
    );
    healthLoads.set(client, load);
  }
  return load;
}

/**
 * API health (read once per client), the live store the scene already polls from
 * `GET /store`, and a SKU lookup form. Failures show as toasts.
 */
export function useStoreStatus(client: RetailTwinClient) {
  const { t } = useTranslation();
  const store = useTwinStore((state) => state.live);
  const storeLoading = useTwinStore((state) => state.status === TWIN_STATUS.Loading);
  const [health, setHealth] = useState<HealthResponse | null>(() => healthLoaded.get(client) ?? null);
  const [loading, setLoading] = useState(() => !healthLoaded.has(client));
  const [sku, setSku] = useState("");
  const [inventory, setInventory] = useState<ProductInventory | null>(null);
  const [lookupPending, setLookupPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void loadHealth(client).then((result) => {
      if (cancelled) return;
      setHealth(result);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [client]);

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

  return { health, store, loading: loading || storeLoading, sku, setSku, inventory, lookupPending, onLookup };
}
