#!/usr/bin/env python3
"""
Rotates large log files. Keeps last 90 days in active file, archives older.
Run weekly via cron.
"""
import sys, json, gzip
from pathlib import Path
from datetime import datetime, timezone, timedelta

LOG_DIR = Path(__file__).parent.parent / "logs"
ARCHIVE_DIR = LOG_DIR / "archive"
MAX_DAYS = 90


def rotate_jsonl(filepath: Path):
    if not filepath.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_DAYS)
    keep = []
    archive = []
    with open(filepath) as f:
        for line in f:
            try:
                record = json.loads(line)
                ts_str = record.get("timestamp") or record.get("date") or record.get("recorded_at")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        archive.append(line)
                        continue
            except Exception:
                pass
            keep.append(line)

    if archive:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_name = ARCHIVE_DIR / f"{filepath.stem}_{datetime.now().strftime('%Y%m%d')}.jsonl.gz"
        with gzip.open(archive_name, "wt") as f:
            f.writelines(archive)
        print(f"Archived {len(archive)} records from {filepath.name} → {archive_name.name}")

    with open(filepath, "w") as f:
        f.writelines(keep)
    print(f"Kept {len(keep)} records in {filepath.name}")


def main():
    for log_file in ["signals.jsonl", "ledger.jsonl", "equity_curve.jsonl"]:
        rotate_jsonl(LOG_DIR / log_file)


if __name__ == "__main__":
    main()
