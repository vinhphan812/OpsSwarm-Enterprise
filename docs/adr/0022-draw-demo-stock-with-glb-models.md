# 0022. Draw demo stock with GLB models, primitives as the fallback

Date: 2026-10-13

## Status

Accepted

## Context

ADR 0002 drew every entity as colored primitives and said the app does not import GLB, glTF, or Blender files. That kept the scaffold small, but stock read as boxes and balls: a jar, a can, and an oil bottle looked the same. Issue #29 asks for GLB assets behind a primitive fallback toggle, with hit boxes and entity ids unchanged and no regression in load or frame rate.

Twin state carries no product looks, so a model can only be picked on the FE. Stock is drawn as one instanced mesh per primitive shape, and the item layout (cells, counts, capacity) is what `unitsDrawn`, the overflow checks, and the move tween read.

Alternatives considered:

- Replace fixtures (gondolas, coolers, checkouts) with GLBs too. Their procedural parts carry selection glow, status lights, and wall hiding; swapping them is a larger change for less gain. Left for later.
- `useGLTF` with `Suspense`. A suspended stock would hide the whole store until every model loaded, and one bad file would fail the batch. Loading outside React, with each model settled on its own, keeps the scene up.
- Draco or meshopt compression. The models are about 450 KB together (Snackies 205 KB with a 1024² WebP atlas); a decoder costs more than it saves.
- Simplifying the meshes (meshoptimizer). At a ratio that helped, it broke these flat-shaded models (holes, loose triangles), so the pack is used as shipped.

## Decision

Stock is drawn with low-poly GLB models from Snackies (printed packaging) and Kenney's Food Kit (CC0), served from `apps/web/public/models/`. `stock/models.ts` lists the named demo catalog's models and the surface kinds each may stand on; any other product takes a model, or its primitive, from its surface's pool by its id. A model is fitted, in its own proportions, into the cell its primitive would fill, so the item layout is unchanged. Models load once per page, after the scene is up, and each one that fails is left out. `?assets=primitive` turns them off. Fixtures stay primitives. This replaces only the "does not import GLB" sentence of ADR 0002; its id rules stand.

## Consequences

- Stock reads as products. Counts, places, hit boxes, ids, selection, halos, and the move tween behave as before.
- The SKU-to-model map and the pools are presentation, like the colors picked by id. When the twin serves product looks, they should come from there.
- `GLTFLoader` (14 KB gzip) is a lazy chunk; the first bundle grows by about 2 KB.
- Each loaded model adds one instanced draw (and one more while selected or flagged).
- Pull request:
- Issue: https://github.com/vinhphan812/retailtwin-ai/issues/29
- Supersedes: ADR 0002, in part (GLB imports)
- Superseded by:
