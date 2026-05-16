# mediamonkey-to-koito

Converts a MediaMonkey 4 SQLite database into [Koito](https://koito.io/)-importable
JSON files in the Spotify Extended Streaming History format.

## Usage

```sh
python mm2koito.py path/to/MediaMonkey.DB --out output/
```

Then copy the generated `Streaming_History_Audio_<year>_0.json` files into
your Koito `import/` folder and restart Koito. See
[Koito's import guide](https://koito.io/guides/importing/).

Requires Python 3.9+ (stdlib only).

## Output Format

Spotify-style JSON, one file per calendar year. Koito picks them up
automatically because the file names contain `Streaming_History_Audio`.

Each record includes `ms_played` (taken from MediaMonkey's `SongLength`),
which preserves Koito's "Hours Listened" statistic.

## Known Limitations

### Counter-only listens are skipped

MediaMonkey tracks plays in two places: a per-song `PlayCounter` and a
`Played` table with timestamps. In our DB the counter total exceeds the
timestamped log by ~6% (about 7,000 listens). These extra plays most
likely come from device sync (iPod / phone) where MediaMonkey bumps the
counter but does not insert a timestamped row.

These listens are skipped. Synthesizing fake timestamps would distort
Koito's history graphs.

### AlbumArtist preferred over track Artist

Spotify's schema has a single artist field per listen
(`master_metadata_album_artist_name`). When a track has both an
AlbumArtist and an Artist (e.g. compilations, "feat." tracks), the
AlbumArtist is used because it groups plays more sensibly in Koito.

### Time zones

`PlayDate` values are stored as OLE Automation dates in local time, with
`UTCOffset` recording the user's offset at the moment of play. The
converter normalizes everything to UTC.
