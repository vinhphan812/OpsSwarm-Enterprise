# RetailTwin AI — Demo Video Production Runbook

> Resolves #47 — `[I13][P0] Produce final demo video under 3 minutes`

This document is the authoritative runbook for producing the flagship 3-minute demo
video submitted as the primary evaluation artifact for RetailTwin AI. It defines the
target, the storyboard, the recording procedure, the acceptance gates, and the
evidence packaging. Capture the production by following this runbook step by step.

## 1. Goal and constraints

| Constraint | Target |
|---|---|
| **Audience** | Competition judges evaluating autonomy + guarded execution, not architecture |
| **Duration** | Strictly **≤ 2:55** (leaves headroom under the 3:00 cap) |
| **Language** | English (on-screen captions or voiceover) |
| **Storyline** | Autopilot ON → demand spike → investigation → candidates → simulation → stale-context block → automatic refresh/replan → DCG PASS → live 3D change → verification |
| **Surface shown** | Deployed product only — no `localhost`, no `127.0.0.1`, no fixture-only backend |
| **No manual trigger** | No human prompt, no CLI command, no DB write starts the core flow. Everything happens because Autopilot is `ON` and the deterministic scenario fires |
| **Submission artifact** | One MP4 (`demo/retailtwin-demo.mp4`) plus one evidence bundle (`demo/evidence/`) |

The video must prove a single point:

> RetailTwin AI does not just let AI manage a store. It guarantees that every
> autonomous action is still valid at the exact moment it reaches the live store.

## 2. Deployed product (the surface shown)

Use the currently live deployment. Capture versions before recording and embed them
in the video's lower-third overlay.

| Component | URL |
|---|---|
| Web (3D Live Twin + UI) | `https://retailtwin-ai-511002.web.app` |
| API | `https://retailtwin-api-537192856637.us-central1.run.app` |
| Health probe | `GET ${API_ORIGIN}/health` |
| Store probe | `GET ${API_ORIGIN}/store` |

Confirmation before you press Record (≤ 30 s):

```bash
FRONTEND_ORIGIN="https://retailtwin-ai-511002.web.app"
API_ORIGIN="https://retailtwin-api-537192856637.us-central1.run.app"

curl --fail --show-error --silent --head "${FRONTEND_ORIGIN}/"
curl --fail --show-error --silent "${API_ORIGIN}/health"
curl --fail --show-error --silent "${API_ORIGIN}/store"

curl --fail --show-error --silent --dump-header - --output /dev/null \
  --header "Origin: ${FRONTEND_ORIGIN}" "${API_ORIGIN}/health"
```

Both API responses must include `access-control-allow-origin: ${FRONTEND_ORIGIN}`.
If any probe fails, do not record. Fix the deployment first (see
`docs/deploy-web.md`, `docs/deploy.md`, and `scripts/deploy-cloudrun.sh`).

## 3. Scenario and tooling references

| Reference | Path | Used for |
|---|---|---|
| Storyline | `docs/DEMO_AND_ACCEPTANCE.md` §2 | 3-minute story spine |
| Demo flow | `docs/demo/README.md` | Flagship scenario checklist |
| Stale-context gate (G04) | `docs/DEMO_AND_ACCEPTANCE.md` §4 | The DCG block + auto-replan moment |
| Submission acceptance gate (G06) | `docs/DEMO_AND_ACCEPTANCE.md` §6 | 20 consecutive clean runs |
| Architecture | `docs/ARCHITECTURE.md` | 15-second credibility moment |

The deterministic scenario controller behind the video is the production
scenario mode described in `docs/DEMO_AND_ACCEPTANCE.md` §3. It controls timing,
seeds, the deliberate stale-context mutation, and the reset; it does **not**
fake Gemini tool calls, Firestore state, the Simulation Twin, the DCG result,
Executor mutations, or verification — those are real for every shot.

## 4. Storyboard (3 minutes, 12 shots)

The full shot-by-shot breakdown lives in
[`docs/demo-video/shot-list.md`](demo-video/shot-list.md). Each shot lists
duration, on-screen content, audio/caption text, and the acceptance criterion
that proves it. Headline timings below; details in the shot list.

| # | Shot | Duration | Demo Timeline |
|---|---|---:|---|
| 1 | Title + deployed URL overlay | 0:05 | `0:00–0:05` |
| 2 | 3D store running, AUTOPILOT ON, no prompt | 0:05 | `0:05–0:10` |
| 3 | Weekend demand spike for P017 fires | 0:10 | `0:10–0:20` |
| 4 | Agent Activity: evidence + diagnosis | 0:15 | `0:20–0:35` |
| 5 | Candidate A / B / C appear | 0:15 | `0:35–0:50` |
| 6 | Simulation Twin + KPI compare | 0:15 | `0:50–1:05` |
| 7 | Context mutation; DCG blocks stale decision | 0:15 | `1:05–1:20` |
| 8 | Auto refresh evidence + replan | 0:15 | `1:20–1:35` |
| 9 | DCG `ALLOW`, Executor commits | 0:15 | `1:35–1:50` |
| 10 | Live 3D shelf/facings/replenishment change | 0:15 | `1:50–2:05` |
| 11 | Verifier reports `PASS` | 0:15 | `2:05–2:20` |
| 12 | Architecture cred + close | 0:25 | `2:30–2:55` |
|   | **Total headroom** | **0:05** | ends at **2:55** |

Shot 12 budget is consumed as: 15 s architecture credibility card, 5 s closing
statement, 5 s title/URL end card. Total hard cap: 2:55.

## 5. Tools and capture setup

Choose one recording path per producer preference. Whichever you pick, the
**output is committed under `demo/`** as described in §6.

### 5.1 Tooling matrix

| Layer | Recommended | Fallback | Required output |
|---|---|---|---|
| Screen video | OBS Studio (lossless, 30 fps, 1920×1080) | Loom (Mac), QuickTime Player | `demo/raw/screen.mkv` or `.mov` |
| Audio (VO) | Audacity + USB lav mic | Built-in mic in quiet room | `demo/raw/voiceover.wav` 48 kHz mono |
| Browser | Chrome (latest stable), `--disable-gpu` off, hardware accel on | Firefox | — |
| Stale-context control | `tests/e2e/gates/g04_guard_gate.py` | `python` direct API call | `demo/evidence/g04-evidence.json` |
| Timing reference | `scripts/record_demo_video.sh` | Manual stopwatch | `demo/evidence/timing.txt` |
| Edit | DaVinci Resolve (free), Final Cut, Premiere | `ffmpeg` trim only | `demo/retailtwin-demo.mp4` |
| Captions | Hand-drawn `.srt` from shot list | Whisper transcription | `demo/retailtwin-demo.srt` |

### 5.2 Capture environment checklist

- 1920×1080 display, 100% scaling
- 30 fps, constant (or 60 fps if plan A; 30 fps encodes smaller)
- Chrome: `chrome://flags/#enable-gpu-rasterization` → Enabled
- Chrome DevTools: Network throttling `No throttling`, CPU throttling `No throttling`
- Hide bookmarks bar, hide all extensions, full-screen the 3D view (`F`)
- OS: notifications off, Do Not Disturb on, dark/light theme consistent
- Browser zoom 100% on the URL bar so judges can read the overlay
- The deterministic scenario controller runs the demo; no human clicks anywhere
  except the **single deliberate stale-context mutation** in shot 7

## 6. Output and storage

```
demo/
├── retailtwin-demo.mp4         # the deliverable (≤ 3:00, 1080p)
├── retailtwin-demo.srt         # English captions
├── README.md                   # producer sign-off + access notes
├── raw/                        # discardable source material (gitignored)
│   ├── screen.mkv
│   ├── voiceover.wav
│   └── edits.nls
└── evidence/                   # auditable proof of every shot
    ├── g04-evidence.json       # from scripts/verify-cloud-preflight.sh or API
    ├── timing.txt              # per-shot start/end timestamps vs shot-list.md
    ├── g06-summary.txt         # ≥ 20 consecutive runs PASSED
    ├── deployed-urls.txt       # the four probes from §2 with status codes
    ├── env.txt                 # git SHA, API revision, Hosting release id
    └── screenshots/            # one PNG per shot for documentation
```

The final MP4 stays under 100 MB to keep submission upload reasonable. Encode:

```bash
ffmpeg -i raw/screen.mkv -i raw/voiceover.wav \
  -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 160k -ar 48000 -ac 2 -movflags +faststart \
  -shortest demo/retailtwin-demo.mp4
```

If a hosting location outside the repo is required (e.g. competition portal),
mirror the MP4 to both:

- `demo/retailtwin-demo.mp4` inside the repo (signed off via PR)
- The team's shared drive URL recorded in `demo/README.md`

## 7. Recording procedure (run start to finish)

```bash
# 1. Pre-flight (deploy reachable, scenario controller seeded)
scripts/verify-cloud-preflight.sh            # g04 evidence already captured here
gcloud run revisions list \
  --service retailtwin-api --region us-central1 \
  --project retailtwin-ai-511002 > demo/evidence/env.txt

# 2. Hit Record (OBS / Loom). Producer does NOT touch keyboard after this
#    point. The deterministic scenario controller drives everything.
scripts/record_demo_video.sh \
  --scenario weekend-demand-surge \
  --stale-mutation-at 75s \
  --duration 180 \
  --out demo/raw/screen.mkv

# 3. Voiceover is recorded separately so timing can be tweaked in edit:
#    - one take per shot (12 takes)
#    - filenames: demo/raw/voiceover-01.wav ... voiceover-12.wav
#    - silent VO is acceptable; on-screen captions are mandatory regardless.

# 4. Edit assembly per shot-list.md; relock timings to the file timestamps.
ffmpeg -i demo/raw/screen.mkv -i demo/raw/voiceover.wav \
  -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 160k -movflags +faststart \
  demo/retailtwin-demo.mp4

# 5. Truth-check the encoded output against §8.
ffprobe -hide_banner -show_entries format=duration,duration_ts \
  demo/retailtwin-demo.mp4 | tee demo/evidence/timing.txt
```

The recording script `scripts/record_demo_video.sh` (see §10) automates steps 2
and 5. It does not record video itself; the producer's OBS / Loom captures
the desktop while the script drives the deterministic scenario.

## 8. Acceptance gates (the bar a recording must clear)

Detailed checks live in
[`docs/demo-video/acceptance-criteria.md`](demo-video/acceptance-criteria.md).
The summary bar a take must clear before sign-off:

- [ ] **Duration** — `ffprobe` reports ≤ 3:00 (target 2:55) on the final MP4.
- [ ] **Deployed surface** — the URL bar shows `retailtwin-ai-511002.web.app` at
      any 0:05 sample between 0:00 and 0:30.
- [ ] **No manual prompt** — producer hands are off keyboard from 0:10 until
      the deliberate stale-context mutation in shot 7. Recording logs prove this.
- [ ] **Autopilot ON** — the AUTOPILOT pill is visible at 0:05 and stays green.
- [ ] **Stale-context block** — `REFRESH_REQUIRED` is visible on screen at 1:15
      (±2 s) and `ALLOW` at 1:40 (±2 s).
- [ ] **Live 3D change** — between 1:50 and 2:05 the shelf/facings/replenishment
      state changes on screen (compare screenshots pre/post).
- [ ] **Verifier PASS** — the verifier panel reads `PASS` at 2:15 (±2 s).
- [ ] **G04 evidence** — `demo/evidence/g04-evidence.json` exists and has
      `decision_ctx_guard.allowed == false` for the stale decision and `true`
      for the replacement.
- [ ] **G06 evidence** — `demo/evidence/g06-summary.txt` records ≥ 20
      consecutive clean runs.
- [ ] **No secrets** — the audio track, captions, and screen never surface
      tokens, service-account JSON, or `127.0.0.1`.
- [ ] **Captions** — every caption line aligns with its shot within ±0.5 s.

## 9. Evidence packaging (mandatory before merge)

A PR is not mergeable until `demo/evidence/` is complete. Each artifact is
named in §6; each is generated by a single command listed below.

| Artifact | Generator | Pass criterion |
|---|---|---|
| `g04-evidence.json` | `tests/e2e/gates/g04_guard_gate.py --out demo/evidence/g04-evidence.json` | exit 0, `pass == true` |
| `g06-summary.txt` | the G06 loop summarized by `scripts/verify-cloud-preflight.sh` | 20/20 passes |
| `deployed-urls.txt` | the four `curl` probes in §2 | 200/200/200/200 + CORS header |
| `env.txt` | `gcloud run revisions list` + `firebase hosting:releases:list` | one current revision per side |
| `screenshots/` | manual saves during recording | one PNG per shot, named `shot-NN.png` |
| `timing.txt` | `ffprobe` of the final MP4 | duration ≤ 3:00 |

## 10. Automation script

`scripts/record_demo_video.sh` provides a single entry point for the producer.
It wires the deterministic scenario controller to the recording window, captures
screenshots per shot, exports timing metadata, and re-runs the verification
probes so every artifact lands in `demo/evidence/`. See the script's header
docstring for usage.

Usage:

```bash
# Full automated take: drives the scenario, saves evidence, leaves recording to OBS.
scripts/record_demo_video.sh \
  --frontend-url https://retailtwin-ai-511002.web.app \
  --api-url      https://retailtwin-api-537192856637.us-central1.run.app \
  --scenario     weekend-demand-surge \
  --duration     180 \
  --evidence-dir demo/evidence
```

The script never fakes backend output. It only orchestrates. Producer still
presses Record in OBS at the prompt and stops on the prompt.

## 11. PR / submission checklist

This is the bar the PR for #47 must clear:

- [ ] `docs/DEMO_VIDEO.md` (this file) updated
- [ ] `docs/demo-video/shot-list.md` filled in with the chosen screen
      capture plan
- [ ] `docs/demo-video/acceptance-criteria.md` references the actual
      evidence artifacts in `demo/evidence/`
- [ ] `docs/demo-video/production-checklist.md` ticked for every shot
- [ ] `scripts/record_demo_video.sh` present, executable, and verified
      by a dry run on the deployed surface
- [ ] `demo/retailtwin-demo.mp4` ≤ 3:00 (target 2:55)
- [ ] `demo/retailtwin-demo.srt` aligns within ±0.5 s of shot list
- [ ] `demo/evidence/` complete: `g04-evidence.json`, `g06-summary.txt`,
      `deployed-urls.txt`, `env.txt`, `timing.txt`, `screenshots/`
- [ ] `demo/README.md` records producer, date, Git revision
- [ ] PR body uses the template in `.github/PULL_REQUEST_TEMPLATE.md`,
      references `Closes #47`, and lists every `demo/evidence/` file
- [ ] No tokens, no service-account JSON, no localhost in any frame or caption

## 12. Failure paths to exercise (refresher for the team)

The following failure paths must be covered by the underlying gates (G04/G06),
not faked in the demo. They are referenced here so the producer knows what to
say if a judge asks:

- duplicate Pub/Sub event
- missing mandatory evidence
- malformed/forbidden tool call
- stale context (the one shown on camera)
- expired commit authorization
- altered action after authorization
- insufficient inventory
- shelf capacity violation
- backend/tool timeout
- post-action verification mismatch

## 13. Cross-references

- Issue: #47
- Storyline: `docs/DEMO_AND_ACCEPTANCE.md`
- Demo flow: `docs/demo/README.md`
- Shot list: `docs/demo-video/shot-list.md`
- Acceptance: `docs/demo-video/acceptance-criteria.md`
- Production checklist: `docs/demo-video/production-checklist.md`
- Recording script: `scripts/record_demo_video.sh`
- Deploy docs: `docs/deploy.md`, `docs/deploy-web.md`
- Cloud preflight: `scripts/verify-cloud-preflight.sh`
