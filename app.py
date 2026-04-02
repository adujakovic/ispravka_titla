import streamlit as st
import pandas as pd
from io import BytesIO
import titl_join
import time as tm
import re

# =====================================
# CONFIG
# =====================================
MAX_LEN_STEPS = (60, 120, 140)

MIN_DURATION = 1.0
MAX_DIST_FORWARD = 0.1
MAX_DIST_BACKWARD = 1.0


# =====================================
# VALIDATION + FILTER
# =====================================
def validate_and_filter_segments(segments):

    time_pattern = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}$")

    valid_segments = []
    deleted_segments = []

    expected_number = 1

    for seg in segments:

        error_reason = None

        # 1. broj
        if seg["num"] != expected_number:
            error_reason = f"Pogrešan redoslijed (očekivano {expected_number})"

        # 2. vrijeme format
        if not time_pattern.match(seg["start"]) or not time_pattern.match(seg["end"]):
            error_reason = "Neispravan format vremena"

        # 3. start >= end
        if seg["start"] >= seg["end"]:
            error_reason = "Start >= End"

        # 4. tekst
        if not seg["text"].strip():
            error_reason = "Prazan tekst"

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

    # renumeracija
    for i, seg in enumerate(valid_segments, start=1):
        seg["num"] = i

    return valid_segments, deleted_segments


# =====================================
# PASSWORD
# =====================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔐 Subtitle Merger Login")

# =====================================
# UI
# =====================================
st.title("📜 SRT Merger + Cleaner")

uploaded_file = st.file_uploader("Upload SRT file", type=["srt"])

if "processed" not in st.session_state:
    st.session_state.processed = False

# =====================================
# PROCESS
# =====================================
if uploaded_file and st.button("🚀 Process SRT"):

    start_time = tm.time()

    raw_bytes = uploaded_file.getvalue()
    
    encodings = [
        "utf-8-sig",
        "utf-16",
        "windows-1250",
        "windows-1252",
        "latin-1"
    ]
    
    content = None
    
    for enc in encodings:
        try:
            content = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    
    if content is None:
        st.error("❌ Ne mogu pročitati encoding fajla")
        st.stop()  
    


    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # INITIAL PARSE
    merged_segments, mapping = titl_join.parse_srt(content)

    # ITERATIVE MERGING
    for MAX_LEN in MAX_LEN_STEPS:
        merged_segments, mapping = titl_join.parse_srt(
            merged_segments,
            max_len=MAX_LEN
        )
    for MAX_LEN in MAX_LEN_STEPS:
        merged_segments, mapping = titl_join.merge_segments(
            merged_segments,
            max_len=MAX_LEN,
            min_duration=MIN_DURATION,
            max_dist_forward=MAX_DIST_FORWARD,
            max_dist_backward=MAX_DIST_BACKWARD
        )

    # =====================================
    # VALIDATION + FILTER
    # =====================================
    clean_segments, deleted_segments = validate_and_filter_segments(merged_segments)

    # FINAL SRT
    joined_srt = titl_join.segments_to_srt(clean_segments)

    # =====================================
    # EXCEL DATA
    # =====================================
    df_final = pd.DataFrame([
        {
            "Segment": seg["num"],
            "Time": f"{seg['start']} --> {seg['end']}",
            "Merged Text": seg["text"],
            "Original Segments": ", ".join(map(str, sorted(seg["orig_ids"])))
        }
        for seg in clean_segments
    ])

    df_deleted = pd.DataFrame(deleted_segments)

    # EXPORT EXCEL
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
        df_final.to_excel(writer, sheet_name="Final Segments", index=False)
        if df_deleted.empty:
            df_deleted = pd.DataFrame([{
                "Segment": "",
                "Time": "",
                "Text": "",
                "Error": "Nema grešaka"
            }])
        
        df_deleted.to_excel(writer, sheet_name="Deleted Segments", index=False)
    # STORE
    st.session_state.joined_srt = joined_srt
    st.session_state.excel_bytes = excel_buffer.getvalue()
    st.session_state.processed = True

    end_time = tm.time()
    total_seconds = end_time - start_time

    st.session_state.duration = tm.strftime(
        "%H:%M:%S",
        tm.gmtime(total_seconds)
    )

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
