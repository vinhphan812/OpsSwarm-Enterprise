from __future__ import annotations


class FakeGitHub:
    def __init__(self,
                 issue): self.issue = issue; self.comments = []; self.labels = []; self.closed = []; self.created = []; self.permissions = {
        "dev": "maintain", "reader": "read"}

    async def get_issue(self, n): return self.issue

    async def comment(self, n, body): self.comments.append((n, body)); return {"id": len(self.comments)}

    async def set_labels(self, n, labels): self.labels = list(labels); return labels

    async def close_issue(self, n): self.closed.append(n); return {}

    async def create_issue(self, title, body, labels): self.created.append((title, body, labels)); return {
        "number": 900 + len(self.created)}

    async def permission(self, u): return self.permissions.get(u, "none")


class FakeOpenClaw:
    def __init__(self, responses):
        self.responses = list(responses);
        self.calls = []

    async def run_json(self, agent, session, prompt):
        self.calls.append((agent, session, prompt))
        if not self.responses: raise AssertionError("No fake response left")
        r = self.responses.pop(0)
        if isinstance(r, Exception): raise r
        return r
