"""A hash-chained, append-only decision ledger.

Every material act of the committee — forecasts, orders, vetoes,
resolutions — is appended here with a content hash that includes the hash
of the previous entry. This makes the audit trail tamper-evident: any
retcon of past reasoning breaks the chain, which `verify()` detects.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

GENESIS = "0" * 64


def _canonical_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class LedgerEntry:
    seq: int
    ts: str
    kind: str                 # e.g. "forecast", "order", "veto", "resolution", "note"
    as_of: str
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str = ""

    def __post_init__(self) -> None:
        if not self.entry_hash:
            self.entry_hash = _canonical_hash({
                "seq": self.seq, "ts": self.ts, "kind": self.kind,
                "as_of": self.as_of, "payload": self.payload,
                "prev_hash": self.prev_hash,
            })


class DecisionLedger:
    """Append-only in-memory ledger with JSONL persistence and verification."""

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []
        self._seq = 0

    def append(self, kind: str, as_of: date, payload: dict[str, Any]) -> LedgerEntry:
        prev = self.entries[-1].entry_hash if self.entries else GENESIS
        self._seq += 1
        entry = LedgerEntry(
            seq=self._seq,
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            kind=kind,
            as_of=as_of.isoformat(),
            payload=payload,
            prev_hash=prev,
        )
        self.entries.append(entry)
        return entry

    @property
    def head_hash(self) -> str:
        return self.entries[-1].entry_hash if self.entries else GENESIS

    def verify(self) -> tuple[bool, Optional[str]]:
        """Recompute the chain. Returns (ok, first_bad_reason)."""
        prev = GENESIS
        for e in self.entries:
            if e.seq <= 0:
                return False, f"bad seq {e.seq}"
            if e.prev_hash != prev:
                return False, f"entry {e.seq}: prev_hash mismatch (chain broken)"
            expect = _canonical_hash({
                "seq": e.seq, "ts": e.ts, "kind": e.kind,
                "as_of": e.as_of, "payload": e.payload,
                "prev_hash": e.prev_hash,
            })
            if e.entry_hash != expect:
                return False, f"entry {e.seq}: content hash mismatch (tampered)"
            prev = e.entry_hash
        return True, None

    # ---- persistence -------------------------------------------------
    def to_jsonl(self, path: str) -> None:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for e in self.entries:
                f.write(json.dumps(asdict(e), sort_keys=True) + "\n")

    @classmethod
    def from_jsonl(cls, path: str) -> "DecisionLedger":
        ledger = cls()
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                row["entry_hash"] = row.pop("entryHash", row.get("entry_hash", ""))
                entry = LedgerEntry(**row)
                ledger.entries.append(entry)
                ledger._seq = entry.seq
        ok, why = ledger.verify()
        if not ok:
            raise ValueError(f"ledger integrity failure: {why}")
        return ledger
