# Crate Review

A local review page for comparing possible duplicate music tracks using Rekordbox metadata and audio signatures. The page stores review decisions in the browser and exports approved actions; it does not modify Rekordbox, Music, or audio files.

## Generate a local review

Requirements: Python 3 and `ffmpeg` on macOS, plus a Rekordbox XML export and the referenced music files.

```sh
python3 build_duplicate_sweep.py
```

By default, the generator looks for the XML at `~/Documents/rekordbox/rekordbox.xml` and the library at `~/Music/Music/Media.localized/Music`. Override either with `REKORDBOX_XML` or `MUSIC_LIBRARY_ROOT`, or use `--xml` and `--library-root`.

If the XML does not identify which playlists are intelligent, list their names in `.local/playlist-types.json`:

```json
{"intelligentPlaylists": ["Example automatic list"], "intelligentFolders": ["Example automatic folder"]}
```

This file stays local. Set `REKORDBOX_PLAYLIST_TYPES` to use a different config path.

The generator writes `duplicate-sweep.json`, `sweep-top50.js`, and `waveforms.js` beside the script. These files contain private library paths, playlist names, cue data, and audio fingerprints; they are ignored by Git and should not be published.

Open `index.html` in a browser after generation. If no local sweep data exists, the page opens with an empty candidate list.

## Decisions

Each track can be marked to keep or delete. Locking a pair records the choice in browser storage. Downloading approved decisions exports a JSON plan; it does not execute the requested library or file operations. Process those actions separately after reviewing the exported plan.
