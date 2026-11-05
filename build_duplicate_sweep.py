#!/usr/bin/env python3
"""Build a conservative, evidence-rich duplicate candidate set from Rekordbox XML."""
import argparse
import array
import audioop
import concurrent.futures
import difflib
import hashlib
import json
import math
import os
import re
import subprocess
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from collections import defaultdict

XML_DEFAULT = os.environ.get("REKORDBOX_XML", os.path.expanduser("~/Documents/rekordbox/rekordbox.xml"))
LIBRARY_ROOT = os.environ.get("MUSIC_LIBRARY_ROOT", os.path.expanduser("~/Music/Music/Media.localized/Music"))
PLAYLIST_TYPES_FILE = os.environ.get("REKORDBOX_PLAYLIST_TYPES", os.path.join(os.path.dirname(__file__), ".local", "playlist-types.json"))


def load_playlist_types():
    if not os.path.isfile(PLAYLIST_TYPES_FILE):
        return set(), set()
    with open(PLAYLIST_TYPES_FILE) as source:
        config = json.load(source)
    return ({name.casefold() for name in config.get("intelligentPlaylists", [])},
            {name.casefold() for name in config.get("intelligentFolders", [])})


AUTO_PLAYLISTS, AUTO_FOLDERS = load_playlist_types()
TOP_COUNT = 50
CANDIDATE_COUNT = 500
WAVE_BINS = 600


def norm(value):
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    value = re.sub(r"^\s*\d+[-. ]+", "", value)
    value = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def local_path(location):
    location = location or ""
    if location.startswith("file://localhost"):
        location = location[len("file://localhost"):]
    elif location.startswith("file://"):
        location = location[len("file://"):]
        if not location.startswith("/"):
            location = "/" + location.split("/", 1)[1]
    return urllib.parse.unquote(location)


def duration_seconds(track):
    try:
        return int(track.get("TotalTime", 0))
    except ValueError:
        return 0


def playlist_data(root):
    by_track = defaultdict(lambda: {"manual": set(), "smart": set()})

    def visit(node, folders=()):
        name = node.get("Name", "")
        ancestry = folders + ((name,) if node.get("Type") == "0" and name != "ROOT" else ())
        if node.get("Type") == "1":
            path = "/".join(ancestry + (name,)) if ancestry else name
            smart = name.casefold() in AUTO_PLAYLISTS or any(
                "smart" in part.casefold() or "intelligent" in part.casefold() or part.strip().casefold() in AUTO_FOLDERS
                for part in ancestry
            )
            bucket = "smart" if smart else "manual"
            for member in node.findall("TRACK"):
                key = member.get("Key")
                if key:
                    by_track[key][bucket].add(path)
        for child in node.findall("NODE"):
            visit(child, ancestry)

    playlists = root.find("PLAYLISTS")
    if playlists is not None:
        for node in playlists.findall("NODE"):
            visit(node)
    return by_track


def cue_summary(track):
    hot = memory = loops = 0
    marks = []
    for mark in track.findall("POSITION_MARK"):
        attrs = mark.attrib
        kind = attrs.get("Type", "0")
        number = attrs.get("Num", "-1")
        try:
            start = float(attrs.get("Start", "0"))
        except ValueError:
            start = 0.0
        try:
            end = float(attrs.get("End", "-1"))
        except ValueError:
            end = -1.0
        if kind == "4":
            loops += 1
            cue_kind = "loop"
            slot = ""
        elif number == "-1":
            memory += 1
            cue_kind = "memory"
            slot = ""
        else:
            hot += 1
            cue_kind = "hot"
            try:
                slot = chr(ord("A") + int(number))
            except (ValueError, TypeError):
                slot = str(number)
        marks.append({"kind": cue_kind, "slot": slot, "name": attrs.get("Name", ""),
                      "start": round(start, 3), "end": round(end, 3) if end >= 0 else None})
    marks.sort(key=lambda mark: (mark["start"], mark["kind"], mark["slot"]))
    return hot, memory, loops, marks


def collect_tracks(root, library_root):
    memberships = playlist_data(root)
    records = {}
    by_id = {}
    for node in root.find("COLLECTION").findall("TRACK"):
        attrs = node.attrib
        path = local_path(attrs.get("Location", ""))
        if not path or not os.path.isfile(path) or not path.startswith(library_root + os.sep):
            continue
        hot, memory, loops, marks = cue_summary(node)
        member = memberships.get(attrs.get("TrackID", ""), {"manual": set(), "smart": set()})
        record = {
            "name": attrs.get("Name", ""), "artist": attrs.get("Artist", ""),
            "album": attrs.get("Album", ""), "albumArtist": attrs.get("AlbumArtist", ""), "path": path,
            "duration": duration_seconds(node), "bitrate": int(attrs.get("BitRate", 0) or 0),
            "sampleRate": int(attrs.get("SampleRate", 0) or 0), "kind": attrs.get("Kind", ""),
            "size": int(attrs.get("Size", 0) or 0), "bpm": attrs.get("AverageBpm", "0.00"),
            "key": attrs.get("Tonality", ""), "plays": int(attrs.get("PlayCount", 0) or 0),
            "rating": int(attrs.get("Rating", 0) or 0), "trackId": attrs.get("TrackID", ""),
            "hotCues": hot, "memoryCues": memory, "loops": loops, "cueMarks": marks,
            "manualPlaylists": sorted(member["manual"]), "smartPlaylists": sorted(member["smart"]),
            "fileBytes": os.path.getsize(path),
        }
        # Preserve the record with the richest Rekordbox metadata for repeated locations.
        if path not in records or len(marks) + len(member["manual"]) > len(records[path]["cueMarks"]) + len(records[path]["manualPlaylists"]):
            records[path] = record
        by_id[attrs.get("TrackID", "")] = record
    return list(records.values()), by_id


def duration_delta(a, b):
    return abs(a["duration"] - b["duration"])


def version_profile(title):
    text = (title or "").lower()
    labels = ("instrumental", "full vocal", "vocal version", "radio edit", "dj edit", "club edit", "extended", "vip", "dub", "acapella", "a cappella", "remix", "rework", "live", "bootleg", "flip")
    return {label for label in labels if label in text}


def candidate_pairs(tracks):
    exact = defaultdict(list)
    titles = defaultdict(list)
    artists = defaultdict(list)
    for track in tracks:
        title, artist = norm(track["name"]), norm(track["artist"])
        track["normTitle"] = title
        track["normArtist"] = artist
        if title:
            exact[(artist, title)].append(track)
            titles[title].append(track)
        if artist:
            artists[artist].append(track)

    pairs = {}

    def add(a, b, basis, title_similarity=None):
        if a["path"] == b["path"]:
            return
        if a["path"] < b["path"]:
            left, right = a, b
        else:
            left, right = b, a
        key = (left["path"], right["path"])
        sim = title_similarity if title_similarity is not None else difflib.SequenceMatcher(None, left["normTitle"], right["normTitle"]).ratio()
        artist_sim = difflib.SequenceMatcher(None, left["normArtist"], right["normArtist"]).ratio()
        versions_a, versions_b = version_profile(left["name"]), version_profile(right["name"])
        delta = duration_delta(left, right)
        closeness = max(0.0, 1.0 - delta / 90.0)
        bpm_a, bpm_b = float(left["bpm"] or 0), float(right["bpm"] or 0)
        bpm_match = 1.0 if bpm_a and bpm_b and abs(bpm_a - bpm_b) <= 0.15 else 0.0
        key_match = 1.0 if left["key"] and left["key"] == right["key"] else 0.0
        score = round(55 * sim + 25 * artist_sim + 15 * closeness + 3 * bpm_match + 2 * key_match, 2)
        if key not in pairs or score > pairs[key]["metadataScore"]:
            pairs[key] = {"tracks": [left, right], "basis": basis, "titleSimilarity": round(sim, 4),
                          "artistSimilarity": round(artist_sim, 4), "durationDifference": delta,
                          "versionMismatch": bool((versions_a or versions_b) and versions_a != versions_b),
                          "metadataScore": score, "pcmMatch": False, "fileMatch": False,
                          "audioEnvelopeSimilarity": None, "audioSignature": "not checked"}

    for (artist, title), bucket in exact.items():
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                if duration_delta(a, b) <= 90:
                    add(a, b, "same artist and normalized title")

    for artist, bucket in artists.items():
        if len(bucket) > 200:
            continue
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                delta = duration_delta(a, b)
                if delta > 25 or a["normTitle"] == b["normTitle"]:
                    continue
                sim = difflib.SequenceMatcher(None, a["normTitle"], b["normTitle"]).ratio()
                if sim >= 0.80 and min(len(a["normTitle"]), len(b["normTitle"])) >= 5:
                    add(a, b, "similar titles, same artist", sim)

    for title, bucket in titles.items():
        if len(title) < 6 or len(bucket) > 100:
            continue
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                if a["normArtist"] == b["normArtist"] or duration_delta(a, b) > 15:
                    continue
                add(a, b, "same title, different artist tags")

    # Ensure there are 500 reviewable pairs without lowering the meaningful title threshold.
    ranked = sorted(pairs.values(), key=lambda item: (-item["metadataScore"], item["durationDifference"], item["tracks"][0]["path"]))
    if len(ranked) < CANDIDATE_COUNT:
        raise RuntimeError(f"Only {len(ranked)} candidates found; refusing to pad with weak matches")
    return ranked


def base36(value):
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    value = max(0, min(35, int(value)))
    return chars[value]


def audio_signature(path, duration):
    file_hash = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            file_hash.update(block)
    command = ["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
    if result.returncode:
        return {"fileHash": file_hash.hexdigest(), "pcmHash": None, "peaks": None, "error": result.stderr.decode(errors="replace")[-240:]}
    pcm = result.stdout
    pcm_hash = hashlib.sha256(pcm).hexdigest() if pcm else None
    sample_count = len(pcm) // 2
    if not sample_count:
        return {"fileHash": file_hash.hexdigest(), "pcmHash": pcm_hash, "peaks": None, "error": "empty decoded audio"}
    peaks = []
    for i in range(WAVE_BINS):
        start = i * sample_count // WAVE_BINS
        end = max(start + 1, (i + 1) * sample_count // WAVE_BINS)
        peak = audioop.max(pcm[start * 2:end * 2], 2)
        peaks.append(base36(round(peak / 32767 * 35)))
    low_pcm, _ = audioop.ratecv(pcm, 2, 1, 8000, 1000, None)
    return {"fileHash": file_hash.hexdigest(), "pcmHash": pcm_hash, "peaks": "".join(peaks),
            "lowPcm": low_pcm, "error": None}


def envelope_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return None
    x = [int(ch, 36) for ch in left]
    y = [int(ch, 36) for ch in right]
    best = -1.0
    for lag in range(-4, 5):
        xs = x[max(0, lag):len(x) + min(0, lag)]
        ys = y[max(0, -lag):len(y) - max(0, lag)]
        if len(xs) < len(x) * 0.9:
            continue
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        dx, dy = [v - mx for v in xs], [v - my for v in ys]
        den = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
        if den:
            best = max(best, sum(a * b for a, b in zip(dx, dy)) / den)
    return round(best, 5) if best >= 0 else None


def sample_similarity(left, right):
    if not left or not right:
        return None
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) < 4000 or len(longer) - len(shorter) > 20000:
        return None
    try:
        offset, factor = audioop.findfit(longer, shorter)
        segment = longer[offset:offset + len(shorter)]
        rms_short, rms_long = audioop.rms(shorter, 2), audioop.rms(segment, 2)
        if not rms_short or not rms_long:
            return None
        return round(max(-1.0, min(1.0, factor * rms_short / rms_long)), 5)
    except audioop.error:
        return None


def quality_label(track):
    bitrate = track["bitrate"]
    kind = track["kind"].lower()
    if "mp3" in kind:
        fmt = "MP3"
    elif "aac" in kind or "m4a" in kind:
        fmt = "AAC"
    elif "flac" in kind:
        fmt = "FLAC"
    elif "aiff" in kind:
        fmt = "AIFF"
    elif "wav" in kind:
        fmt = "WAV"
    else:
        fmt = re.sub(r"\s+File$", "", track["kind"], flags=re.I) or "audio"
    return f"{bitrate} {fmt}" if bitrate else fmt


def ui_track(track, signature):
    duration = track["duration"]
    cues = f"H{track['hotCues']} M{track['memoryCues']} L{track['loops']}"
    manual = track["manualPlaylists"]
    smart = track["smartPlaylists"]
    return {
        "name": os.path.basename(track["path"]), "album": track["album"] or "Unknown Album",
        "artist": track["artist"], "path": track["path"], "quality": quality_label(track), "bitrate": track["bitrate"],
        "key": track["key"] or "—", "bpm": f"{float(track['bpm'] or 0):.2f}" if float(track["bpm"] or 0) else "",
        "cues": cues, "playlists": f"{len(manual)} manual / {len(smart)} smart",
        "manualPlaylists": manual, "smartPlaylists": len(smart), "smartPlaylistNames": smart,
        "plays": track["plays"], "seconds": duration, "sampleRate": track["sampleRate"],
        "size": track["fileBytes"], "pcmHash": signature.get("pcmHash"), "fileHash": signature.get("fileHash"),
        "cueMarks": track["cueMarks"],
    }


def compare_keep_score(a, b, exact_audio=False, near_exact=False):
    cues_a = a["hotCues"] + a["memoryCues"] + a["loops"]
    cues_b = b["hotCues"] + b["memoryCues"] + b["loops"]
    vals = [(a["bitrate"], b["bitrate"]), (cues_a, cues_b)]
    compilation_a = is_compilation_album(a)
    compilation_b = is_compilation_album(b)
    if compilation_a != compilation_b:
        vals.append((int(not compilation_a), int(not compilation_b)))
    wins = sum(x > y for x, y in vals)
    losses = sum(x < y for x, y in vals)
    a_lists, b_lists = set(a["manualPlaylists"]), set(b["manualPlaylists"])
    # Exact or near-exact content can collapse to one row when the surviving
    # file preserves all curated-list placements from the other copy.
    if exact_audio or near_exact:
        if a_lists > b_lists:
            return "a"
        if b_lists > a_lists:
            return "b"
        if a_lists and b_lists and a_lists != b_lists:
            return "both"
        if a_lists and not b_lists:
            return "a"
        if b_lists and not a_lists:
            return "b"
        if wins and not losses:
            return "a"
        if losses and not wins:
            return "b"
        if not wins and not losses:
            suffix_choice = filename_suffix_preference(a, b) if exact_audio else None
            if suffix_choice:
                return suffix_choice
            return "a"
    if wins and not losses and not b_lists:
        return "a"
    if losses and not wins and not a_lists:
        return "b"
    return "both"


def filename_suffix_preference(a, b):
    """Prefer a matching base filename over a copy with a trailing number."""
    name_a = os.path.splitext(os.path.basename(a["path"]))[0]
    name_b = os.path.splitext(os.path.basename(b["path"]))[0]
    numbered_a = re.fullmatch(r"(.+?)\s+\d+", name_a)
    numbered_b = re.fullmatch(r"(.+?)\s+\d+", name_b)
    if numbered_a and numbered_a.group(1).casefold() == name_b.casefold():
        return "b"
    if numbered_b and numbered_b.group(1).casefold() == name_a.casefold():
        return "a"
    return None


def is_compilation_album(track):
    album_artist = track.get("albumArtist", "")
    if re.search(r"\bvarious\s+artists?\b|^\s*v/?a\s*$", album_artist, re.I):
        return True
    album = track.get("album", "")
    if (
        re.search(r"\bvarious\s+artists?\b|\bcompilation\b", album, re.I)
        or re.match(r"^\s*(?:v/?a|v\.a\.?)\s*(?:[/:-]|$)", album, re.I)
    ):
        return True
    compilation_folders = {"va", "v.a.", "various", "various artists", "compilation", "compilations"}
    return any(part.strip().casefold() in compilation_folders for part in os.path.dirname(track.get("path", "")).split(os.sep))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xml", default=XML_DEFAULT)
    parser.add_argument("--library-root", default=LIBRARY_ROOT)
    parser.add_argument("--candidate-output", default="duplicate-sweep.json")
    parser.add_argument("--top-output", default="sweep-top50.js")
    parser.add_argument("--waveforms", default="waveforms.js")
    args = parser.parse_args()

    root = ET.parse(args.xml).getroot()
    tracks, _ = collect_tracks(root, args.library_root)
    candidates = candidate_pairs(tracks)
    paths = sorted({track["path"] for pair in candidates for track in pair["tracks"]})
    print(f"Parsed {len(tracks)} existing Rekordbox tracks; {len(candidates)} candidate pairs use {len(paths)} unique files.", flush=True)

    signatures = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(audio_signature, path, 0): path for path in paths}
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            path = futures[future]
            try:
                signatures[path] = future.result()
            except Exception as exc:
                signatures[path] = {"fileHash": None, "pcmHash": None, "peaks": None, "error": str(exc)}
            if i % 50 == 0 or i == len(paths):
                print(f"Decoded/fingerprinted {i}/{len(paths)} candidate files", flush=True)

    for pair in candidates:
        a, b = pair["tracks"]
        sig_a, sig_b = signatures[a["path"]], signatures[b["path"]]
        pair["fileMatch"] = bool(sig_a.get("fileHash") and sig_a["fileHash"] == sig_b.get("fileHash"))
        pair["pcmMatch"] = bool(sig_a.get("pcmHash") and sig_a["pcmHash"] == sig_b.get("pcmHash"))
        pair["audioEnvelopeSimilarity"] = envelope_similarity(sig_a.get("peaks"), sig_b.get("peaks"))
        pair["audioSampleSimilarity"] = sample_similarity(sig_a.get("lowPcm"), sig_b.get("lowPcm")) if pair["durationDifference"] <= 20 else None
        if pair["fileMatch"]:
            pair["audioSignature"] = "identical file bytes"
        elif pair["pcmMatch"]:
            pair["audioSignature"] = "identical decoded mono 8 kHz PCM"
        elif pair["audioSampleSimilarity"] is not None:
            pair["audioSignature"] = f"time-aligned 1 kHz sample correlation {pair['audioSampleSimilarity']:.3f}"
        elif pair["audioEnvelopeSimilarity"] is not None:
            pair["audioSignature"] = f"waveform envelope correlation {pair['audioEnvelopeSimilarity']:.3f}"
        else:
            pair["audioSignature"] = "not comparable"

        # Strong duplicates require audio evidence plus close title/duration. Lower confidence candidates remain in the 500-pair audit file.
        strong_audio = pair["fileMatch"] or pair["pcmMatch"] or (
            (pair["audioSampleSimilarity"] or 0) >= 0.96 and pair["durationDifference"] <= 5
            and pair["titleSimilarity"] >= 0.9 and pair["artistSimilarity"] >= 0.75 and not pair["versionMismatch"]
        )
        pair["confidence"] = "high" if pair["fileMatch"] or pair["pcmMatch"] else "medium" if strong_audio else "low"
        exact_audio = pair["fileMatch"] or pair["pcmMatch"]
        near_exact = (pair["audioSampleSimilarity"] or 0) >= 0.995 and not pair["versionMismatch"]
        pair["oneCopyRecommendation"] = compare_keep_score(a, b, exact_audio, near_exact) if strong_audio else "both"
        pair["rankScore"] = round((100 if pair["fileMatch"] or pair["pcmMatch"] else 80 * (pair["audioSampleSimilarity"] or 0))
                                   + pair["metadataScore"] * 0.2
                                   + (5 if pair["oneCopyRecommendation"] in ("a", "b") else 0), 2)
        pair["tracks"] = [ui_track(t, signatures[t["path"]]) for t in (a, b)]

    candidates.sort(key=lambda p: (-p["rankScore"], -p["metadataScore"], p["durationDifference"]))
    candidates = candidates[:CANDIDATE_COUNT]
    for i, pair in enumerate(candidates, 1):
        pair["number"] = i

    report = {
        "sourceXml": os.path.basename(args.xml), "candidateCount": len(candidates),
        "sourceTrackCount": len(tracks), "rankedBy": ["audio signature", "metadata similarity", "duration", "manual-list and quality/cue retention"],
        "candidates": candidates,
    }
    with open(args.candidate_output, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Prefer confident one-copy decisions; then use strong audio matches with an explicit keep-both recommendation to fill the review list.
    one_copy = [p for p in candidates if p["confidence"] in ("high", "medium") and p["oneCopyRecommendation"] in ("a", "b")]
    selected = one_copy[:TOP_COUNT]

    ui_candidates = []
    for i, pair in enumerate(selected, 1):
        a, b = pair["tracks"]
        # Keep the XML tags as displayed labels and retain both file records in the exported audit.
        raw_a, raw_b = next(t for t in tracks if t["path"] == a["path"]), next(t for t in tracks if t["path"] == b["path"])
        titles = [norm(raw_a["name"]), norm(raw_b["name"])]
        title = raw_a["name"] if titles[0] == titles[1] else f"{raw_a['name']} / {raw_b['name']}"
        performer = raw_a["artist"] or raw_b["artist"] or "Unknown artist"
        if raw_a["artist"] and raw_b["artist"] and norm(raw_a["artist"]) != norm(raw_b["artist"]):
            performer = f"{raw_a['artist']} / {raw_b['artist']}"
        ui_candidates.append({
            "id": i, "title": title, "artist": performer,
            "duration": f"{a['seconds']//60}:{a['seconds']%60:02d}",
            "match": "PCM MATCH" if pair["fileMatch"] or pair["pcmMatch"] else f"AUDIO {round((pair['audioSampleSimilarity'] or 0)*100)}%" if pair["confidence"] == "medium" else "POSSIBLE",
            "matchType": "exact" if pair["fileMatch"] or pair["pcmMatch"] else "unknown",
            "recommended": pair["oneCopyRecommendation"],
            "patternGroups": [pair["confidence"], "similar title" if "similar title" in pair["basis"] else "same title"],
            "tracks": [{k: v for k, v in tr.items() if k not in ("pcmHash", "fileHash", "cueMarks", "smartPlaylistNames")} for tr in pair["tracks"]],
            "options": [
                {"id": "a", "label": "Keep A", "note": "Mark B for removal later"},
                {"id": "b", "label": "Keep B", "note": "Mark A for removal later"},
                {"id": "both", "label": "Keep both", "note": "Keep both"},
                {"id": "skip", "label": "Skip for now", "note": "Decide later"},
            ],
            "sweepEvidence": {k: v for k, v in pair.items() if k != "tracks"},
        })
    with open(args.top_output, "w") as f:
        f.write("window.DUPLICATE_SWEEP_TOP50 = ")
        json.dump(ui_candidates, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    try:
        raw = open(args.waveforms, "r").read()
        existing = json.loads(raw.split("=", 1)[1].strip().rstrip(";"))
    except Exception:
        existing = {}
    for pair in selected:
        for tr in pair["tracks"]:
            sig = signatures.get(tr["path"], {})
            if sig.get("peaks"):
                existing[tr["path"]] = {"peaks": sig["peaks"], "duration": tr["seconds"], "cues": tr["cueMarks"]}
    with open(args.waveforms, "w") as f:
        f.write("window.TRACK_VISUALS = ")
        json.dump(existing, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    print(f"Saved 500 detailed pairs to {args.candidate_output}; {len(selected)} one-copy recommendations are in {args.top_output}.")
    print("One-copy recommendations among top set:", sum(p["oneCopyRecommendation"] in ("a", "b") for p in selected))
    print("Audio-signature matches in top set:", sum(p["confidence"] in ("high", "medium") for p in selected))


if __name__ == "__main__":
    main()
