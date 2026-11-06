# Crate Review rules

Updated 2026-11-05 from review decisions.

## Candidate and duplicate evidence

- Find candidates using normalized artist/title plus close title variants and duration. A title or duration match alone is not proof of a duplicate.
- Compare file hashes and decoded audio signatures. Mark an exact match only when the files or normalized decoded audio match; label weaker evidence separately.
- Keep the evidence for all candidate pairs, including paths, duration, format/bitrate, Rekordbox cues and analysis, playlist memberships, play count, and audio-signature result.
- Preserve remix, edit, and version distinctions when the audio differs.
- Treat an explicit DJ Edit or Club Edit label as a version distinction, even when the title otherwise normalizes to the same words.

## Keep recommendation

- For an exact audio duplicate with no manual playlist placement, recommend one copy. When quality, cue data, and manual-list context tie, prefer the matching filename without a trailing numeric copy suffix (for example, `Track.mp3` over `Track 1.mp3`); otherwise use A as the stable tie-break.
- A track that loses on every directional comparison and has no manual playlist placement can be removed in favour of the other track. Current directional comparisons are bitrate and cue-data count; do not treat a different key, BPM, or duration as inherently better.
- When other evidence is tied, prefer a track from an artist album over the same audio on a Various Artists or compilation release. Use explicit album-artist/compilation tags or clear album and folder markers for this distinction.
- Treat manual playlist placements as a preservation signal. Do not recommend dropping a manually placed track just because another file has higher bitrate or more cues.
- For exact or near-exact audio matches, a one-copy recommendation may preserve all curated-list placements by keeping the track whose manual-playlist set is a superset; if both tracks cover different manual lists, keep both.
- Recommend keeping both when the comparison has trade-offs, unclear audio identity, or both copies have curated manual-list context.
- Bitrate below 256 kbps is low quality for this review. Higher bitrate is a quality advantage when comparing the same codec; it does not prove two files are duplicates.

## Playlist classification

- Rekordbox calls automatic playlists **Intelligent Playlists**. Record library-specific names in the local playlist-type config, never in source control.
- The XML collection export can flatten intelligent-list membership into regular playlist nodes. Do not infer manual status from XML membership alone; use the Rekordbox library metadata and known list type.
- Treat playlists under configured intelligent folders as automatic membership, not curated set placements.

## Review and processing

- Keep review read-only. Store decisions in browser storage and export approved choices; exporting records actions but does not execute them. Process only after the reviewer explicitly asks to process approved choices.
- Each track has a keep/delete switch. Keep is green/on with a check; delete is red/off with a trash icon. Require at least one kept track in each approved pair.
- Once a deletion choice is locked, tint that track's full row red (pale red in light mode), make its filename red, and fade row contents to 50% opacity. An unlocked Delete choice uses the normal row styling.
- For an approved delete, remove the track from the Rekordbox Collection, remove it from the Apple Music library while keeping its file, then move the file to Trash. Do not empty Trash.
- When the reviewer handles Rekordbox through Missing File Manager, verify each Music entry by exact file location, remove the approved Music entries, move only those files to Trash, and retain a private restore ledger. The reviewer then removes the missing Collection entries in Rekordbox.
- Show the most confident one-copy recommendations first, with the complete candidate audit retained separately.
- Make per-track differences easy to scan; show shared properties only on request. Place the disclosure caret before the properties (`‹` collapsed, `›` expanded), keep the property chips on one line, and right-align them against the waveform. On narrower windows, allow horizontal scrolling instead of wrapping properties.
- Use green for an objectively better value, red for worse, and orange for a difference without a clear direction. Matching values stay collapsed by default.
- Use the available desktop width, leave room for album labels, keep the waveform compact and subdued, and make cue markers high contrast. Include a per-track play/pause control and a draggable/clickable seek marker.
- Center the play glyph in its button. Show a small Apple Music icon before albums in `Media.localized`; show shortened paths only for other locations.
- Default to the OS colour scheme. Cycle the theme control through System, Light, and Dark; System follows later OS appearance changes.
- Use the transparent repository logo in the app header with no CSS backing. Vertically center the wordmark, keep it close to the logo, and color “review” in the record's teal hue with sufficient contrast in each theme.
- Initialize keep/delete switches from the recommendation. Lock confirmed choices, and keep them separate from the initial suggested state.
- Use concise text, a simple candidate number, no pair codes, no explanatory subtext under choices, and full paths only on hover.
