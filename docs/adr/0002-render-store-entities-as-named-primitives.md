# 0002. Render store entities as named primitives

Date: 2026-10-07

## Status

Accepted

## Context

Issue #3 needs a runnable 3D store before later issues can show merchandising actions. `apps/web` had no application, only a responsibility note. Issue #4 will bind one product to Live Twin state, and issues #23–#25 will move, resize, and replenish products in the scene. Those issues need a stable way to find a shelf, slot, or product in the scene graph.

The control-loop and tool contracts in issue #1 are still open. Scene coordinates therefore cannot be treated as canonical twin state. The machine available for this scaffold runs Node 20.17, and the current Vite 7/8 plus React Three Fiber 9 line requires Node 20.19 and React 19.

The scene is a view. It must not gain a path that writes Live Twin state.

## Decision

`apps/web` is a Vite + React + TypeScript application. The store scene uses React Three Fiber 8 and Drei 9 on React 18 and Three r170, which install and build on Node `>=20.17`.

The scene is right-handed and Y-up. Units are meters. The floor top lies on the XZ plane at `y = 0`. The camera orbits the store center and does not pan. Its distance fits the shelf bounds to the canvas aspect ratio. There is no character and no walk control.

Each Store, Shelf, Slot, and Product object sets both `name` and `userData.entityId` to the domain id (`store-001`, `A01`, `A01-S01`, `P001`, and so on) and sets `userData.entityType`. Geometry is colored primitives. The app does not import GLB, glTF, or Blender files.

Positions for this scaffold come from `apps/web/src/scene/storeFixture.ts`. Issue #4 replaces that fixture with twin state through one adapter and keeps this id attachment rule. The web app does not write store state.

## Consequences

- Later issues can find an entity by id on the scene graph.
- A future API position field is converted in one adapter. Mesh components keep reading one local position.
- Upgrading to React Three Fiber 9 waits on a Node runtime that satisfies Vite 7 or newer.
- The Agent Activity column is reserved layout. It does not yet show the agent timeline.
- Issue #3's scene can be reviewed without a live backend. It does not prove that geometry follows Live Twin state. That proof is issue #4.
- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/56
- Issue: https://github.com/vinhphan812/retailtwin-ai/issues/3
- Supersedes:
- Superseded by: [0022](0022-draw-demo-stock-with-glb-models.md), in part: stock may be drawn with GLB models
