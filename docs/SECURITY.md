# Security model

- GitHub webhook bodies are validated with HMAC-SHA256.
- Human authority is derived from GitHub repository collaborator permission.
- READ and SAFE_WRITE may run automatically according to policy.
- RISKY_WRITE requires explicit approval by a sufficiently privileged GitHub user.
- DESTRUCTIVE is denied by default even if a user attempts approval.
- Free-text comments never authorize side effects.
- OpenClaw specialist prompts constrain investigation profiles to read-only work.
- Ambiguous writes are never blindly retried.
- S7 verification is independent of recovery execution.

For production, also enable OpenClaw sandbox/tool allowlists appropriate to each profile and restrict the recovery responder's credentials to the minimum required scope.
