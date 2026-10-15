# Demo Video — Shot List

> Resolves #47 — companion to `docs/DEMO_VIDEO.md`.

This file is the per-shot blueprint the editor follows. Twelve shots, 2:55 total,
5 s of slack against the 3:00 cap. Every shot binds to (a) what's on screen, (b)
the voiceover / caption line, (c) the acceptance criterion that proves it, and
(d) which `demo/evidence/` artifact backs it up.

Time codes use the **final encoded MP4** clock, not the live recording clock.
Editor trims producer dumps to these targets before mux.

## Shot-level schema (every row below uses this)

| Field | Meaning |
|---|---|
| **T in / T out** | Time codes in the final MP4 |
| **On screen** | Window the camera is showing |
| **Caption** | On-screen English line (or VO transcript) |
| **Acceptance** | What a reviewer must observe to score this shot PASS |
| **Evidence** | File in `demo/evidence/` that backs the acceptance |

## Shot 01 — Title and URL

- **T in / T out:** `0:00:00` – `0:00:05`
- **On screen:** Title card. Lower third: `RetailTwin AI · Autonomous Store Operator`. URL overlay: `https://retailtwin-ai-511002.web.app`. Background: still frame of the deployed 3D store.
- **Caption:** `RetailTwin AI — Autonomous, context-guarded retail operations.`
- **Acceptance:** The deployed URL is fully legible at 100% zoom on a 13" laptop screen. Title card matches GitHub repo name. No localhost visible anywhere in the frame.
- **Evidence:** `demo/evidence/deployed-urls.txt`; `demo/evidence/screenshots/shot-01.png`.

## Shot 02 — 3D store running, Autopilot ON

- **T in / T out:** `0:00:05` – `0:00:10`
- **On screen:** Browser full-screen, URL bar shows `https://retailtwin-ai-511002.web.app/twin`. The AUTOPILOT pill (top-left of the simulator HUD) is green and reads `ON`. The 3D shelf view is rendered.
- **Caption:** `Autopilot is on. The store is live state. No prompt has been typed.`
- **Acceptance:** Autopilot pill is visible and green at `0:00:08`. The URL bar shows the deployed origin. Producer is **off the keyboard** for the full shot.
- **Evidence:** `demo/evidence/screenshots/shot-02.png` (full screen).

## Shot 03 — Weekend demand spike fires

- **T in / T out:** `0:00:10` – `0:00:20`
- **On screen:** Live event feed panel scrolls a new entry: `Demand surge detected · P017 · velocity +46%`. The shelf for P017 starts visibly empty in the 3D view.
- **Caption:** `A weekend demand spike fires for SKU P017. The system observes it automatically.`
- **Acceptance:** Event entry timestamped and visible. No human prompt text appears in the chat / input area. The 3D shelf for P017 still shows pre-surge allocation at the end of the shot.
- **Evidence:** `demo/evidence/screenshots/shot-03.png`; transcript line from `demo/raw/voiceover-03.wav`.

## Shot 04 — Investigation: evidence + diagnosis

- **T in / T out:** `0:00:20` – `0:00:35`
- **On screen:** Agent Activity panel shows three log rows: `Evidence · shelf qty 8, backroom 54, velocity +46%`, then `Diagnosis · shelf allocation likely insufficient`, then `Tool call · read_inventory(p017)`. The 3D view stays unchanged.
- **Caption:** `The investigator pulls evidence and reads live inventory. Diagnosis: shelf allocation is insufficient.`
- **Acceptance:** All three log rows visible at `0:00:32`. None of them are typed-in prompts; they are tool-call / agent-output lines. The Live Twin is unmodified.
- **Evidence:** `demo/evidence/screenshots/shot-04.png`; `g04-evidence.json` contains `evidence: [...]` for P017.

## Shot 05 — Candidates A / B / C appear

- **T in / T out:** `0:00:35` – `0:00:50`
- **On screen:** Planner panel reveals three candidate cards: `A — keep facings 2`, `B — facings 2→4, replenish +12`, `C — facings 2→6, replenish +24`. One is highlighted as selected by the planner.
- **Caption:** `The planner proposes three candidates — A, B, C — and asks the simulation twin to evaluate each.`
- **Acceptance:** Exactly three cards visible, each with a facings change and a replenishment delta. The selected one is highlighted. Cards are real planner output, not staged.
- **Evidence:** `demo/evidence/screenshots/shot-05.png`.

## Shot 06 — Simulation Twin + KPI compare

- **T in / T out:** `0:00:50` – `0:01:05`
- **On screen:** Simulation Twin panel showing KPI bars for A / B / C: stockout risk, expected lost sales, predicted revenue delta, shelf utilization. B is the leader on stockout risk and revenue.
- **Caption:** `The simulation twin evaluates each candidate. Scenario B wins on stockout risk and revenue.`
- **Acceptance:** KPI bars for all three candidates are visible; B's bars win the listed KPIs. Numbers come from the running simulation, not from a screenshot.
- **Evidence:** `demo/evidence/screenshots/shot-06.png`; `g04-evidence.json.simulation_results`.

## Shot 07 — Stale-context mutation, DCG blocks

- **T in / T out:** `0:01:05` – `0:01:20`
- **On screen:** A toast appears: `Context changed · inventory version N → N+1`. The DCG panel transitions to red and reads `REFRESH_REQUIRED · decision D1 stale`. Below it: `Action · facings 2→4, replenish +12 — NOT authorized`.
- **Caption:** `While the planner is about to commit, context shifts. The Decision Context Guard rejects the now-stale decision. No live mutation occurs.`
- **Acceptance:** Toast and red DCG panel visible. D1 is explicitly refused. No 3D change occurs in this window. The producer's single manual action — the deliberate stale-context mutation — is the **only** hands-on-keyboard moment in the entire video.
- **Evidence:** `demo/evidence/screenshots/shot-07.png`; `demo/evidence/g04-evidence.json` (`decision_ctx_guard.allowed == false` for D1).

## Shot 08 — Auto refresh and replan

- **T in / T out:** `0:01:20` – `0:01:35`
- **On screen:** Agent Activity panel: `Evidence refresh · re-reading inventory at version N+1`, then `Replan · candidate B' built for current context`, then `Tool call · read_inventory(p017)`. The selected card now points at B'.
- **Caption:** `The agent refreshes evidence and replans — automatically, without a human prompt.`
- **Acceptance:** Refreshed evidence row, new decision id, replan row visible. No human clicks trigger any of these.
- **Evidence:** `demo/evidence/screenshots/shot-08.png`; `g04-evidence.json.replan_step` non-null.

## Shot 09 — DCG `ALLOW`, Executor commits

- **T in / T out:** `0:01:35` – `0:01:50`
- **On screen:** DCG panel transitions to green and reads `ALLOW · decision D2 signed for exact actions`. The Authorization panel briefly shows a token. The Executor commit line: `Commit · facings 2→4, replenish +12`.
- **Caption:** `The refreshed decision passes the guard. The executor receives a single-use, short-lived authorization.`
- **Acceptance:** The token is visible only momentarily, is clearly authorization-only (not an API key), and is gone before the next shot. DCG is green, Executor is yellow then green.
- **Evidence:** `demo/evidence/screenshots/shot-09.png`; `g04-evidence.json.decision_ctx_guard.allowed == true` for D2.

## Shot 10 — Live 3D change

- **T in / T out:** `0:01:50` – `0:02:05`
- **On screen:** Same camera angle as Shot 02. The shelf for P017 visibly changes: facings increase from 2 to 4, replenishment units arrive, the backroom count updates. A subtle "version N+1" badge appears in the corner.
- **Caption:** `Facings move from 2 to 4. Replenishment of 12 units arrives. Live twin version increments.`
- **Acceptance:** The 3D rendering visibly changes within the shot window. Side-by-side comparison between Shot 02 end frame and Shot 10 end frame must show the difference.
- **Evidence:** `demo/evidence/screenshots/shot-10-before.png`, `demo/evidence/screenshots/shot-10-after.png`.

## Shot 11 — Verifier reports `PASS`

- **T in / T out:** `0:02:05` – `0:02:20`
- **On screen:** Verifier panel: `Verification · PASS · KPI match within tolerance · no policy violation`. Agent Activity shows the latest log row.
- **Caption:** `Verification passes. The autonomous action was provably correct against live state.`
- **Acceptance:** Verifier panel reads `PASS`. The full pipeline log is visible on the right.
- **Evidence:** `demo/evidence/screenshots/shot-11.png`; `g04-evidence.json.verifier == "PASS"`.

## Shot 12 — Architecture credibility + close

- **T in / T out:** `0:02:30` – `0:02:55` (the slack 2:20–2:30 is intentional headroom)
- **On screen:** Architecture card: `Gemini · Agent Development Kit`, then `Cloud Run · Firestore · Pub/Sub`, then `Decision Context Guard (No-Stale-Commit)`. Final title card with deployed URL and the closing line.
- **Caption:** `Built on Gemini and Google Cloud. The Decision Context Guard makes every autonomous action provably current at commit time. RetailTwin AI — see it at retailtwin-ai-511002.web.app.`
- **Acceptance:** Each pillar is named once. Closing URL is the same deployed origin as Shot 01. Final shot lands at ≤ `2:55:00`.
- **Evidence:** `demo/evidence/screenshots/shot-12.png`; `demo/evidence/timing.txt` final duration ≤ 180 s and ≤ 175 s recommended.

## Aggregate acceptance for the take

The whole take is `PASS` only if every shot above is `PASS`. The final encoder
output is in `demo/retailtwin-demo.mp4` and the SRT is in
`demo/retailtwin-demo.srt`. Refer to
[`acceptance-criteria.md`](acceptance-criteria.md) for the formal grader pass.
