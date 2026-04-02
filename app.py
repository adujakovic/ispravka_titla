import streamlit as st
import re
import pandas as pd
from openai import OpenAI
import tiktoken
from io import BytesIO
import titl_join
import time as tm

# =====================================
# CONFIG
# =====================================
MODEL = "gpt-4.1"
BATCH_SIZE = 200

INPUT_COST = 0.00015
OUTPUT_COST = 0.0006

MAX_LEN_STEPS = (60, 120, 140)

MIN_DURATION = 1.0
MAX_DIST_FORWARD = 0.1
MAX_DIST_BACKWARD = 1.0

# =====================================
# LOAD SECRETS
# =====================================
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
APP_PASSWORD = st.secrets["APP_PASSWORD"]

client = OpenAI(api_key=OPENAI_API_KEY)

# =====================================
# PASSWORD PROTECTION
# =====================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔐 Subtitle Corrector Login")
    password_input = st.text_input("Enter password", type="password")

    if st.button("Login"):
        if password_input == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")

    st.stop()

# =====================================
# PROMPT PARTS
# =====================================
PROMPT_PART_1 = """Ispravi pravopisne i gramatičke pogreške u ovom hrvatskom tekstu.
Strogo poštuj ova pravila:
"""

DEFAULT_RULES = """- Ne dodaj nove riječi osim ako je to nužno za potpunu gramatičku ispravnost.
- Ne mijenjaj redoslijed riječi osim ako je očito gramatički netočan.
- Ne mijenjaj stil, ton ili biblijski izraz osim ako je riječ ili struktura objektivno netočna.
- Ne dodaj dodatnu interpunkciju osim ako je nužna radi gramatičke ispravnosti.
- Ako je rečenica upitna ili nalik upitnoj, možeš dodati "li" ili "je" radi ispravne forme pitanja.
- Riječi 'Riječ', 'Misija', 'Biblija', 'Sveto Pismo', 'Pismo', 'Pismu', 'Čista Istina',
  'Otac', 'Oče', 'Očeva', 'Očevu' uvijek piši s velikim početnim slovom.
- Sve riječi koje počinju s 'božansk' piši s velikim početnim slovom.
- Zamjenice (On, Njega, Njegov...) piši velikim slovom samo ako je jasno da se odnose na Boga ili Isusa Krista.
- Ako se znak '.' nalazi između dva broja (npr. 3.1), zamijeni ga s ':'.
- Nikad ne uklanjaj znak '-'.
- Brojeve zapisane slovima pretvori u znamenke.
- Ako je broj na početku rečenice, ostavi ga slovima.
"""

PROMPT_PART_3 = """
- Svaka ulazna linija mora imati točno jednu izlaznu liniju.

Vrati točno isti broj linija, s istim redoslijedom i istim brojevima.

Format:
1) tekst
2) tekst

Tekst:
{lines}
"""

# =====================================
# TOKEN COUNTING
# =====================================
def count_tokens(text):
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))

# =====================================
# ALIGNMENT LOGIC
# =====================================
def align_lines(original_batch, corrected_texts):

    filtered = [line for line in corrected_texts if line.strip()]

    if len(filtered) < len(original_batch):
        filtered += [
            orig_text for (_, _, orig_text) in original_batch[len(filtered):]
        ]
    elif len(filtered) > len(original_batch):
        filtered = filtered[:len(original_batch)]

    return filtered
    
def generate_response(model, prompt, temperature=0):
    try:
        # First try new Responses API (GPT-5 compatible)
        response = client.responses.create(
            model=model,
            input=prompt,
            temperature=temperature
        )
        return response.output_text

    except Exception:
        # Fallback to legacy Chat Completions (GPT-4 compatible)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature
        )
        return response.choices[0].message.content




# =====================================
# UI
# =====================================
st.title("📜 Korekcija SRT filea HRV")

st.subheader("⚙️ Uredi pravila korekcije")

if "custom_rules" not in st.session_state:
    st.session_state.custom_rules = DEFAULT_RULES

custom_rules = st.text_area(
    "Pravila (možeš dodavati ili brisati):",
    value=st.session_state.custom_rules,
    height=300
)

st.session_state.custom_rules = custom_rules

uploaded_file = st.file_uploader("Upload SRT file", type=["srt"])

if "processed" not in st.session_state:
    st.session_state.processed = False

# =====================================
# PROCESS
# =====================================
if uploaded_file and st.button("🚀 Pokreni korekciju SRT"):
    start_time = tm.time()
    content = uploaded_file.read().decode("utf-8-sig")
    raw_bytes = uploaded_file.getvalue()
    content = raw_bytes.decode("utf-8-sig")
    
    # NORMALIZE LINE ENDINGS
    content = content.replace("\r\n", "\n").replace("\r", "\n")


    merged_segments, mapping = titl_join.parse_srt(content)

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

    joined_srt = titl_join.segments_to_srt(merged_segments)

    segments = [
        (str(i+1), f"{seg['start']} --> {seg['end']}", seg["text"])
        for i, seg in enumerate(merged_segments)
    ]

    df_data = []
    total_cost = 0.0
    corrected_srt_output = ""

    total_input_tokens = 0
    total_output_tokens = 0

    progress = st.progress(0)

    for batch_num, i in enumerate(range(0, len(segments), BATCH_SIZE), start=1):

        batch = segments[i:i+BATCH_SIZE]

        lines_text = "\n".join(
            [f"{j+1}) {text}" for j, (_, _, text) in enumerate(batch)]
        )

        PROMPT_TEMPLATE = (
            PROMPT_PART_1
            + st.session_state.custom_rules
            + PROMPT_PART_3
        )

        prompt = PROMPT_TEMPLATE.format(lines=lines_text)

        input_tokens = count_tokens(prompt)



        output_text = generate_response(MODEL, prompt, temperature=0)
        output_tokens = count_tokens(output_text)

        total_input_tokens += input_tokens
        total_output_tokens += output_tokens

        real_cost = (
            (input_tokens / 1000 * INPUT_COST) +
            (output_tokens / 1000 * OUTPUT_COST)
        )

        total_cost += real_cost

        corrected = [
            re.sub(r"^\s*\d+\)\s*", "", line).strip()
            for line in output_text.split("\n")
            if re.match(r"^\s*\d+\)", line)
        ]

        corrected = align_lines(batch, corrected)

        for (num, time, original), corrected_text in zip(batch, corrected):

            df_data.append({
                "Final Segment": num,
                "Vrijeme": time,
                "Final Text": corrected_text,
                "Original Segments": ", ".join(
                    map(str, sorted(
                        merged_segments[int(num)-1]["orig_ids"]
                    ))
                )
            })

            corrected_srt_output += f"{num}\n{time}\n{corrected_text}\n\n"

        progress.progress(min((i+BATCH_SIZE)/len(segments), 1.0))

    # =====================================
    # EXCEL EXPORT
    # =====================================
    df_final = pd.DataFrame(df_data)

    def extract_original_blocks(segment_list_str, raw_content):
        if not segment_list_str:
            return ""

        ids = [int(x.strip()) for x in segment_list_str.split(",") if x.strip().isdigit()]
        blocks = []

        for oid in ids:
            pattern = rf"{oid}\s+([\d:,]+ --> [\d:,]+)\s+([\s\S]*?)(?=\n\d+\n|$)"
            match = re.search(pattern, raw_content)

            if match:
                time_line = match.group(1)
                text_block = match.group(2).strip()
                blocks.append(f"{oid}\n{time_line}\n{text_block}")

        return "\n\n".join(blocks)

    df_final["Original Full Segments"] = df_final["Original Segments"].apply(
        lambda x: extract_original_blocks(x, content)
    )
    # =====================================
    # ADD MERGED TEXT COMPARISON
    # =====================================
    
    # Map merged segment number -> original merged text (before OpenAI)
    merged_text_map = {
        str(i + 1): seg["text"]
        for i, seg in enumerate(merged_segments)
    }
    
    # Add Text_before column (original merged text)
    df_final["Text_before"] = df_final["Final Segment"].map(merged_text_map)
    
    # Add equality column
    df_final["Isti tekst?"] = df_final["Text_before"] == df_final["Final Text"]
    
    # OPTIONAL: move columns so they appear next to Final Text
    cols = df_final.columns.tolist()
    
    # Reorder columns: insert Text_before before Final Text,
    # and Isti tekst? right after Final Text
    final_text_index = cols.index("Final Text")
    
    new_order = (
        cols[:final_text_index] +
        ["Text_before", "Final Text", "Isti tekst?"] +
        [c for c in cols[final_text_index+1:] if c not in ["Text_before", "Isti tekst?"]]
    )
    
    df_final = df_final[new_order]
    
    excel_buffer = BytesIO()

    with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
        df_final.to_excel(writer, sheet_name="Final Mapping", index=False)

    # STORE SESSION STATE
    st.session_state.corrected_srt = corrected_srt_output
    st.session_state.joined_srt = joined_srt
    st.session_state.excel_bytes = excel_buffer.getvalue()
    st.session_state.total_cost = total_cost
    st.session_state.total_input_tokens = total_input_tokens
    st.session_state.total_output_tokens = total_output_tokens
    st.session_state.processed = True
    end_time = tm.time()
    total_seconds = end_time - start_time
    
    st.session_state.formatted_duration = tm.strftime(
        "%H:%M:%S",
        tm.gmtime(total_seconds)
    )
    

# =====================================
# DISPLAY RESULTS
# =====================================
if st.session_state.processed:

    st.success("✅ Processing complete!")

    st.write(f"💰 Total cost (zanemari): ${st.session_state.total_cost:.6f}")
    st.write(f"📥 Input tokens: {st.session_state.total_input_tokens:,}")
    st.write(f"📤 Output tokens: {st.session_state.total_output_tokens:,}")
    st.write(
        f"🔢 Total tokens: "
        f"{st.session_state.total_input_tokens + st.session_state.total_output_tokens:,}"
    )


    st.write(f"⏱️ Ukupno vrijeme obrade: {st.session_state.formatted_duration}")

    st.download_button(
        "📥 Download Corrected SRT",
        st.session_state.corrected_srt,
        file_name="corrected.srt"
    )

    st.download_button(
        "📊 Download Excel Report",
        st.session_state.excel_bytes,
        file_name="report.xlsx"
    )









































