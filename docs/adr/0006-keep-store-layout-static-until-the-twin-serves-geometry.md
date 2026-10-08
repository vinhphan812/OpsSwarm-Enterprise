# 0006. Keep the store layout static until the twin serves geometry

Date: 2026-10-08

## Status

Proposed

## Context

Issue #4 binds the 3D scene to Live Twin state. Its Definition of Done asks that no static or mock data decide where a product appears. `GET /store` (ADR 0003, `apps/api`) returns products with `shelf_id`, `slot_id`, facings, and stock, but no geometry: no position or turn for shelves, equipment, or slots. Nothing serves geometry yet.

Options considered:

- **Wait for the backend to serve geometry.** Blocks issue #4 on backend work that is not scheduled.
- **Use the per-product `position` from docs/DOMAIN_AND_DATA_MODEL.md.** Places products without the shelves and slots they belong to, so the scene would disagree with the `Store → Zone → Shelf → Slot → Product` hierarchy.
- **Keep the layout of shelves, equipment, and slots in the web app, and take product placement from the twin.** The twin decides which slot a product is in; the web app decides where that slot is drawn.

## Decision

The web app keeps the store layout (shelf and equipment positions, turns, and slot ids) as code in `apps/web/src/fixtures/storeFixture.ts`, exposed through `storeLayout` in `apps/web/src/scene/layout.ts`. Which slot a product occupies, its facings, and its stock come only from twin state. A product whose `shelf_id` or `slot_id` is not in the layout is not drawn and is reported on screen.

## Consequences

- Moving a product between slots, changing facings, or changing stock in the twin shows in the scene without a web change.
- Adding, moving, or renumbering a shelf needs a web change, and the backend must use the same shelf and slot ids. The layout is the reference for valid `slot_id` values until the backend serves it.
- Slot ids are positional (`<shelf_id>-S01`, `-S02`, …, counted across the fixture's display surfaces); changing a fixture's surfaces renumbers its slots.
- When the backend serves layout, `toSceneStore` takes shelves, equipment, and slots from state, and a new ADR supersedes this one.
- Pull request:
- Issue: https://github.com/vinhphan812/retailtwin-ai/issues/4
- Supersedes:
- Superseded by:
