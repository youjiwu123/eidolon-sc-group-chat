#!/usr/bin/env python3
"""Export a story-only SQLite database from a deployment database.

The deployment's `/data/eidolon.db` holds everything: accounts, conversations, messages,
memories, and the story corpus. This copies just the story tables into a new file, so it can
be shared without any user data:

    episodes, episode_cast, episode_lines, episode_passages

Usage (inside the backend container, or anywhere the source file is readable):

    python tools/export-story-db.py /data/eidolon.db /tmp/story.db

The story text itself is the original work's; share it privately only.
"""

from __future__ import annotations

import argparse
import os
import sqlite3

TABLES = ("episodes", "episode_cast", "episode_lines", "episode_passages")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="the deployment database, e.g. /data/eidolon.db")
    parser.add_argument("output", help="where to write the story-only database, e.g. /tmp/story.db")
    args = parser.parse_args()

    if not os.path.isfile(args.source):
        print(f"no such database: {args.source}", flush=True)
        return 1
    if os.path.exists(args.output):
        os.remove(args.output)

    db = sqlite3.connect(args.output)
    db.execute("ATTACH DATABASE ? AS src", (args.source,))
    present = {
        row[0]
        for row in db.execute("select name from src.sqlite_master where type='table'")
    }
    for table in TABLES:
        if table not in present:
            print(f"skipped (not in the source): {table}", flush=True)
            continue
        db.execute(f'CREATE TABLE "{table}" AS SELECT * FROM src."{table}"')
        count = db.execute(f'select count(1) from "{table}"').fetchone()[0]
        print(f"{table}: {count} rows", flush=True)
    db.commit()
    db.execute("VACUUM")
    db.close()

    print(f"wrote {args.output} ({os.path.getsize(args.output) / 1e6:.1f} MB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
