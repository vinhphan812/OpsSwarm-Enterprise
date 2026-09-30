# Evidence storage and verification

Evidence is stored as append-only JSONL files at:

    <data-dir>/evidence/<run-id>.jsonl

Each run also has a retained lock sentinel at `<run-id>.lock`. The lock uses
`msvcrt.locking` on Windows and `fcntl.flock` on POSIX. It covers reload,
deduplication, chain-signature calculation, append/fsync, and in-memory index
updates. The sentinel is not evidence and must not be deleted while a process
may be writing; stale sentinels are safe to retain because locks release when
file handles close.

Distinct evidence records are never removed by deduplication. Idempotency only
skips records with the same configured payload signature; records with distinct
signatures remain in the hash chain.

Run an independent verification without starting the service:

    opsswarm evidence verify <run-id> --data-dir <data-dir>

Exit codes are deterministic:

* 0: `PASS` and a valid chain
* 1: `FAIL` and one or more verification errors (including missing files,
  malformed JSON, malformed record shapes, or chain breaks)
* 2: command-line usage error

Retention and deletion remain deployment responsibilities. Removing a JSONL
file makes verification fail closed; deleting or reordering lines is detected
by chain verification.
