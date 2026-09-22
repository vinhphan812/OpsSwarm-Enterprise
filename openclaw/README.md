# OpenClaw binding

OpsSwarm uses the documented Gateway-backed CLI turn:

```bash
openclaw agent --agent <agent-id> --session-key <key> --message-file <file> --json
```

The repository supplies seven agent workspaces and eight Skills. Edit the absolute repository path in `openclaw.patch.json5`, then:

```bash
openclaw config patch --file openclaw/openclaw.patch.json5 --dry-run
openclaw config patch --file openclaw/openclaw.patch.json5
openclaw config validate
openclaw gateway start
openclaw agents list
```

OpsSwarm intentionally does not use a second harness or runtime adapter.
