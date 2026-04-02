import streamlit as st
import pandas as pd
from io import BytesIO
import titl_join
import time as tm

# =====================================
# CONFIG
# =====================================
MAX_LEN_STEPS = (60, 120, 140)

MIN_DURATION = 1.0
MAX_DIST_FORWARD = 0.1
MAX_DIST_BACKWARD = 1.0

APP_PASSWORD = st.secrets["APP_PASSWORD"]

# =====================================
# PASSWORD
# =====================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔐 Subtitle Merger Login")
    password_input = st.text_input("Enter password", type="password")

    if st.button("Login"):
        if password_input == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")

    st.stop()

# =====================================
# UI
# =====================================
st.title("📜 SRT Merger (No AI)")

uploaded_file = st.file_uploader("Upload SRT file", type=["srt"])

if "processed" not in st.session_state:
    st.session_state.processed = False

# =====================================
# PROCESS
# =====================================
if uploaded_file and st.button("🚀 Process SRT"):

    start_time = tm.time()

    raw_bytes = uploaded_file.getvalue()
    content = raw_bytes.decode("utf-8-sig")

    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # INITIAL PARSE
    merged_segments, mapping = titl_join.parse_srt(content)

    # ITERATIVE MERGING
    for MAX_LEN in MAX_LEN_STEPS:
        merged_segments, mapping = titl_join.parse_srt(
            merged_segments,
            max_len=MAX_LEN
        )

        merged_segments, mapping = titl_join.merge_segments(
            merged_segments,
            max_len=MAX_LEN,
            min_duration=MIN_DURATION,
            max_dist_forward=MAX_DIST_FORWARD,
            max_dist_backward=MAX_DIST_BACKWARD
        )

    # FINAL SRT
    joined_srt = titl_join.segments_to_srt(merged_segments)

    # =====================================
    # EXCEL DATA (ONLY MERGING INFO)
    # =====================================
    df_data = []

    for i, seg in enumerate(merged_segments, start=1):
        df_data.append({
            "Segment": i,
            "Time": f"{seg['start']} --> {seg['end']}",
            "Merged Text": seg["text"],
            "Original Segments": ", ".join(
                map(str, sorted(seg["orig_ids"]))
            )
        })

    df_final = pd.DataFrame(df_data)

    # EXPORT EXCEL
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
        df_final.to_excel(writer, sheet_name="Merged Segments", index=False)

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
        "📥 Download Merged SRT",
        st.session_state.joined_srt,
        file_name="merged.srt"
    )

    st.download_button(
        "📊 Download Excel",
        st.session_state.excel_bytes,
        file_name="merged_report.xlsx"
    )
