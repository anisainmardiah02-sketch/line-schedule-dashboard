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

st.markdown("# 🗓️ Weekly Line Schedule")
st.caption("What model is running on each line, each day this week — with Qual runs flagged.")

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
    sched["Qual"] = sched["Remark"].astype(str).str.contains("qual", case=False, na=False)
    return sched


sched = load_schedule(uploaded_file)
line_order = sorted(sched["Line"].dropna().unique(), key=line_sort_key)
dates = sorted(sched["Date"].unique())

# ---- 2. KPI METRICS ----
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total MOs this week", len(sched))
k2.metric("Active lines", sched["Line"].nunique())
k3.metric("Days covered", sched["Date"].nunique())
k4.metric("⚠️ Qual triggers", int(sched["Qual"].sum()))

st.write("")

# ---- 3. QUAL ALERT BANNER ----
qual_rows = sched[sched["Qual"]]
if len(qual_rows) > 0:
    st.error(f"⚠️ {len(qual_rows)} Line Qual run(s) detected this week — check before releasing.")
    for _, row in qual_rows.iterrows():
        remark_snippet = str(row["Remark"]).split("\n")[0][:100]
        st.markdown(
            f"- **{row['Line']}** · {row['Date']} · MO# `{row['MO#']}` · "
            f"{row['Description']} — _{remark_snippet}_"
        )
else:
    st.success("✅ No Line Qual runs flagged this week.")

st.write("")

# ---- 4. LINE × DATE MODEL GRID ----
st.subheader("Model running by line and day")

pivot_desc = (
    sched.groupby(["Line", "Date"])["Description"]
    .apply(lambda x: "; ".join(sorted(set(str(v).strip() for v in x))))
    .unstack(fill_value="")
    .reindex(index=line_order, columns=dates, fill_value="")
)
pivot_qual = (
    sched.groupby(["Line", "Date"])["Qual"]
    .any()
    .unstack(fill_value=False)
    .reindex(index=line_order, columns=dates, fill_value=False)
)

# Format date column headers nicely
pivot_desc.columns = [d.strftime("%a %m/%d") for d in pivot_desc.columns]
pivot_qual.columns = pivot_desc.columns


def highlight_qual(_):
    styles = pivot_qual.map(lambda v: "background-color: #e6c9e0; font-weight: 600;" if v else "")
    return styles


st.dataframe(
    pivot_desc.style.apply(highlight_qual, axis=None),
    use_container_width=True,
)
st.caption("🔴 Highlighted cells contain a Line Qual run that day.")

st.write("")

# ---- 5. FILTERABLE DETAIL TABLE ----
st.subheader("Full schedule detail")

f1, f2, f3 = st.columns([1, 1, 2])
with f1:
    line_filter = st.selectbox("Line", ["All lines"] + line_order)
with f2:
    qual_only = st.checkbox("Show Qual runs only")
with f3:
    search = st.text_input("Search MO#, PN, description...", "")

table = sched.copy()
if line_filter != "All lines":
    table = table[table["Line"] == line_filter]
if qual_only:
    table = table[table["Qual"]]
if search:
    s = search.lower()
    mask = (
        table["MO#"].astype(str).str.lower().str.contains(s)
        | table["PN"].astype(str).str.lower().str.contains(s)
        | table["Description"].astype(str).str.lower().str.contains(s)
    )
    table = table[mask]

display_cols = ["Line", "Date", "Weekday", "MO#", "PN", "Description",
                 "MO Qty", "Plan Qty", "MO status", "Qual"]
display_table = table[display_cols].sort_values(["Date", "Line"])

st.download_button(
    "⬇ Download filtered schedule (CSV)",
    data=display_table.to_csv(index=False).encode("utf-8"),
    file_name="line_schedule.csv",
    mime="text/csv",
)

st.dataframe(display_table, use_container_width=True, hide_index=True)
