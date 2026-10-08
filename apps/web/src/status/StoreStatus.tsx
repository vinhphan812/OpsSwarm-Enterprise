import { useEffect, useState, type FormEvent } from "react";
import { defaultClient } from "../api/client";
import type { HealthResponse, ProductInventory, RetailTwinClient, StoreResponse } from "../api/types";
import "./StoreStatus.css";

type StoreStatusProps = {
  client?: RetailTwinClient;
};

export function StoreStatus({ client = defaultClient }: StoreStatusProps) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [store, setStore] = useState<StoreResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sku, setSku] = useState("");
  const [inventory, setInventory] = useState<ProductInventory | null>(null);
  const [inventoryError, setInventoryError] = useState<string | null>(null);
  const [lookupPending, setLookupPending] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      const [healthResult, storeResult] = await Promise.allSettled([client.health(), client.store()]);
      if (cancelled) return;

      if (healthResult.status === "fulfilled") {
        setHealth(healthResult.value);
      } else {
        setHealth(null);
      }
      if (storeResult.status === "fulfilled") {
        setStore(storeResult.value);
      } else {
        setStore(null);
      }

      let failure: unknown = null;
      if (healthResult.status === "rejected") {
        failure = healthResult.reason;
      } else if (storeResult.status === "rejected") {
        failure = storeResult.reason;
      }
      if (failure instanceof Error) {
        setLoadError(failure.message);
      } else if (failure) {
        setLoadError("The API request failed.");
      } else {
        setLoadError(null);
      }
      setLoading(false);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [client]);

  async function onLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = sku.trim();
    if (!query) {
      setInventory(null);
      setInventoryError("Enter a SKU.");
      return;
    }
    setLookupPending(true);
    setInventoryError(null);
    try {
      setInventory(await client.inventory(query));
    } catch (error) {
      setInventory(null);
      setInventoryError(error instanceof Error ? error.message : "Inventory lookup failed.");
    } finally {
      setLookupPending(false);
    }
  }

  return (
    <section className="store-status">
      <h2>Store API</h2>
      <p className="store-status-note">Reads come from the API. This column does not change live inventory.</p>

      {loading ? <p>Loading store…</p> : null}
      {loadError ? (
        <p role="alert" className="store-status-error">
          {loadError}
        </p>
      ) : null}
      {health ? (
        <p>
          API {health.status} · {health.environment} · {health.store_id}
        </p>
      ) : null}

      {store ? (
        <>
          <h2>{store.store_id}</h2>
          <p>
            Context {store.context_version} · version {store.version}
          </p>
          <div className="store-status-table">
            <table>
              <thead>
                <tr>
                  <th scope="col">SKU</th>
                  <th scope="col">Shelf</th>
                  <th scope="col">Slot</th>
                  <th scope="col">Facings</th>
                  <th scope="col">On shelf</th>
                  <th scope="col">Backroom</th>
                </tr>
              </thead>
              <tbody>
                {store.products.map((item) => (
                  <tr key={item.sku}>
                    <td>
                      <span className="store-status-label">SKU</span>
                      {item.sku}
                    </td>
                    <td>
                      <span className="store-status-label">Shelf</span>
                      {item.shelf_id}
                    </td>
                    <td>
                      <span className="store-status-label">Slot</span>
                      {item.slot_id}
                    </td>
                    <td>
                      <span className="store-status-label">Facings</span>
                      {item.facings}
                    </td>
                    <td>
                      <span className="store-status-label">On shelf</span>
                      {item.shelf_quantity}
                    </td>
                    <td>
                      <span className="store-status-label">Backroom</span>
                      {item.backroom_quantity}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      <form className="store-status-lookup" onSubmit={onLookup}>
        <label htmlFor="sku">SKU</label>
        <input
          id="sku"
          name="sku"
          value={sku}
          onChange={(event) => setSku(event.target.value)}
          autoComplete="off"
        />
        <button type="submit" disabled={lookupPending}>
          {lookupPending ? "Looking up…" : "Look up inventory"}
        </button>
      </form>
      {inventoryError ? (
        <p role="alert" className="store-status-error">
          {inventoryError}
        </p>
      ) : null}
      {inventory ? (
        <p>
          {inventory.sku} on {inventory.shelf_id} / {inventory.slot_id}: {inventory.shelf_quantity} on shelf,{" "}
          {inventory.backroom_quantity} in the backroom.
        </p>
      ) : null}
    </section>
  );
}
