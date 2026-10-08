import type { StoreResponse } from "@/core/api/types";
import storeState from "./store-001.state.json";

/**
 * Mock `GET /store` response for store-001: the store with empty shelves. Dev only,
 * never Live Twin truth. Products come from the API.
 */
export const mockStoreState: StoreResponse = storeState;
