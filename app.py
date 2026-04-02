import streamlit as st
import pandas as pd
from io import BytesIO
import titl_join
import time as tm
import re

# =====================================
# CONFIGURATION
# =====================================
# Defines how aggressive merging is
MAX_LEN_STEPS = (60, 120, 140)

MIN_DURATION = 1.0
MAX_DIST_FORWARD = 0.1
MAX_DIST_BACKWARD = 1.0


# =====================================
# VALIDATION FUNCTION
# Removes bad segments after merging
# =====================================
def validate_and_filter_segments(segments):

    time_pattern = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}$")

    valid_segments = []
    deleted_segments = []

    expected_number = 1

    for seg in segments:

        error_reason = None

        # 1. Segment numbering check
        if seg["num"] != expected_number:
            error_reason = f"Pogrešan redoslijed (expected {expected_number})"

        # 2. Time format check
        if not time_pattern.match(seg["start"]) or not time_pattern.match(seg["end"]):
            error_reason = "Invalid time format"

        # 3. Logical time check
        if seg["start"] >= seg["end"]:
            error_reason = "Start >= End"

        # 4. Empty text check
        if not seg["text"].strip():
            error_reason = "Empty text"

        if error_reason:
            deleted_segments.append({
                "Segment": seg["num"],
                "Time": f"{seg['start']} --> {seg['end']}",
                "Text": seg["text"],
                "Error": error_reason
            })
        else:
            valid_segments.append(seg)

        expected_number += 1

    # Renumber valid segments after deletion
    for i, seg in enumerate(valid_segments, start=1):
        seg["num"] = i

    return valid_segments, deleted_segments


# =====================================
# FIX TIMESTAMPS BEFORE MERGE
# =====================================
def fix_srt_timestamps(content):

    def fix_time_format(t):
        if "," in t:
            base, ms = t.split(",")
            ms = (ms + "000")[:3]  # force 3 digits
            return f"{base},{ms}"
        return t + ",000"

    lines = content.split("\n")

    segments = []
    i = 0

    # Parse raw SRT blocks
    while i < len(lines):
        if lines[i].strip().isdigit():

            num = lines[i].strip()
            time_line = lines[i+1].strip() if i+1 < len(lines) else ""

            text_block = []
            j = i + 2

            while j < len(lines) and lines[j].strip():
                text_block.append(lines[j])
                j += 1

            segments.append({
                "num": num,
                "time": time_line,
                "text": text_block
            })

            i = j
        else:
            i += 1

    # Fix time format
    pattern = re.compile(r"(\d{2}:\d{2}:\d{2},?\d*)\s*-->\s*(\d{2}:\d{2}:\d{2},?\d*)")

    for seg in segments:
        match = pattern.match(seg["time"])
        if match:
            start, end = match.groups()
            seg["time"] = f"{fix_time_format(start)} --> {fix_time_format(end)}"

    # Fix logical overlaps
    for idx, seg in enumerate(segments):

        start, end = seg["time"].split(" --> ")

        start_sec = titl_join.to_seconds(start)
        end_sec = titl_join.to_seconds(end)

        # Prevent overlap with previous
        if idx > 0:
            prev_end = titl_join.to_seconds(
                segments[idx-1]["time"].split(" --> ")[1]
            )
            start_sec = max(start_sec, prev_end)

        # Prevent overlap with next
        if idx < len(segments) - 1:
            next_start = titl_join.to_seconds(
                segments[idx+1]["time"].split(" --> ")[0]
            )
            end_sec = min(end_sec, next_start)

        seg["time"] = f"{titl_join.to_srt_time(start_sec)} --> {titl_join.to_srt_time(end_sec)}"

    # Rebuild SRT string
    output = ""
    for i, seg in enumerate(segments, start=1):
        output += f"{i}\n{seg['time']}\n"
        output += "\n".join(seg["text"]) + "\n\n"

    return output


# =====================================
# SAFE FILE DECODING
# Handles multiple encodings
# =====================================
def decode_file(raw_bytes):

    encodings = [
        "utf-8-sig",
        "utf-16",
        "windows-1250",
        "windows-1252",
        "latin-1"
    ]

    for enc in encodings:
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue

    return None


# =====================================
# EXTRACT ORIGINAL SEGMENTS (for Excel)
# =====================================
def extract_original_blocks(segment_ids_str, raw_content):

    if not segment_ids_str:
        return ""

    ids = [int(x.strip()) for x in segment_ids_str.split(",") if x.strip().isdigit()]
    blocks = []

    for oid in ids:
        pattern = rf"{oid}\s+([\d:,]+ --> [\d:,]+)\s+([\s\S]*?)(?=\n\d+\n|$)"
        match = re.search(pattern, raw_content)

        if match:
            time_line = match.group(1)
            text_block = match.group(2).strip()
            blocks.append(f"{oid}\n{time_line}\n{text_block}")

    return "\n\n".join(blocks)


# =====================================
# UI
# =====================================
st.title("📜 SRT Merger + Cleaner")

uploaded_file = st.file_uploader("Upload SRT file", type=["srt"])

if "processed" not in st.session_state:
    st.session_state.processed = False


# =====================================
# PROCESS PIPELINE
# =====================================
if uploaded_file and st.button("🚀 Process SRT"):

    start_time = tm.time()

    raw_bytes = uploaded_file.getvalue()
    content = decode_file(raw_bytes)

    if content is None:
        st.error("❌ Cannot decode file")
        st.stop()

    # Normalize line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Step 1: Fix timestamps
    content = fix_srt_timestamps(content)

    # Step 2: Parse + Merge (clean loop)
    merged_segments, mapping = titl_join.parse_srt(content)

    for MAX_LEN in MAX_LEN_STEPS:
        merged_segments, mapping = titl_join.parse_srt(merged_segments, max_len=MAX_LEN)
    for MAX_LEN in MAX_LEN_STEPS:
        merged_segments, mapping = titl_join.merge_segments(
            merged_segments,
            max_len=MAX_LEN,
            min_duration=MIN_DURATION,
            max_dist_forward=MAX_DIST_FORWARD,
            max_dist_backward=MAX_DIST_BACKWARD
        )

    # Step 3: Validation
    clean_segments, deleted_segments = validate_and_filter_segments(merged_segments)

    # Step 4: Build final SRT
    joined_srt = titl_join.segments_to_srt(clean_segments)

    # =====================================
    # EXCEL OUTPUT
    # =====================================
    df_final = pd.DataFrame([
        {
            "Segment": seg["num"],
            "Time": f"{seg['start']} --> {seg['end']}",
            "Merged Text": seg["text"],
            "Original Segments": ", ".join(map(str, sorted(seg["orig_ids"]))),
            "Original Full Segments": extract_original_blocks(
                ", ".join(map(str, sorted(seg["orig_ids"]))),
                content
            )
        }
        for seg in clean_segments
    ])

    df_deleted = pd.DataFrame(deleted_segments)

    if df_deleted.empty:
        df_deleted = pd.DataFrame([{
            "Segment": "",
            "Time": "",
            "Text": "",
            "Error": "Nema grešaka"
        }])

    # Export Excel
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
        df_final.to_excel(writer, sheet_name="Final Segments", index=False)
        df_deleted.to_excel(writer, sheet_name="Deleted Segments", index=False)

    # Store results
    st.session_state.joined_srt = joined_srt
    st.session_state.excel_bytes = excel_buffer.getvalue()
    st.session_state.processed = True

    # Timing
    total_seconds = tm.time() - start_time
    st.session_state.duration = tm.strftime("%H:%M:%S", tm.gmtime(total_seconds))


# =====================================
# OUTPUT
# =====================================
if st.session_state.processed:

    st.success("✅ Processing complete!")
    st.write(f"⏱️ Time: {st.session_state.duration}")

    st.download_button(
        "📥 Download Cleaned SRT",
        st.session_state.joined_srt,
        file_name="cleaned_merged.srt"
    )

    st.download_button(
        "📊 Download Excel",
        st.session_state.excel_bytes,
        file_name="merged_report.xlsx"
    )
