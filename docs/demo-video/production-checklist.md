# Demo Video — Production Checklist

> Resolves #47. The pre-flight / per-take / post-flight checklist the producer
> ticks, in order, before the PR for #47 opens.

This file is intentionally procedural. Each item is a row in a single long
checklist. Ticking it is binary; the next row depends on the previous one being
ticked.

## 0. Pre-recording (≤ 1 hour before)

- [ ] Branch `issue/47-demo-video-runbook` is up to date with `main` (`git pull --ff-only`)
- [ ] Cloud Run revision is the expected tagged SHA (`gcloud run revisions list --service retailtwin-api --region us-central1 --project retailtwin-ai-511002`)
- [ ] Firebase Hosting release matches (`firebase hosting:releases:list --site retailtwin-ai-511002 --project retailtwin-ai-511002`)
- [ ] The four curl probes in `docs/DEMO_VIDEO.md` §2 all return 200 + correct CORS header
- [ ] Chrome bookmarks bar hidden, extensions off, full screen, dark/light theme matches plan
- [ ] OBS / Loom scene is set to 1920×1080 at 30 fps, audio input is the chosen mic
- [ ] macOS Do Not Disturb on, notifications off, screen lock disabled for the take window
- [ ] Director's seat has sight line to the deployed URL bar
- [ ] `scripts/record_demo_video.sh --help` shows current flags
- [ ] `demo/evidence/` exists and is empty
- [ ] Producer's hands are off the keyboard for the run; only the single deliberate stale-context mutation in shot 7 is human-triggered

## 1. Take 0 (test take, do not keep)

- [ ] Run `scripts/record_demo_video.sh --scenario weekend-demand-surge --duration 180 --evidence-dir demo/evidence --take test`
- [ ] Confirm the deterministic scenario controller reaches each shot on time
- [ ] Confirm screenshots land in `demo/evidence/screenshots/`
- [ ] Confirm G04 evidence file lands in `demo/evidence/g04-evidence.json`
- [ ] Discard the take's MP4 if one was produced

## 2. Take 1 (recording)

- [ ] Producer presses Record in OBS / Loom
- [ ] `scripts/record_demo_video.sh --scenario weekend-demand-surge --duration 180 --evidence-dir demo/evidence --take 1` runs without error
- [ ] Producer types nothing; the only deliberate mutation lands in shot 7
- [ ] Take finishes cleanly; OBS / Loom produces `demo/raw/screen-1.mkv`
- [ ] Voiceover takes recorded: `demo/raw/voiceover-01.wav` … `voiceover-12.wav`
- [ ] Producer presses Stop; recording saved

## 3. Editor assembly

- [ ] `demo/raw/screen-1.mkv` is muxed with `demo/raw/voiceover.wav` per shot-list.md
- [ ] Final cut lands at ≤ 2:55 (`ffprobe` confirms)
- [ ] Captions written to `demo/retailtwin-demo.srt`, aligned ±0.5 s per shot
- [ ] Output file written to `demo/retailtwin-demo.mp4`, ≤ 100 MB
- [ ] Encode settings: H.264 yuv420p, AAC, faststart, 30 fps

## 4. Take-N acceptance (per `docs/demo-video/acceptance-criteria.md`)

- [ ] §A J-01 … J-12 — every row is PASS
- [ ] §B G-01 — `g04-evidence.json` exists, `pass == true`
- [ ] §B G-02 — G04 evidence shape includes run_id, git_sha, decision_ids, guard_audit, live_twin_diff
- [ ] §B G-03 — `g06-summary.txt` shows 20/20 passes
- [ ] §B G-04 — deployed URLs still answer; CORS header present
- [ ] §B G-05 — `ffprobe` shows H.264 + AAC + ≤ 180 s + ≤ 100 MB
- [ ] §B G-06 — `.srt` has exactly 12 cues

## 5. Take-N evidence packaging

- [ ] `demo/retailtwin-demo.mp4` (≤ 100 MB)
- [ ] `demo/retailtwin-demo.srt`
- [ ] `demo/evidence/g04-evidence.json`
- [ ] `demo/evidence/g06-summary.txt`
- [ ] `demo/evidence/deployed-urls.txt`
- [ ] `demo/evidence/env.txt`
- [ ] `demo/evidence/timing.txt`
- [ ] `demo/evidence/take-record.json` filled per §E of acceptance-criteria.md
- [ ] `demo/evidence/screenshots/shot-01.png` … `shot-12.png`
- [ ] `demo/README.md` records producer, date, git SHA, signed off by two reviewers

## 6. Pre-merge sweep

- [ ] `grep -RE 'BEGIN PRIVATE KEY|127\.0\.0\.1|localhost' demo/` returns nothing
- [ ] `ffprobe demo/retailtwin-demo.mp4 2>&1 | grep Duration` shows ≤ 180 s
- [ ] `wc -c demo/retailtwin-demo.mp4` shows ≤ 100 MB
- [ ] `wc -l demo/retailtwin-demo.srt` shows 12 cues plus headers
- [ ] Take-record JSON's `overall` is `PASS`
- [ ] Two reviewers signed off in `demo/README.md`

## 7. PR for #47

- [ ] PR title: `[I13][P0] Demo video production runbook and acceptance criteria (resolves #47)`
- [ ] PR body uses `.github/PULL_REQUEST_TEMPLATE.md`
- [ ] PR body has `Closes #47`
- [ ] PR body lists every `demo/evidence/` file
- [ ] PR reviewer pings the integration owner (issue #47 labels: `role:integration`)
- [ ] PR reviewer is **not** the producer

## 8. Failure handling

- [ ] If a single shot fails: see §D of `docs/demo-video/acceptance-criteria.md`
- [ ] If J-06 / J-07 / J-08 fail: full retake, do not edit over the failure
- [ ] All failure decisions are appended to `demo/evidence/<date>-failure.md` (gitignored)

## 9. Final gate (post-merge)

- [ ] Production build is updated: `scripts/deploy-cloudrun.sh` if API revision needs to change
- [ ] Hosting release id matches the one recorded in `demo/evidence/env.txt`
- [ ] At least one demo viewer outside the producer team watched the final MP4 and signed off
- [ ] The video is mirrored at the team's shared drive (URL recorded in `demo/README.md`)
