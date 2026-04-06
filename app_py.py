import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import re, io

# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Ruvixx · Case Investigation",
    page_icon="🔶",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
ORG, GRN, RED = "#F97316", "#16A34A", "#EF4444"

MCC_SET = {
    "mexico","colombia","ecuador","costa rica","dominican republic",
    "el salvador","panama","guatemala","honduras","nicaragua","belize",
}
CS_SET = {
    "argentina","chile","brazil","uruguay","paraguay","bolivia","peru","venezuela",
}
COUNTRY_FIX = {
    "domican republic": "Dominican Republic",
    "dominican repbulic": "Dominican Republic",
    "belice": "Belize",
    "bolivar": "Bolivia",
    "ecuardor": "Ecuador",
}
REGIONS = {
    "MCC": {
        "name": "México Central Caribe", "contact": "Tatiana Romero",
        "pills": ["MX","CO","EC","GT","DO","CR","SV","PA","HN","NI","BZ"],
        "groups": [
            {"label": "Mexico",                 "countries": ["Mexico"],                                   "quota": 25},
            {"label": "Colombia + Ecuador",      "countries": ["Colombia","Ecuador"],                       "quota": 30},
            {"label": "CR + Dom. Rep. + Panama", "countries": ["Costa Rica","Dominican Republic","Panama"], "quota": 25},
            {"label": "Nicaragua",               "countries": ["Nicaragua"],                                "quota": 1},
            {"label": "Guatemala",               "countries": ["Guatemala"],                                "quota": 1},
            {"label": "El Salvador",             "countries": ["El Salvador"],                              "quota": 1},
            {"label": "Honduras",                "countries": ["Honduras"],                                 "quota": 1},
            {"label": "Belize",                  "countries": ["Belize"],                                   "quota": 1},
        ],
        "total_quota": 85, "daily_min": 5, "daily_ideal": 8,
        "weekly_min": 25, "weekly_ideal": 40, "support": ["Luis"],
    },
    "CS": {
        "name": "Cono Sur", "contact": "Ignacio Duce",
        "pills": ["AR","CL","BR","UY","PY","BO","PE","VE"],
        "groups": [
            {"label": "Argentina", "countries": ["Argentina"], "quota": 20},
            {"label": "Chile",     "countries": ["Chile"],     "quota": 25},
            {"label": "Peru",      "countries": ["Peru"],      "quota": 25},
            {"label": "Bolivia",   "countries": ["Bolivia"],   "quota": 5},
            {"label": "Paraguay",  "countries": ["Paraguay"],  "quota": 5},
            {"label": "Uruguay",   "countries": ["Uruguay"],   "quota": 5},
        ],
        "total_quota": 85, "daily_min": 5, "daily_ideal": 8,
        "weekly_min": 25, "weekly_ideal": 40, "support": [],
    },
}
DISQ_KW = [
    "disqualif","rejected","rjected","duplicate","duplicado",
    "already contacted","entity already","repeated","case related",
]

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def norm_country(c):
    if not c or str(c).strip() in ("", "nan", "None"):
        return ""
    t = str(c).strip()
    return COUNTRY_FIX.get(t.lower(), t)

def get_region(country):
    l = country.lower()
    if l in MCC_SET: return "MCC"
    if l in CS_SET:  return "CS"
    return None

def is_disq(qa):
    q = str(qa or "").lower()
    return any(k in q for k in DISQ_KW)

def parse_date_val(val):
    if val is None: return None
    try:
        if isinstance(val, (datetime, date)):
            v = val if isinstance(val, datetime) else datetime(val.year, val.month, val.day)
            return v.strftime("%Y-%m-%d")
    except Exception:
        pass
    s = str(val).strip()
    if not s or s in ("nan", "None", "NaT", ""):
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (2020 <= y <= 2035):
            return None
        mo, d = (b, a) if a > 12 else (a, b)
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y}-{mo:02d}-{d:02d}"
    try:
        dt = pd.to_datetime(s, dayfirst=False, errors="coerce")
        if pd.notna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return None

def parse_wide(df_raw):
    """Parse wide-format spreadsheet: scan for 'Date' headers, extract groups."""
    rows = df_raw.values.tolist()
    if len(rows) < 2:
        return pd.DataFrame()
    headers = [str(h).strip() if h is not None and str(h) != "nan" else "" for h in rows[0]]
    date_positions = [i for i, h in enumerate(headers) if h == "Date"]

    records, seen = [], set()
    for dp in date_positions:
        for row in rows[1:]:
            try:
                ds  = parse_date_val(row[dp] if dp < len(row) else None)
                cid = str(row[dp+1] if dp+1 < len(row) else "").strip().strip("\"'")
                ctr = norm_country(row[dp+3] if dp+3 < len(row) else "")
                inv = str(row[dp+4] if dp+4 < len(row) else "").strip()
                qa  = str(row[dp+5] if dp+5 < len(row) else "")
                if not ds or not cid or not ctr or not inv or inv in ("nan","None",""):
                    continue
                if is_disq(qa):
                    continue
                region = get_region(ctr)
                if not region:
                    continue
                key = f"{cid}|{ds}|{inv}"
                if key in seen:
                    continue
                seen.add(key)
                records.append({"date": ds, "case_id": cid, "country": ctr,
                                 "investigator": inv, "region": region})
            except Exception:
                continue

    return pd.DataFrame(records) if records else pd.DataFrame(
        columns=["date","case_id","country","investigator","region"])

def read_file(f):
    name = f.name.lower()
    try:
        if name.endswith((".xlsx", ".xls")):
            return pd.read_excel(f, header=None, dtype=str, engine="openpyxl")
        content = f.read()
        f.seek(0)
        text = content.decode("utf-8", errors="replace")
        sep = "\t" if "\t" in text.split("\n")[0] else ","
        return pd.read_csv(io.StringIO(text), header=None, sep=sep, dtype=str)
    except Exception as e:
        st.error(f"Error reading {f.name}: {e}")
        return pd.DataFrame()

def get_weeks(year, month):
    weeks = []
    first = date(year, month, 1)
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(1)
    cur = first - timedelta(first.weekday())           # back to Monday
    while cur <= last:
        end = cur + timedelta(4)                       # Friday
        if end >= first and cur <= last:
            weeks.append({
                "start": cur.strftime("%Y-%m-%d"),
                "end":   end.strftime("%Y-%m-%d"),
                "label": f"{cur.strftime('%b')} {cur.day} – {end.strftime('%b')} {end.day}",
            })
        cur += timedelta(7)
    return weeks

def fmt_day(ds):
    d = datetime.strptime(ds, "%Y-%m-%d")
    return f"{d.strftime('%b')} {d.day}"

def dot_color(n, mn, ideal):
    if not n:       return "#FEE2CC"
    if n >= ideal:  return GRN
    if n >= mn:     return ORG
    return RED

def badge_for(total, wmin, wideal):
    if not total:          return "No data",   "#FEE2E2", RED
    if total >= wideal:    return "Ideal",      "#DCFCE7", GRN
    if total >= wmin:      return "Above min",  "#FEF9C3", "#CA8A04"
    return "Below min", "#FEE2E2", RED

# ──────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────────────────────
EMPTY_DF = pd.DataFrame(columns=["date","case_id","country","investigator","region"])
for k, v in [("data", EMPTY_DF), ("files", []), ("tab", "MCC"), ("dark", False)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ──────────────────────────────────────────────────────────────────────────────
# THEME
# ──────────────────────────────────────────────────────────────────────────────
dark = st.session_state.dark
BG   = "#1A1614" if dark else "#FEF9F5"
CARD = "#242120" if dark else "#FFFFFF"
BORD = "#3D3532" if dark else "#FED7AA"
TX   = "#FAFAF9" if dark else "#1C1917"
TX2  = "#A8A29E" if dark else "#78716C"
OL   = "#431407" if dark else "#FEF3EA"
OB   = "#7C2D12" if dark else "#FED7AA"
PLT  = "plotly_dark" if dark else "plotly_white"

# ──────────────────────────────────────────────────────────────────────────────
# GLOBAL CSS
# ──────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
  .stApp {{ background-color: {BG} !important; }}
  .main .block-container {{ padding: 1rem 2rem 2rem; max-width: 1440px; }}
  #MainMenu, footer, header {{ visibility: hidden; }}

  /* Hide file-uploader drag zone — keep only the Browse button */
  [data-testid="stFileUploaderDropzone"] {{ display: none !important; }}
  [data-testid="stFileUploaderDropzoneInstructions"] {{ display: none !important; }}
  [data-testid="stFileUploader"] > section {{ padding: 0 !important; }}
  [data-testid="stFileUploader"] label {{ font-size: 12px !important; color: {TX2} !important; }}

  /* Cards via st.container(border=True) */
  [data-testid="stVerticalBlockBorderWrapper"] {{
      border: 1px solid {BORD} !important;
      border-radius: 14px !important;
      background: {CARD} !important;
  }}

  /* Section labels */
  .sec-lbl {{
      font-size: 10px; font-weight: 700; color: {ORG};
      letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 12px;
  }}
  /* Progress bars */
  .pw {{ height: 7px; background: {"#44403C" if dark else "#FEE2CC"}; border-radius: 4px; margin: 4px 0; }}
  .pf {{ height: 100%; border-radius: 4px; }}
  /* Highlights */
  .hl {{ display: flex; align-items: flex-start; gap: 8px; margin-bottom: 10px; }}
  .hd {{ width: 7px; height: 7px; border-radius: 50%; margin-top: 4px;
          flex-shrink: 0; display: inline-block; }}

  /* Primary button → orange */
  [data-testid="stButton"] button[kind="primary"] {{
      background: {ORG} !important;
      color: white !important;
      border: none !important;
  }}
  [data-testid="stButton"] button[kind="secondary"] {{
      background: {CARD} !important;
      color: {TX} !important;
      border: 1px solid {BORD} !important;
  }}

  /* Divider */
  hr {{ border-color: {BORD}; margin: 6px 0; }}

  /* Selectbox */
  [data-testid="stSelectbox"] > div > div {{
      background: {CARD} !important;
      border-color: {BORD} !important;
      color: {TX} !important;
  }}

  /* General text */
  p, span, label, div {{ color: {TX}; }}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# TOP BAR
# ──────────────────────────────────────────────────────────────────────────────
cfg = REGIONS[st.session_state.tab]

col_logo, col_mcc, col_cs, col_region, col_theme = st.columns([1.4, 1, 1, 4.5, 0.5])

with col_logo:
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:8px;padding:5px 0">
      <div style="width:30px;height:30px;background:{ORG};border-radius:7px;
                  display:flex;align-items:center;justify-content:center;
                  color:white;font-weight:800;font-size:14px;flex-shrink:0">R</div>
      <div>
        <div style="font-weight:700;font-size:13px;color:{TX}">ruvixx</div>
        <div style="font-size:8px;color:{TX2};letter-spacing:.06em;
                    text-transform:uppercase">Case Investigation</div>
      </div>
    </div>""", unsafe_allow_html=True)

with col_mcc:
    if st.button("México CC", key="btn_mcc",
                 type="primary" if st.session_state.tab == "MCC" else "secondary",
                 use_container_width=True):
        st.session_state.tab = "MCC"
        st.rerun()

with col_cs:
    if st.button("Cono Sur", key="btn_cs",
                 type="primary" if st.session_state.tab == "CS" else "secondary",
                 use_container_width=True):
        st.session_state.tab = "CS"
        st.rerun()

with col_region:
    pills = "".join(
        f'<span style="font-size:9px;font-weight:700;background:{ORG};color:white;'
        f'border-radius:3px;padding:1px 4px;margin:0 1px">{p}</span>'
        for p in cfg["pills"]
    )
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:6px;background:{OL};
                border:1px solid {OB};border-radius:8px;padding:6px 10px;
                font-size:12px;color:#92400E;font-weight:500;flex-wrap:wrap">
      <span style="width:7px;height:7px;border-radius:50%;background:{ORG};
                   display:inline-block;flex-shrink:0"></span>
      {cfg["name"]} · {cfg["contact"]}  {pills}
    </div>""", unsafe_allow_html=True)

with col_theme:
    if st.button("🌙" if not dark else "☀️", key="theme_btn", use_container_width=True):
        st.session_state.dark = not st.session_state.dark
        st.rerun()

st.markdown(f'<hr style="border-color:{BORD}">', unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# CONTROLS: month / week / upload
# ──────────────────────────────────────────────────────────────────────────────
data     = st.session_state.data
has_data = not data.empty

months_avail = []
if has_data:
    for ms in sorted(data["date"].str[:7].unique()):
        y, m = int(ms[:4]), int(ms[5:7])
        months_avail.append({"year": y, "month": m,
                              "label": datetime(y, m, 1).strftime("%B %Y")})
if not months_avail:
    t = datetime.today()
    months_avail = [{"year": t.year, "month": t.month, "label": t.strftime("%B %Y")}]

ctl1, ctl2, ctl3, ctl4 = st.columns([2, 2, 1.6, 3])

with ctl1:
    sel_m_lbl = st.selectbox("Month", [m["label"] for m in months_avail],
                              index=len(months_avail) - 1,
                              label_visibility="collapsed", key="sel_month")
    sel_month = next(m for m in months_avail if m["label"] == sel_m_lbl)

with ctl2:
    weeks     = get_weeks(sel_month["year"], sel_month["month"])
    w_labels  = [f"Week of {w['label']}" for w in weeks]
    sel_w_lbl = st.selectbox("Week", w_labels, label_visibility="collapsed", key="sel_week")
    sel_week  = weeks[w_labels.index(sel_w_lbl)]

with ctl3:
    uploaded = st.file_uploader(
        "📂 Load data", type=["csv","xlsx","xls","tsv"],
        accept_multiple_files=True, key="uploader",
        label_visibility="visible",
        help="Upload your wide-format Excel/CSV export (March, April, …). Multiple files are merged automatically.",
    )
    if uploaded:
        added = False
        for f in uploaded:
            if f.name not in st.session_state.files:
                raw = read_file(f)
                if not raw.empty:
                    parsed = parse_wide(raw)
                    if not parsed.empty:
                        combined = pd.concat([st.session_state.data, parsed], ignore_index=True)
                        combined = combined.drop_duplicates(subset=["case_id","date","investigator"])
                        st.session_state.data = combined
                        st.session_state.files.append(f.name)
                        added = True
        if added:
            st.rerun()

with ctl4:
    if has_data:
        n_mcc = len(data[data["region"] == "MCC"])
        n_cs  = len(data[data["region"] == "CS"])
        clr_c, info_c = st.columns([1, 3])
        with clr_c:
            if st.button("Clear", key="clear_btn"):
                st.session_state.data  = EMPTY_DF.copy()
                st.session_state.files = []
                st.rerun()
        with info_c:
            st.markdown(f"""
            <div style="font-size:11px;color:{TX2};padding-top:6px;line-height:1.6">
              {len(data)} cases · MCC: {n_mcc} · CS: {n_cs}<br>
              <span style="color:{ORG}">{', '.join(st.session_state.files)}</span>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="font-size:11px;color:{TX2};padding-top:8px">
          No data loaded — upload your case export to populate the dashboard.
        </div>""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# COMPUTE METRICS
# ──────────────────────────────────────────────────────────────────────────────
cfg    = REGIONS[st.session_state.tab]
r_data = data[data["region"] == st.session_state.tab] if has_data else pd.DataFrame()
w_data = (
    r_data[(r_data["date"] >= sel_week["start"]) & (r_data["date"] <= sel_week["end"])]
    if not r_data.empty else pd.DataFrame()
)

total = len(w_data)
gap   = max(0, cfg["total_quota"] - total)
pct   = min(100, round(total / cfg["total_quota"] * 100)) if cfg["total_quota"] else 0

groups = [
    {**g, "done": len(w_data[w_data["country"].isin(g["countries"])]) if not w_data.empty else 0}
    for g in cfg["groups"]
]

invs = []
if not w_data.empty:
    for inv_name, grp in sorted(w_data.groupby("investigator"), key=lambda x: -len(x[1])):
        invs.append({
            "name":    inv_name,
            "total":   len(grp),
            "by_day":  grp.groupby("date").size().to_dict(),
            "support": inv_name in cfg["support"],
        })

# Week days Mon–Fri
w_days = []
d_cur  = datetime.strptime(sel_week["start"], "%Y-%m-%d")
d_end  = datetime.strptime(sel_week["end"],   "%Y-%m-%d")
while d_cur <= d_end:
    ds = d_cur.strftime("%Y-%m-%d")
    w_days.append({
        "ds":    ds,
        "label": fmt_day(ds),
        "day":   str(d_cur.day),
        "total": len(w_data[w_data["date"] == ds]) if not w_data.empty else 0,
    })
    d_cur += timedelta(1)

by_country  = (w_data.groupby("country").size().sort_values(ascending=False).to_dict()
               if not w_data.empty else {})
by_inv_stat = [{"name": i["name"], "total": i["total"],
                "pct": round(i["total"] / total * 100) if total else 0,
                "support": i["support"]}
               for i in invs]

# ──────────────────────────────────────────────────────────────────────────────
# SUMMARY METRIC ROW
# ──────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="display:flex;justify-content:flex-end;align-items:center;
            gap:28px;padding:8px 0 12px">
  <div style="text-align:center">
    <div style="font-size:22px;font-weight:800;color:{ORG};line-height:1">{total}</div>
    <div style="font-size:9px;color:{TX2};text-transform:uppercase;letter-spacing:.06em">Cases Generated</div>
  </div>
  <div style="text-align:center">
    <div style="font-size:22px;font-weight:800;color:{ORG};line-height:1">{gap}</div>
    <div style="font-size:9px;color:{TX2};text-transform:uppercase;letter-spacing:.06em">Quota Gap</div>
  </div>
  <div style="text-align:center">
    <div style="font-size:22px;font-weight:800;color:{ORG};line-height:1">{pct}%</div>
    <div style="font-size:9px;color:{TX2};text-transform:uppercase;letter-spacing:.06em">Quota Progress</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:12px;font-weight:700;color:{TX}">Trimble LATAM</div>
    <div style="font-size:10px;color:{TX2}">{sel_week["label"]}, {sel_month["year"]}</div>
  </div>
</div>""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# MAIN ROW: GAUGE  |  GROUP BREAKDOWN  |  HIGHLIGHTS
# ──────────────────────────────────────────────────────────────────────────────
mc1, mc2, mc3 = st.columns([1.5, 3, 2])

# ── Gauge ──────────────────────────────────────────────────────────────────────
with mc1:
    with st.container(border=True):
        absent_color = "#44403C" if dark else "#FEE2CC"
        fig_g = go.Figure(go.Pie(
            values=[max(total, 0.0001), max(gap, 0.0001)],
            hole=0.72, sort=False, textinfo="none", hoverinfo="none",
            marker_colors=[ORG, absent_color], showlegend=False,
        ))
        for txt, y_pos, sz, col in [
            (f"<b>{total}</b>",              0.57, 26, TX),
            (f"/ {cfg['total_quota']} cases", 0.44, 10, TX2),
            (f"<b>{pct}%</b>",               0.30, 14, ORG),
            ("WEEKLY QUOTA",                 0.16,  9, TX2),
        ]:
            fig_g.add_annotation(text=txt, x=0.5, y=y_pos, showarrow=False,
                                 font=dict(size=sz, color=col))
        fig_g.update_layout(margin=dict(t=5,b=5,l=5,r=5), height=200,
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_g, use_container_width=True, config={"displayModeBar": False})
        st.markdown(
            f'<p style="text-align:center;font-size:12px;font-weight:700;'
            f'color:{ORG};margin-top:-20px">{gap} cases to go</p>',
            unsafe_allow_html=True,
        )

# ── Group Breakdown ─────────────────────────────────────────────────────────────
with mc2:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">Batch Quota · Group Breakdown</div>',
                    unsafe_allow_html=True)
        for g in groups:
            left = max(0, g["quota"] - g["done"])
            bp   = min(100, g["done"] / g["quota"] * 100) if g["quota"] else 0
            bc   = GRN if left == 0 else (ORG if g["done"] / max(g["quota"],1) >= 0.6 else RED)
            lbl  = "✓ done" if left == 0 else f"{left} left"
            st.markdown(f"""
            <div style="margin-bottom:9px">
              <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">
                <span style="color:{TX}">{g['label']}</span>
                <span style="color:{TX2}">{g['done']}/{g['quota']}
                  <span style="font-weight:700;color:{bc}">{lbl}</span>
                </span>
              </div>
              <div class="pw"><div class="pf" style="width:{bp:.1f}%;background:{bc}"></div></div>
            </div>""", unsafe_allow_html=True)
        st.markdown(f"""
        <div style="margin-top:10px;padding-top:8px;border-top:1px solid {BORD};
                    display:flex;justify-content:space-between;font-size:11px;color:{TX2}">
          <span>Target Batch <b style="color:{TX}">{cfg['total_quota']} cases</b></span>
          <span>Remaining <b style="color:{ORG}">{gap} cases</b></span>
        </div>""", unsafe_allow_html=True)

# ── Key Highlights ──────────────────────────────────────────────────────────────
with mc3:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">⚡ Key Highlights</div>', unsafe_allow_html=True)
        hl = [{"c": ORG, "t": "Batch in progress",
               "s": f"{total}/{cfg['total_quota']} — {gap} cases remaining"}]
        for g in groups:
            left = max(0, g["quota"] - g["done"])
            hc   = GRN if left == 0 else (ORG if g["done"] / max(g["quota"],1) >= 0.6 else RED)
            hl.append({"c": hc, "t": g["label"],
                       "s": f"{g['done']}/{g['quota']} — "
                            f"{'All complete ✓' if left==0 else f'{left} cases left'}"})
        if invs:
            tp = round(invs[0]["total"] / total * 100) if total else 0
            hl.append({"c": ORG, "t": "Top investigator",
                       "s": f"{invs[0]['name']} · {invs[0]['total']} cases ({tp}%)"})
        for h in hl[:9]:
            st.markdown(f"""
            <div class="hl">
              <span class="hd" style="background:{h['c']}"></span>
              <div>
                <div style="font-size:11px;color:{TX2}">{h['t']}</div>
                <div style="font-size:11px;font-weight:700;color:{h['c']}">{h['s']}</div>
              </div>
            </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# INVESTIGATOR CARDS
# ──────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="font-size:10px;font-weight:700;color:{TX2};letter-spacing:.07em;
            text-transform:uppercase;margin-bottom:8px">
  👤 Investigator Quota Performance — Min {cfg['daily_min']}/day · Ideal {cfg['daily_ideal']}/day · {sel_week['label']}
  <span style="font-size:10px;font-weight:400;background:{OL};padding:2px 8px;
               border-radius:20px;border:1px dashed {OB};margin-left:8px">
    click card to expand ↓
  </span>
</div>""", unsafe_allow_html=True)

def make_inv_card_html(inv):
    """Return the static HTML for one investigator card."""
    bl, bb, bc = (("Support","#F3F4F6","#6B7280")
                  if inv["support"]
                  else badge_for(inv["total"], cfg["weekly_min"], cfg["weekly_ideal"]))
    wk_pct = min(100, inv["total"] / cfg["weekly_ideal"] * 100) if cfg["weekly_ideal"] else 0

    bars = ""
    for wd in w_days:
        n  = inv["by_day"].get(wd["ds"], 0)
        dc = dot_color(n, cfg["daily_min"], cfg["daily_ideal"])
        tc = TX if n else "#D1D5DB"
        bars += (f'<div style="flex:1;text-align:center">'
                 f'<div style="font-size:10px;font-weight:700;color:{tc};margin-bottom:3px">{"–" if not n else n}</div>'
                 f'<div style="height:24px;background:{dc};border-radius:4px"></div>'
                 f'<div style="font-size:9px;color:{TX2};margin-top:3px">{wd["day"]}</div>'
                 f'</div>')

    if inv["support"]:
        progress_html = (
            f'<div style="display:flex;justify-content:space-between;font-size:12px;'
            f'color:{TX2};margin-bottom:12px">'
            f'<span>Cases contributed</span>'
            f'<span style="font-weight:700;color:{TX}">{inv["total"]} cases</span></div>'
        )
    else:
        progress_html = (
            f'<div style="display:flex;justify-content:space-between;font-size:12px;'
            f'color:{TX2};margin-bottom:3px">'
            f'<span>Weekly total</span>'
            f'<span style="font-weight:700;color:{bc}">{inv["total"]} cases</span></div>'
            f'<div style="height:7px;background:{("#44403C" if dark else "#FEE2CC")};'
            f'border-radius:4px;margin-bottom:3px">'
            f'<div style="height:100%;width:{wk_pct:.1f}%;background:{bc};border-radius:4px"></div></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:10px;'
            f'color:{TX2};margin-bottom:12px">'
            f'<span>0</span><span>▲ min {cfg["weekly_min"]}</span>'
            f'<span style="color:{GRN}">ideal {cfg["weekly_ideal"]}</span></div>'
        )

    support_sub = (f'<div style="font-size:10px;color:{TX2}">Support role</div>'
                   if inv["support"] else "")

    legend = "".join(
        f'<span style="display:flex;align-items:center;gap:3px;font-size:10px;color:{TX2}">'
        f'<span style="width:9px;height:9px;background:{lc};border-radius:2px;'
        f'display:inline-block"></span>{ll}</span>'
        for lc, ll in [
            (GRN, f'≥{cfg["daily_ideal"]} ideal'),
            (ORG, f'{cfg["daily_min"]}–{cfg["daily_ideal"]-1} min'),
            (RED, f'1–{cfg["daily_min"]-1} low'),
            ("#FEE2CC", "0 absent"),
        ]
    )

    return f"""
    <div style="background:{CARD};border:1px solid {BORD};border-radius:14px;padding:14px 16px;margin-bottom:4px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:11px">
        <div style="width:32px;height:32px;border-radius:50%;background:{OL};border:2px solid {OB};
                    display:flex;align-items:center;justify-content:center;
                    font-weight:700;color:{ORG};font-size:13px">{inv['name'][0]}</div>
        <div>
          <div style="font-weight:700;font-size:14px;color:{TX}">{inv['name']}</div>
          {support_sub}
        </div>
        <span style="margin-left:auto;font-size:10px;font-weight:700;
                     background:{bb};color:{bc};padding:2px 8px;border-radius:20px">{bl}</span>
      </div>
      {progress_html}
      <div style="font-size:9px;color:{TX2};text-transform:uppercase;
                  letter-spacing:.07em;margin-bottom:6px">Daily Production</div>
      <div style="display:flex;gap:5px;align-items:flex-end">{bars}</div>
      <div style="margin-top:8px;display:flex;gap:7px;flex-wrap:wrap">{legend}</div>
    </div>"""

# Render cards
if not invs:
    ph_cols = st.columns(3)
    for phc in ph_cols:
        with phc:
            st.markdown(
                f'<div style="background:{CARD};border:1px solid {BORD};border-radius:14px;'
                f'padding:16px;height:130px;display:flex;align-items:center;justify-content:center">'
                f'<span style="color:{TX2};font-size:13px">Upload data to populate</span></div>',
                unsafe_allow_html=True,
            )
else:
    n_cols   = min(4, len(invs))
    inv_cols = st.columns(n_cols)
    for idx, inv in enumerate(invs):
        with inv_cols[idx % n_cols]:
            st.markdown(make_inv_card_html(inv), unsafe_allow_html=True)
            with st.expander(f"📊 {inv['name']} — detail", expanded=False):
                ex1, ex2 = st.columns(2)
                day_vals = [inv["by_day"].get(wd["ds"], 0) for wd in w_days]

                with ex1:
                    st.markdown(
                        f'<div style="font-size:10px;font-weight:700;color:{ORG};'
                        f'text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">Daily cases</div>',
                        unsafe_allow_html=True,
                    )
                    fig_d = go.Figure(go.Bar(
                        x=[wd["label"] for wd in w_days], y=day_vals,
                        marker_color=[dot_color(n, cfg["daily_min"], cfg["daily_ideal"]) for n in day_vals],
                        marker_line_width=0,
                    ))
                    fig_d.update_layout(
                        height=160, margin=dict(t=5,b=5,l=5,r=5),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        template=PLT,
                        xaxis=dict(showgrid=False),
                        yaxis=dict(showgrid=True),
                    )
                    st.plotly_chart(fig_d, use_container_width=True, config={"displayModeBar": False})

                with ex2:
                    st.markdown(
                        f'<div style="font-size:10px;font-weight:700;color:{ORG};'
                        f'text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">By country</div>',
                        unsafe_allow_html=True,
                    )
                    if not w_data.empty:
                        inv_c = (w_data[w_data["investigator"] == inv["name"]]
                                 .groupby("country").size()
                                 .sort_values().to_dict())
                        if inv_c:
                            fig_c = go.Figure(go.Bar(
                                x=list(inv_c.values()), y=list(inv_c.keys()),
                                orientation="h", marker_color=ORG, marker_line_width=0,
                            ))
                            fig_c.update_layout(
                                height=max(120, len(inv_c) * 28),
                                margin=dict(t=5,b=5,l=5,r=5),
                                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                template=PLT,
                                xaxis=dict(showgrid=True),
                                yaxis=dict(showgrid=False),
                            )
                            st.plotly_chart(fig_c, use_container_width=True,
                                            config={"displayModeBar": False})

st.markdown("<br>", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# DAILY PRODUCTION CHART
# ──────────────────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown(f'<div class="sec-lbl">Daily Case Production — {cfg["name"]}</div>',
                unsafe_allow_html=True)
    x_vals = [wd["label"] for wd in w_days]
    y_vals = [wd["total"] for wd in w_days]

    fig_line = go.Figure()
    if has_data and any(y_vals):
        fig_line.add_trace(go.Scatter(
            x=x_vals, y=y_vals, mode="lines+markers",
            line=dict(color=ORG, width=2.5),
            marker=dict(color=ORG, size=8),
            fill="tozeroy", fillcolor="rgba(249,115,22,0.12)",
        ))
    else:
        fig_line.add_trace(go.Scatter(
            x=x_vals, y=[0]*len(x_vals), mode="lines",
            line=dict(color=BORD, width=2),
        ))

    ideal_d = cfg["weekly_ideal"] / 5
    min_d   = cfg["weekly_min"]   / 5
    fig_line.add_hline(y=ideal_d, line_dash="dash", line_color=GRN,
                       annotation_text="Ideal", annotation_position="right",
                       annotation_font_color=GRN)
    fig_line.add_hline(y=min_d, line_dash="dash", line_color=RED,
                       annotation_text="Min", annotation_position="right",
                       annotation_font_color=RED)
    fig_line.update_layout(
        height=220, margin=dict(t=10,b=10,l=10,r=60),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        template=PLT, showlegend=False,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(249,115,22,0.1)"),
    )
    st.plotly_chart(fig_line, use_container_width=True, config={"displayModeBar": False})

st.markdown("<br>", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# BOTTOM CHARTS: BY COUNTRY  |  BY INVESTIGATOR
# ──────────────────────────────────────────────────────────────────────────────
bc1, bc2 = st.columns(2)

def empty_bar_msg():
    return f'<p style="color:{TX2};font-size:13px;padding:20px 0">No data for this week</p>'

with bc1:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">Cases by Country</div>', unsafe_allow_html=True)
        if by_country:
            fig_ctr = go.Figure(go.Bar(
                x=list(by_country.values()),
                y=list(by_country.keys()),
                orientation="h", marker_color=ORG, marker_line_width=0,
                text=list(by_country.values()), textposition="outside",
                textfont=dict(color=TX),
            ))
            fig_ctr.update_layout(
                height=max(220, len(by_country) * 30),
                margin=dict(t=5,b=5,l=10,r=40),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                template=PLT,
                xaxis=dict(showgrid=True, gridcolor="rgba(249,115,22,0.1)"),
                yaxis=dict(showgrid=False, autorange="reversed"),
            )
            st.plotly_chart(fig_ctr, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown(empty_bar_msg(), unsafe_allow_html=True)

with bc2:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">Cases by Investigator</div>', unsafe_allow_html=True)
        if by_inv_stat:
            fig_inv = go.Figure(go.Bar(
                x=[i["total"] for i in by_inv_stat],
                y=[i["name"]  for i in by_inv_stat],
                orientation="h", marker_color=ORG, marker_line_width=0,
                text=[f"{i['total']} ({i['pct']}%)" for i in by_inv_stat],
                textposition="outside",
                textfont=dict(color=TX),
            ))
            fig_inv.update_layout(
                height=max(220, len(by_inv_stat) * 40),
                margin=dict(t=5,b=5,l=10,r=90),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                template=PLT,
                xaxis=dict(showgrid=True, gridcolor="rgba(249,115,22,0.1)"),
                yaxis=dict(showgrid=False, autorange="reversed"),
            )
            st.plotly_chart(fig_inv, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown(empty_bar_msg(), unsafe_allow_html=True)
