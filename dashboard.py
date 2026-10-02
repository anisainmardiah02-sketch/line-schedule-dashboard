import re

import streamlit as st
import pandas as pd

st.set_page_config(page_title="Weekly Line Schedule", layout="wide")

# ---- NUDE PURPLE THEME ----
st.markdown("""
<style>
.stApp { background-color: #f3ede9; }
h1, h2, h3, p, span, label, div { color: #4a3f4a; }
div[data-testid="stMetric"] {
    background-color: #f9f2f6;
    border: 1px solid #e2d3de;
    border-radius: 10px;
    padding: 1rem 1.2rem;
}
div[data-testid="stMetric"] label { color: #8a7086 !important; }
div[data-testid="stMetricValue"] { color: #8a5a8f; }
</style>
""", unsafe_allow_html=True)

# Words searched for in the Remark column. Each trigger type has its own pattern,
# so people can write it in different ways (e.g. "Line Qual", "Internal build", "new PN").
TRIGGER_PATTERNS = {
    "Qual": r"qual",
    "Internal build": r"internal",
    "New PN": r"new\s*p/?n\b|new\s*part",
    "Change from": r"chang(?:e|ed|es)\s+from",
    "Transfer": r"transfer",
    "First build": r"(?:first|1st)[\s-]*build",
}
TRIGGER_TYPES = list(TRIGGER_PATTERNS.keys()) + ["Other keywords"]
TRIGGER_LABEL = " / ".join(TRIGGER_PATTERNS.keys())

st.markdown("# 🗓️ Weekly Line Schedule")
st.caption(f"What model is running on each line, each day this week — with {TRIGGER_LABEL} runs flagged.")

# ---- 1. UPLOAD FILE ----
uploaded_file = st.file_uploader("Upload your PD Schedule Excel file", type=["xlsx"])

if not uploaded_file:
    st.info("Upload your schedule Excel file above. Nothing is saved — it stays only in this session.")
    st.stop()


def line_sort_key(x):
    try:
        return (0, int(str(x)[1:]))
    except ValueError:
        return (1, str(x))


@st.cache_data
def load_schedule(file):
    df = pd.read_excel(file, sheet_name="SMT Schedule", header=None)

    # Each day is its own column block; find them by locating "MO#" headers
    header_row = df.iloc[1]
    block_starts = [c for c in df.columns if str(header_row[c]).strip() == "MO#"]

    # Line label (col 0) only appears on the first row of each MO group — carry it down
    df[0] = df[0].ffill()

    col_labels = ["MO#", "PN", "Description", "MO Qty", "Plan Qty", "MO status",
                  "Release Date", "Pcs/Pnl", "UPH", "LT", "Remark"]

    records = []
    n_cols = df.shape[1]
    for idx, bs in enumerate(block_starts):
        date_val = pd.to_datetime(df.iloc[0, bs]).date()
        weekday = df.iloc[0, bs + 1]

        # Each block runs until the next block's "MO#" (or end of sheet) — width can vary
        block_end = block_starts[idx + 1] if idx + 1 < len(block_starts) else n_cols

        # Find each expected column by matching its header text within this block's range,
        # instead of assuming a fixed column offset (layouts sometimes shift between files)
        col_map = {}
        for c in range(bs, block_end):
            label = str(header_row[c]).strip()
            if label in col_labels and label not in col_map:
                col_map[label] = c

        block = pd.DataFrame(index=df.index[2:])
        for lbl in col_labels:
            if lbl in col_map:
                block[lbl] = df.iloc[2:, col_map[lbl]]
            else:
                block[lbl] = pd.NA
        block.insert(0, "Line", df.iloc[2:, 0])

        block["Date"] = date_val
        block["Weekday"] = weekday
        records.append(block)

    sched = pd.concat(records, ignore_index=True)
    sched = sched.dropna(subset=["MO#"])
    return sched


def find_triggers(remark, extra_words):
    """Return (list of trigger types found, the remark line that mentions it)."""
    if pd.isna(remark):
        return [], ""
    text = str(remark)
    found = [name for name, pat in TRIGGER_PATTERNS.items() if re.search(pat, text, re.IGNORECASE)]
    if any(w in text.lower() for w in extra_words):
        found.append("Other keywords")

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    snippet = lines[0] if lines else ""
    for ln in lines:
        hit = any(re.search(p, ln, re.IGNORECASE) for p in TRIGGER_PATTERNS.values())
        if hit or any(w in ln.lower() for w in extra_words):
            snippet = ln
            break
    return found, snippet[:120]


sched = load_schedule(uploaded_file)
line_order = sorted(sched["Line"].dropna().unique(), key=line_sort_key)
dates = sorted(sched["Date"].unique())

# ---- 2. TRIGGER SETTINGS ----
with st.expander("⚙️ Trigger settings — what counts as a flagged run"):
    st.write(
        "The Remark column is scanned for: **Qual** (e.g. Line Qual), "
        "**Internal build** (the word 'internal'), "
        "**New PN** ('new PN', 'new P/N', 'new part'), "
        "**Change from** ('change from', 'changed from'), "
        "**Transfer**, and **First build** ('first build', '1st build')."
    )
    extra_text = st.text_input(
        "Extra trigger words (comma-separated)", "",
        help="Add any other word people use, e.g. control run, pilot, trial",
    )
extra_words = [w.strip().lower() for w in extra_text.split(",") if w.strip()]

results = sched["Remark"].apply(lambda r: find_triggers(r, extra_words))
sched["Trigger"] = results.apply(lambda x: ", ".join(x[0]))
sched["Snippet"] = results.apply(lambda x: x[1])
sched["Flagged"] = sched["Trigger"] != ""

flagged = sched[sched["Flagged"]]
if len(flagged) > 0:
    groups = (
        flagged.groupby(["Line", "MO#", "Description", "Trigger", "Snippet"], dropna=False)
        .agg(First=("Date", "min"), Last=("Date", "max"))
        .reset_index()
    )
    groups = groups.assign(
        _key=[(g.First, line_sort_key(g.Line)) for g in groups.itertuples()]
    ).sort_values("_key").drop(columns="_key")
else:
    groups = flagged

# ---- 3. KPI METRICS ----
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total MOs this week", len(sched))
k2.metric("Active lines", sched["Line"].nunique())
k3.metric("Days covered", sched["Date"].nunique())
k4.metric("⚠️ Flagged MOs", len(groups))

st.write("")

# ---- 4. FLAGGED RUNS ALERT BANNER ----
if len(groups) > 0:
    st.error(f"⚠️ {len(groups)} flagged MO(s) this week ({TRIGGER_LABEL}) — check before releasing.")
    for _, g in groups.iterrows():
        if g["First"] == g["Last"]:
            when = g["First"].strftime("%d %b")
        else:
            when = f"{g['First'].strftime('%d %b')} – {g['Last'].strftime('%d %b')}"
        st.markdown(
            f"- **{g['Line']}** · {when} · MO# `{g['MO#']}` · {g['Description']} — "
            f"**{g['Trigger']}** — _{g['Snippet']}_"
        )
else:
    st.success(f"✅ No {TRIGGER_LABEL} runs flagged this week.")

st.write("")

# ---- 5. LINE × DATE MODEL GRID ----
st.subheader("Model running by line and day")

pivot_desc = (
    sched.groupby(["Line", "Date"])["Description"]
    .apply(lambda x: "; ".join(sorted(set(str(v).strip() for v in x))))
    .unstack(fill_value="")
    .reindex(index=line_order, columns=dates, fill_value="")
)
pivot_flag = (
    sched.groupby(["Line", "Date"])["Flagged"]
    .any()
    .unstack(fill_value=False)
    .reindex(index=line_order, columns=dates, fill_value=False)
)

# Format date column headers nicely
pivot_desc.columns = [d.strftime("%a %m/%d") for d in pivot_desc.columns]
pivot_flag.columns = pivot_desc.columns


def highlight_flagged(_):
    return pivot_flag.map(lambda v: "background-color: #e6c9e0; font-weight: 600;" if v else "")


st.dataframe(
    pivot_desc.style.apply(highlight_flagged, axis=None),
    use_container_width=True,
)
st.caption(f"🟪 Highlighted cells contain a flagged run ({TRIGGER_LABEL}) that day.")

st.write("")

# ---- 6. FILTERABLE DETAIL TABLE ----
st.subheader("Full schedule detail")

f1, f2, f3 = st.columns([1, 1, 2])
with f1:
    line_filter = st.selectbox("Line", ["All lines"] + line_order)
with f2:
    trigger_filter = st.selectbox("Show", ["All runs", "Any flagged"] + TRIGGER_TYPES)
with f3:
    search = st.text_input("Search MO#, PN, description...", "")

table = sched.copy()
if line_filter != "All lines":
    table = table[table["Line"] == line_filter]
if trigger_filter == "Any flagged":
    table = table[table["Flagged"]]
elif trigger_filter != "All runs":
    table = table[table["Trigger"].str.contains(trigger_filter, regex=False)]
if search:
    s = search.lower()
    mask = (
        table["MO#"].astype(str).str.lower().str.contains(s)
        | table["PN"].astype(str).str.lower().str.contains(s)
        | table["Description"].astype(str).str.lower().str.contains(s)
    )
    table = table[mask]

display_cols = ["Line", "Date", "Weekday", "MO#", "PN", "Description",
                 "MO Qty", "Plan Qty", "MO status", "Trigger"]
display_table = table[display_cols].sort_values(["Date", "Line"])

st.download_button(
    "⬇ Download filtered schedule (CSV)",
    data=display_table.to_csv(index=False).encode("utf-8"),
    file_name="line_schedule.csv",
    mime="text/csv",
)

st.dataframe(display_table, use_container_width=True, hide_index=True)
