"""MediaMonkey -> Koito (Spotify extended-history JSON) converter.

Reads a MediaMonkey 4 SQLite DB and writes Spotify Extended Streaming
History JSON files Koito auto-imports when dropped into its `import/`
folder.

Notes
-----
PlayCounter excess: ~6% of MM listens are "counter-only" -- the
PlayCounter on Songs is higher than the number of Played rows. These
are skipped because they lack timestamps. Most likely cause is device
sync (iPod/phone) where MM bumps the play counter without inserting a
per-listen Played row. Synthesizing fake timestamps would distort
Koito's history graphs, so they are dropped.

AlbumArtist preference: Spotify's schema uses one artist field per
listen (`master_metadata_album_artist_name`). MediaMonkey stores both
track Artist and AlbumArtist. We prefer AlbumArtist (better grouping
for compilations / "feat." tracks) and fall back to Artist when
AlbumArtist is null/empty.

Time zones: MM stores PlayDate as an OLE Automation date (days since
1899-12-30) in local time, with UTCOffset (days, e.g. -0.1666 = -4h)
being the user's TZ offset at the moment of play. UTC instant is
therefore `PlayDate - UTCOffset` applied to the OLE epoch in UTC.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

OLE_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)


def _iunicode(a: str, b: str) -> int:
    """Case-insensitive Unicode collation matching MediaMonkey's IUNICODE.

    MM declares TEXT columns with `COLLATE IUNICODE`, a custom collation
    implemented in the MM binary. SQLite has no built-in equivalent, so
    even read-only queries against TEXT columns fail with "no such
    collation sequence" unless we register a stand-in. A case-folded
    comparison is enough for read-only use; ordering is unaffected
    because the converter sorts by PlayDate (REAL).
    """
    af, bf = a.casefold(), b.casefold()
    return (af > bf) - (af < bf)


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.create_collation("IUNICODE", _iunicode)
    return conn

QUERY = """
SELECT p.PlayDate, p.UTCOffset,
       s.SongTitle, s.Artist, s.AlbumArtist, s.Album,
       s.SongLength
FROM Played p
JOIN Songs s ON s.ID = p.IDSong
WHERE s.SongTitle IS NOT NULL AND s.SongTitle <> ''
  AND COALESCE(NULLIF(s.Artist, ''), NULLIF(s.AlbumArtist, '')) IS NOT NULL
ORDER BY p.PlayDate
"""


def ole_to_utc(play_date: float, utc_offset: float | None) -> datetime:
    offset = utc_offset if utc_offset is not None else 0.0
    return OLE_EPOCH + timedelta(days=play_date - offset)


def build_record(row: sqlite3.Row) -> dict:
    artist = (row["AlbumArtist"] or row["Artist"] or "").strip() or None
    ms = int(row["SongLength"]) if row["SongLength"] else 0
    ts = ole_to_utc(row["PlayDate"], row["UTCOffset"])
    return {
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "username": None,
        "platform": "mediamonkey",
        "ms_played": ms,
        "conn_country": None,
        "ip_addr_decrypted": None,
        "user_agent_decrypted": None,
        "master_metadata_track_name": row["SongTitle"],
        "master_metadata_album_artist_name": artist,
        "master_metadata_album_album_name": row["Album"],
        "spotify_track_uri": None,
        "episode_name": None,
        "episode_show_name": None,
        "spotify_episode_uri": None,
        "reason_start": None,
        "reason_end": None,
        "shuffle": None,
        "skipped": None,
        "offline": None,
        "offline_timestamp": None,
        "incognito_mode": None,
    }


def write_year_file(out_dir: Path, year: int, records: list[dict]) -> Path:
    path = out_dir / f"Streaming_History_Audio_{year}_0.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return path


def convert(db_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    by_year: dict[int, list[dict]] = defaultdict(list)
    total = 0
    zero_duration = 0

    for row in conn.execute(QUERY):
        rec = build_record(row)
        if rec["ms_played"] == 0:
            zero_duration += 1
        year = int(rec["ts"][:4])
        by_year[year].append(rec)
        total += 1

    conn.close()

    if not by_year:
        print("No listens found.", file=sys.stderr)
        return

    written = []
    for year in sorted(by_year):
        path = write_year_file(out_dir, year, by_year[year])
        written.append((path, len(by_year[year])))

    counter_only = counter_only_estimate(db_path)
    total_hours = sum(r["ms_played"] for recs in by_year.values() for r in recs) / 3_600_000

    print(f"Read {total:,} timestamped listens from {db_path.name}")
    print(f"Skipped (counter-only, no timestamp): ~{counter_only:,}")
    print(f"Zero-duration records: {zero_duration:,}")
    print(f"Total ms_played: {total_hours:.1f} hours")
    print(f"Wrote {len(written)} file(s) to {out_dir}/:")
    for path, n in written:
        print(f"  {path.name}: {n:,} records")


def counter_only_estimate(db_path: Path) -> int:
    conn = _open(db_path)
    cur = conn.execute(
        "SELECT (SELECT COALESCE(SUM(PlayCounter),0) FROM Songs) - "
        "(SELECT COUNT(*) FROM Played)"
    )
    n = cur.fetchone()[0]
    conn.close()
    return max(0, int(n))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path, help="Path to MediaMonkey SQLite DB")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output"),
        help="Output directory for JSON files (default: ./output)",
    )
    args = parser.parse_args()

    if not args.db.exists():
        parser.error(f"DB not found: {args.db}")

    convert(args.db, args.out)


if __name__ == "__main__":
    main()
