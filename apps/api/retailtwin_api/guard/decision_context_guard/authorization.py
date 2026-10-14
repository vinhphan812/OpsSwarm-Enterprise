"""Short-lived, signed commit authorization for exactly one allowed decision.

A token names the decision, its context hash, the hash of each action in
order, the live versions the commit may assume, a one-time nonce and an
expiry. It is signed with HMAC-SHA256. The ledger lets each nonce be consumed
once, so a token cannot be replayed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from retailtwin_api.contracts import Decision
from retailtwin_api.guard.decision_context_guard.hashing import action_hash
from retailtwin_api.guard.decision_context_guard.no_stale_commit import CommitBinding

SIGNING_KEY_ENV = "RETAILTWIN_COMMIT_SIGNING_KEY"
TOKEN_TTL_ENV = "RETAILTWIN_COMMIT_TOKEN_TTL_SECONDS"
DEFAULT_TTL = timedelta(seconds=30)

MISSING_TOKEN = "MISSING_TOKEN"
INVALID_SIGNATURE = "INVALID_SIGNATURE"
TOKEN_EXPIRED = "TOKEN_EXPIRED"
TOKEN_REUSED = "TOKEN_REUSED"
UNKNOWN_TOKEN = "UNKNOWN_TOKEN"
ACTION_MISMATCH = "ACTION_MISMATCH"


class AuthorizationError(Exception):
    """A commit authorization was refused. ``code`` is one of the constants above."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SigningKeyMissing(Exception):
    """No signing key is configured, so no authorization can be issued."""


class SignedAuthorization(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str
    store_id: str
    context_hash: str
    action_hashes: tuple[str, ...]
    entity_versions: dict[str, int]
    nonce: str
    issued_at: datetime
    expiry: datetime
    signature: str = ""

    def binding(self) -> CommitBinding:
        return CommitBinding(
            decision_id=self.decision_id,
            store_id=self.store_id,
            context_hash=self.context_hash,
            entity_versions=dict(self.entity_versions),
            expiry=self.expiry,
        )

    def signing_payload(self) -> bytes:
        body = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


class AuthorizationLedger(Protocol):
    def issue(self, nonce: str, expiry: datetime) -> None: ...

    def consume(self, nonce: str) -> str | None:
        """Mark ``nonce`` used. Return None, or why it cannot be used."""

    def revoke(self, nonce: str) -> None: ...


class InMemoryAuthorizationLedger:
    """Process-memory nonce ledger. Tokens never outlive the process that issued them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: dict[str, datetime] = {}
        self._closed: set[str] = set()

    def issue(self, nonce: str, expiry: datetime) -> None:
        with self._lock:
            self._open[nonce] = expiry

    def consume(self, nonce: str) -> str | None:
        with self._lock:
            if nonce in self._closed:
                return TOKEN_REUSED
            if nonce not in self._open:
                return UNKNOWN_TOKEN
            del self._open[nonce]
            self._closed.add(nonce)
            return None

    def revoke(self, nonce: str) -> None:
        with self._lock:
            self._open.pop(nonce, None)
            self._closed.add(nonce)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommitAuthorizer:
    """Issue and verify signed commit authorizations."""

    def __init__(
        self,
        signing_key: bytes | None,
        ledger: AuthorizationLedger,
        ttl: timedelta = DEFAULT_TTL,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._key = signing_key
        self._ledger = ledger
        self._ttl = ttl
        self._clock = clock

    @classmethod
    def from_env(
        cls,
        ledger: AuthorizationLedger,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> CommitAuthorizer:
        env = os.environ if environ is None else environ
        raw_key = env.get(SIGNING_KEY_ENV, "").strip()
        raw_ttl = env.get(TOKEN_TTL_ENV, "").strip()
        ttl = DEFAULT_TTL
        if raw_ttl:
            if not raw_ttl.isdigit() or int(raw_ttl) < 1:
                raise ValueError(f"{TOKEN_TTL_ENV} must be a positive integer.")
            ttl = timedelta(seconds=int(raw_ttl))
        return cls(raw_key.encode("utf-8") if raw_key else None, ledger, ttl, clock)

    @property
    def can_issue(self) -> bool:
        return self._key is not None

    def issue(self, decision: Decision, binding: CommitBinding) -> SignedAuthorization:
        """Authorize exactly ``decision``'s actions against ``binding``. Fails closed without a key."""

        if self._key is None:
            raise SigningKeyMissing(f"{SIGNING_KEY_ENV} is not set.")
        if decision.decision_id != binding.decision_id:
            raise AuthorizationError(ACTION_MISMATCH, "The binding is for another decision.")
        now = self._clock()
        unsigned = SignedAuthorization(
            decision_id=binding.decision_id,
            store_id=binding.store_id,
            context_hash=binding.context_hash,
            action_hashes=tuple(action_hash(action) for action in decision.proposed_actions),
            entity_versions=dict(binding.entity_versions),
            nonce=secrets.token_hex(16),
            issued_at=now,
            expiry=min(now + self._ttl, binding.expiry),
        )
        token = unsigned.model_copy(update={"signature": self._sign(unsigned)})
        self._ledger.issue(token.nonce, token.expiry)
        return token

    def redeem(self, decision: Decision, token: SignedAuthorization | None) -> CommitBinding:
        """Check ``token`` for exactly ``decision`` and consume it.

        Order: present, signature, expiry, decision and actions, then the
        nonce. A token that fails after its signature checks is revoked so it
        cannot be tried again.
        """

        if token is None:
            raise AuthorizationError(MISSING_TOKEN, "No commit authorization was given.")
        if self._key is None or not hmac.compare_digest(token.signature, self._sign(token)):
            raise AuthorizationError(INVALID_SIGNATURE, "The commit authorization signature is invalid.")
        if self._clock() > token.expiry:
            self._ledger.revoke(token.nonce)
            raise AuthorizationError(TOKEN_EXPIRED, "The commit authorization expired.")
        actions = tuple(action_hash(action) for action in decision.proposed_actions)
        if token.decision_id != decision.decision_id or token.action_hashes != actions:
            self._ledger.revoke(token.nonce)
            raise AuthorizationError(ACTION_MISMATCH, "The actions differ from the authorized actions.")
        refusal = self._ledger.consume(token.nonce)
        if refusal is not None:
            raise AuthorizationError(refusal, "The commit authorization cannot be used again.")
        return token.binding()

    def _sign(self, token: SignedAuthorization) -> str:
        assert self._key is not None
        return hmac.new(self._key, token.signing_payload(), hashlib.sha256).hexdigest()
