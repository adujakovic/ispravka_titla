import re


# =========================
# PARSE SRT + ITERATIVE TEXT MERGE
# =========================
def parse_srt(content, max_len=None):
    """
    Ako content = string -> parsiranje početnog SRT-a.
    Ako content = lista segmenata -> dodatno spajanje po max_len.
    Uvijek vraća (segments, mapping).
    """

    # ---------------------------------
    # 1️⃣ PRVA ITERACIJA (STRING INPUT)
    # ---------------------------------
    if isinstance(content, str):

        pattern = r"(\d+)\s+([\d:,]+) --> ([\d:,]+)\s+([\s\S]*?)(?=\n\d+\n|$)"
        matches = re.findall(pattern, content)

        segments = []
        mapping = []

        for idx, m in enumerate(matches, start=1):
            seg = {
                "num": idx,
                "start": m[1],
                "end": m[2],
                "text": m[3].strip().replace("\n", " "),
                "orig_ids": {idx}
            }
            segments.append(seg)
            mapping.append({idx})

        return segments, mapping

    # ---------------------------------
    # 2️⃣ DALJNJE ITERACIJE (LIST INPUT)
    # ---------------------------------
    segments = content
    merged = []
    mapping = []

    i = 0
    while i < len(segments):

        current = segments[i]
        combined_text = current["text"]
        combined_start = current["start"]
        combined_end = current["end"]
        combined_ids = set(current["orig_ids"])

        while (
            max_len is not None
            and i + 1 < len(segments)
            and len(format_merge(combined_text, segments[i + 1]["text"])) <= max_len
        ):
            i += 1
            next_seg = segments[i]

            combined_text = format_merge(combined_text, next_seg["text"])
            combined_end = next_seg["end"]
            combined_ids |= next_seg["orig_ids"]

        new_seg = {
            "num": len(merged) + 1,
            "start": combined_start,
            "end": combined_end,
            "text": combined_text,
            "orig_ids": combined_ids
        }

        merged.append(new_seg)
        mapping.append(combined_ids)

        i += 1

    return merged, mapping


# =========================
# TIME HELPERS
# =========================
def to_seconds(t):
    h, m, s = t.split(":")
    s, ms = s.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def to_srt_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


# =========================
# TEXT MERGE RULE
# =========================
def format_merge(prev_text, next_text):
    if prev_text.endswith((".", "?", "!", "…")):
        return prev_text + " " + next_text.capitalize()
    else:
        return prev_text + ", " + next_text


# =========================
# MERGE ENGINE (TIMING + RULES)
# =========================
def merge_segments(
        segments,
        max_len=170,
        min_duration=1.0,
        max_dist_forward=0.1,
        max_dist_backward=1.0
):

    merged_segments = []
    mapping = []

    i = 0

    while i < len(segments):

        current = segments[i]

        combined_text = current["text"]
        combined_start = current["start"]
        combined_end = current["end"]
        combined_ids = set(current["orig_ids"])

        # -------- FORWARD MERGE --------
        while (
            i + 1 < len(segments)
            and to_seconds(segments[i + 1]["start"]) - to_seconds(combined_end) <= max_dist_forward
            and len(format_merge(combined_text, segments[i + 1]["text"])) <= max_len
            and not combined_text.endswith((".", "?", "!", "…"))
        ):
            i += 1
            next_seg = segments[i]

            combined_text = format_merge(combined_text, next_seg["text"])
            combined_end = next_seg["end"]
            combined_ids |= next_seg["orig_ids"]

        # -------- MIN DURATION FIX --------
        duration = to_seconds(combined_end) - to_seconds(combined_start)

        if duration < min_duration:
            combined_end = to_srt_time(
                to_seconds(combined_start) + min_duration
            )

        new_seg = {
            "num": len(merged_segments) + 1,
            "start": combined_start,
            "end": combined_end,
            "text": combined_text,
            "orig_ids": combined_ids
        }

        merged_segments.append(new_seg)
        mapping.append(combined_ids)

        i += 1

    return merged_segments, mapping


# =========================
# SRT STRING EXPORT
# =========================
def segments_to_srt(segments):
    output = ""
    for idx, seg in enumerate(segments, start=1):
        output += f"{idx}\n{seg['start']} --> {seg['end']}\n{seg['text']}\n\n"
    return output
