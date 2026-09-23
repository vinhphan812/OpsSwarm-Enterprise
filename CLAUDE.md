# AGENTS.md — OpsSwarm Enterprise

AI coding assistant instructions for this codebase. Place in the project root. Supported by Cursor,
Claude Code, GitHub Copilot (agent mode), Windsurf, Aider, and Continue.dev.

---

## Project Overview

OpsSwarm Enterprise v2.1.0 coordinates governed multi-agent incident response:

- **OpenClaw** is the AI reasoning/execution runtime.
- **GitHub Issues** are the human control surface (one issue = one incident).
- **GitHub Issue comments** are the only human input/decision channel.
- **OpsSwarm S1-S8** (in `skills/`) form the governed control plane.
- **opsswarm/** modules contain all production logic; **tests/** contains all test suites.

Architecture principles (from `README.md`):

1. OpenClaw is the only AI/agent runtime.
2. One GitHub Issue = one incident = one OpsSwarm run.
3. GitHub Issue comments are the only human decision channel.
4. S1-S8 form the governed control plane.
5. Investigation is read-only by default.
6. Agent recommendations are not execution authority.
7. Risky writes require an explicit authorized GitHub command (`/opsswarm approve`).
8. Free-text comments never authorize side effects.
9. Ambiguous writes are never blindly retried.
10. S7 (observe-verify) must independently verify recovery before the issue closes.

---

## Environment and Commands

### Setup

```bash
pip install -e '.[dev]'         # runtime + dev tools
pip install -e '.[release]'    # add build + SBOM tools
```

### Testing

```bash
make test          # all tests + coverage (fail_under=90)
make test-unit    # unit tests only
pytest -q         # quick run
pytest tests/unit/skill_s1/  # per-skill tests
```

### Quality gates

```bash
make ci           # lint + typecheck + test + coverage + build
make lint        # ruff check
make typecheck   # mypy
make coverage     # pytest-cov (fails below 90%)
make build       # build wheel
```

### Skills (S1-S8)

Skill logic is in `opsswarm/skill_logic.py`. Test suites are in `tests/unit/skill_s{1-8}/`.
Skill metadata is in `skills/sN-*/SKILL.md` (frontmatter: `name` + `description` only, per ADR-006).

Do not add `scripts/`, `resources/`, or `tests/` directories inside `skills/sN-*/`.
Runtime logic lives in `opsswarm/`, not scattered across skill folders (per ADR-011).

### Python version

`>=3.11`. Package name: `opsswarm-openclaw-github`.

---

## Coding Standards

- **Language:** Python 3.11+
- **Formatting:** Ruff (`ruff format`), line length 100
- **Linting:** Ruff (`ruff check`) -- rules E9, F63, F7, F82 initially
- **Type checking:** MyPy with `ignore_missing_imports = true`
- **Testing:** pytest, `asyncio_mode = auto`, pytest-asyncio, pytest-cov
- **Pytest markers:** `unit`, `integration`, `security`, `normal`, `boundary`, `fault`,
  `cross_skill`, `contract`, `e2e`, `smoke`
- **Coverage threshold:** 90% (`fail_under = 90`)

---

## Boundaries and Warnings

### Never do

- Never commit secrets, credentials, or tokens. `.env` is gitignored.
- Never use `git reset --hard` or `git push --force` without explicit user approval.
- Never modify `openclaw/workspaces/*/` (OpenClaw-managed).
- Never rename symbols with find-and-replace -- use a tool that understands the call graph.
- Never edit a function, class, or method before running impact analysis.

### Restricted paths

- `openclaw/workspaces/*/` -- OpenClaw-managed, do not edit
- `.env`, `runtime-data/`, `artifacts/` -- generated or local-only
- `opsswarm_openclaw_github.egg-info/` -- build artifact, gitignored
- `.github/workflows/` -- changes may affect CI; validate syntax before committing

### Commit conventions

- One logical change per commit.
- Message format: `type: short description (#issue)`.
- Never commit without running `make ci` first.
- All modified/new files must pass lint, typecheck, and tests.

---

## Documentation Standards

- Project documentation is in English (UK) -- no mixed-language text.
- ADRs are in `docs/adr/` (indexed in `docs/adr/README.md`).
- Operational guides are in `docs/guides/`.
- Audit reports are in `docs/audits/`.
- Triage working documents are in `docs/triage/historical/`.
- No local filesystem paths in committed documentation. Use repository URLs or relative paths.

---

<!-- gitnexus:start -->

# GitNexus -- Code Intelligence

This project is indexed by GitNexus as **OpsSwarm-Enterprise** (2284 symbols, 4099 relationships, 55 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root -- it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` -- e.g. `bunx gitnexus@latest analyze`.

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check -- a zero means unseen, not unaffected; re-run it. For regression review: `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- **MUST warn on HIGH/CRITICAL `risk` pre-edit.** Never use `riskSharedAxes` to waive a HIGH/CRITICAL risk warning.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** Confirm with a text search before treating the symbol as safe to change or delete.

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace -- use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource                                             | Use for                                  |
| ---------------------------------------------------- | ---------------------------------------- |
| `gitnexus://repo/OpsSwarm-Enterprise/context`        | Codebase overview, check index freshness |
| `gitnexus://repo/OpsSwarm-Enterprise/clusters`       | All functional areas                     |
| `gitnexus://repo/OpsSwarm-Enterprise/processes`      | All execution flows                      |
| `gitnexus://repo/OpsSwarm-Enterprise/process/{name}` | Step-by-step execution trace             |

## CLI

| Task                                         | Skill file                                         |
| -------------------------------------------- | -------------------------------------------------- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md`       |
| Blast radius / "What breaks if I change X?"  | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?"             | `.claude/skills/gitnexus-debugging/SKILL.md`       |
| Rename / extract / split / refactor          | `.claude/skills/gitnexus-refactoring/SKILL.md`     |
| Tools, resources, schema reference           | `.claude/skills/gitnexus-guide/SKILL.md`           |
| Index, status, clean, wiki CLI commands      | `.claude/skills/gitnexus-cli/SKILL.md`             |

<!-- gitnexus:end -->
