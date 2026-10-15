# Demo Video — Acceptance Criteria

> Resolves #47. Companion to `docs/DEMO_VIDEO.md` and `shot-list.md`.

This is the formal grader pass. Every criterion below must be `PASS` before the
PR for #47 is mergeable. Each criterion lists: what is being checked, how it is
checked, the evidence file or command that proves it, and the explicit failure
mode that disqualifies a take.

The criteria map onto two audiences. Section A is what a **judge sees**. Section
B is what the **gate runner proves**. Section C is what the **producer verifies**
before opening the PR. Section D is the failing-take protocol.

## A. Judge-visible criteria (the on-screen bar)

| ID | Criterion | How a reviewer checks | Disqualifying failure |
|---|---|---|---|
| J-01 | Duration ≤ 3:00 on the final MP4 | Hover the file, see `<= 2:55`. Or open in player and read the duration | Final MP4 > 3:00 → take retake or trim |
| J-02 | Deployed URL shown at 0:05 | Look at title card | `localhost`, `127.0.0.1`, blank |
| J-03 | AUTOPILOT ON visible at 0:08 | Look at HUD | Pill is red/off at the time of the shot |
| J-04 | Demand spike timestamped for P017 | Read the agent log | Untyped or "demo" string |
| J-05 | Three candidate cards (A/B/C) at 0:40 | Count them | Fewer than three, or only one |
| J-06 | DCG `REFRESH_REQUIRED` shown within `1:15 ± 2 s` | Read the panel | Decision D1 commits and the world changes |
| J-07 | DCG `ALLOW` shown within `1:40 ± 2 s` | Read the panel | The replacement decision never makes it to the panel |
| J-08 | Live 3D change visible between `1:50` and `2:05` | Watch the shelf | No visible change. Same shelf as shot 02 |
| J-09 | Verifier `PASS` at `2:15 ± 2 s` | Read the panel | `FAIL` or invisible |
| J-10 | No manual prompt starts the core flow | Watch the input area for any human-typed text | A prompt is typed by the producer mid-take |
| J-11 | Captions align with audio / on-screen within ±0.5 s | Watch with `.srt` | Any line off by > 0.5 s |
| J-12 | No secrets on screen or in audio | Auditory sweep + visual sweep | Token, service-account JSON, raw HTTP header |

## B. Gate-runner criteria (the system test)

| ID | Criterion | Command / file | Pass bar |
|---|---|---|---|
| G-01 | G04 stale-context guard | `python tests/e2e/gates/g04_guard_gate.py --out demo/evidence/g04-evidence.json` | exit 0, `pass == true`, `decision_ctx_guard.allowed` is `false` for D1 and `true` for D2 |
| G-02 | G04 evidence shape | `jq '.run_id, .git_sha, .decision_ids, .guard_audit, .live_twin_diff' demo/evidence/g04-evidence.json` | All keys present, sha matches the recording's HEAD |
| G-03 | G06 full submission | `scripts/verify-cloud-preflight.sh` | 20/20 runs PASSED, streak unbroken |
| G-04 | Deployed origin is `retailtwin-ai-511002.web.app` and the API is the Cloud Run URL | the four probes from `docs/DEMO_VIDEO.md` §2 | status codes 200/200/200/200 + correct CORS header on the API |
| G-05 | Final MP4 audio + video streams present and within size budget | `ffprobe -show_streams -show_format demo/retailtwin-demo.mp4` | one H.264, one AAC, ≤ 100 MB, ≤ 180 s |
| G-06 | Captions file present and well-formed | `grep -c ' --> ' demo/retailtwin-demo.srt` | exactly 12 cues, one per shot |

## C. Producer pre-merge criteria (the PR bar)

| ID | Criterion | Status before opening PR |
|---|---|---|
| P-01 | `demo/retailtwin-demo.mp4` exists and is ≤ 100 MB | Required |
| P-02 | `demo/retailtwin-demo.srt` exists with 12 cues | Required |
| P-03 | `demo/evidence/g04-evidence.json` exists and `pass == true` | Required |
| P-04 | `demo/evidence/g06-summary.txt` records ≥ 20 consecutive runs | Required |
| P-05 | `demo/evidence/deployed-urls.txt` captured at recording time | Required |
| P-06 | `demo/evidence/env.txt` lists the API revision and Hosting release id used during recording | Required |
| P-07 | `demo/evidence/timing.txt` matches `ffprobe` of the final MP4 | Required |
| P-08 | `demo/evidence/screenshots/` has `shot-01.png` … `shot-12.png` | Required |
| P-09 | `demo/README.md` records producer name, date, git SHA | Required |
| P-10 | No file under `demo/` contains `BEGIN PRIVATE KEY`, `127.0.0.1`, `localhost`, or service-account JSON | `grep -RE 'BEGIN PRIVATE KEY|127\.0\.0\.1|localhost' demo/` |
| P-11 | All twelve shots have evidence backing in `demo/evidence/screenshots/` | Required |

## D. Failing-take protocol

A take fails if **any** of J-01 … J-12 is `FAIL`, **any** of G-01 … G-06 is
`FAIL`, or **any** of P-01 … P-11 is missing. The protocol:

1. Stop the recording immediately. Do not edit over a failing take.
2. Run the gate runner for the suspicious criterion. Record the result in
   `demo/evidence/<date>-failure.md` (gitignored).
3. Decide: trim, retake single shot, or retake entire video.
   - **Trim:** only allowed if the failure is duration overrun (J-01) and the
     editor can cut without losing a required shot.
   - **Retake single shot:** allowed only if J-04 / J-05 / J-09 / J-11 fail.
   - **Retake entire video:** required if J-06 / J-07 / J-08 fail because the
     stale-context proof is the centerpiece of the submission.
4. Re-run all of Section B; re-run `scripts/verify-cloud-preflight.sh`.
5. Update `demo/README.md` with the new attempt number and the diff vs the
   previous attempt.

## E. Pass / fail record template

Each take records a `demo/evidence/take-record.json`:

```json
{
  "issue": 47,
  "attempt": 1,
  "git_sha": "<recording commit>",
  "frontend_origin": "https://retailtwin-ai-511002.web.app",
  "api_origin": "https://retailtwin-api-537192856637.us-central1.run.app",
  "duration_seconds": 174.5,
  "judges": {"J-01": "PASS", "J-02": "PASS", "...": "..."},
  "gates":  {"G-01": "PASS", "...": "..."},
  "producer": {"name": "...", "date": "YYYY-MM-DD"},
  "overall": "PASS"
}
```

The PR for #47 is not mergeable unless `overall == "PASS"`.

## F. Sign-off

The producer and one second reviewer both sign off by appending to
`demo/README.md`:

```text
- <reviewer>, <date>: reviewed every criterion in §A and §B; all PASS
```

Two sign-offs are required before the PR can be merged to `main`.
