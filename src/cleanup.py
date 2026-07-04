"""Delete media in posts/ older than RETENTION_DAYS (filename-dated).

Instagram only needs the public URLs at publish time, so old media is
dead weight that bloats the repo. Run by the daily workflow before the
commit step.
"""

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS") or "14")


def main() -> None:
    posts_dir = Path(__file__).resolve().parent.parent / "posts"
    if not posts_dir.exists():
        return
    cutoff = datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=RETENTION_DAYS)
    removed = 0
    for path in posts_dir.iterdir():
        m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
        if not m:
            continue
        if datetime.strptime(m.group(1), "%Y-%m-%d").date() < cutoff:
            path.unlink()
            removed += 1
    print(f"cleanup: removed {removed} media files older than {RETENTION_DAYS} days")


if __name__ == "__main__":
    main()
