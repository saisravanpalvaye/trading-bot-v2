#!/usr/bin/env python3
"""
verify_closed_trades.py

Guard against silent corruption of trade history (the root cause of the
June 5 2026 merge-conflict incident, where 33 real trades were wiped and
16 correctly-closed trades were reverted to 'open' and re-processed with
stale data).

Rule: once a trade's status is 'closed' in the last COMMITTED version of
paper_trades.csv, none of its outcome fields may change in the NEW version
about to be committed. A closed trade's outcome is a historical fact.

Usage (from repo root, inside a git working tree):
    python verify_closed_trades.py

Exit code 0  -> safe to commit
Exit code 1  -> BLOCKED, prints exactly which rows/fields changed

This is designed to be run as a CI step BEFORE `git commit`, using the
file currently on disk (working tree) vs. HEAD (last commit).
"""

import csv
import subprocess
import sys

FILE = "paper_trades.csv"

# Fields that must never change once a trade is closed.
IMMUTABLE_FIELDS = [
    "status", "exit_date", "exit_price", "exit_reason",
    "partial_exit_price", "partial_exit_date", "partial_pnl",
    "pnl", "result", "days_held",
]


def load_csv_text(text):
    reader = csv.DictReader(text.splitlines())
    return {row["id"]: row for row in reader if row.get("id")}


def get_committed_version():
    """Return dict of {id: row} for paper_trades.csv as of last commit (HEAD)."""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{FILE}"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        # No committed version yet (first commit ever) -> nothing to protect.
        return {}
    return load_csv_text(result.stdout)


def get_working_version():
    with open(FILE, newline="", encoding="utf-8") as f:
        return load_csv_text(f.read())


def main():
    old = get_committed_version()
    new = get_working_version()

    if not old:
        print("No committed baseline found — first commit, nothing to check.")
        return 0

    violations = []

    for trade_id, old_row in old.items():
        if old_row.get("status") != "closed":
            continue  # only closed trades are protected

        new_row = new.get(trade_id)
        if new_row is None:
            violations.append(f"{trade_id}: existed as CLOSED in last commit, "
                               f"missing entirely in new version.")
            continue

        for field in IMMUTABLE_FIELDS:
            old_val = (old_row.get(field) or "").strip()
            new_val = (new_row.get(field) or "").strip()
            if old_val != new_val:
                violations.append(
                    f"{trade_id}: field '{field}' changed on a CLOSED trade "
                    f"({old_val!r} -> {new_val!r})"
                )

    if violations:
        print("BLOCKED — closed-trade history would be mutated by this commit:")
        print("-" * 70)
        for v in violations:
            print(f"  {v}")
        print("-" * 70)
        print(f"{len(violations)} violation(s). Refusing to commit.")
        print("If this is intentional (rare manual correction), fix by hand")
        print("and re-run — do NOT bypass this without understanding why a")
        print("closed trade's outcome is trying to change.")
        return 1

    print(f"OK — {len(old)} previously-closed trades unchanged. Safe to commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
