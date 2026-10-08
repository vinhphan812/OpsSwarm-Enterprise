import type { ProductInventory } from "@/types/twin.type";
import apiFixture from "../../../../data/schemas/store-state.example.json";

/** P001 as `GET /store` serves it from the API's day-0 fixture. */
export const FIXTURE_P001: ProductInventory = { ...apiFixture.products[0], store_id: apiFixture.store_id, version: 1 };
