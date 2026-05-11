import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import re, copy
from openpyxl import load_workbook

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Ruvixx · Case Investigation", page_icon="🔶",
                   layout="wide", initial_sidebar_state="collapsed")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
ORG, GRN, RED = "#F97316", "#16A34A", "#EF4444"

COUNTRY_FIX = {
    "domican republic":   "Dominican Republic",
    "dominican repbulic": "Dominican Republic",
    "belice": "Belize", "bolivar": "Bolivia", "ecuardor": "Ecuador",
}
COUNTRY_PILLS = {
    "Mexico":"MX","Colombia":"CO","Ecuador":"EC","Guatemala":"GT",
    "Dominican Republic":"DO","Costa Rica":"CR","El Salvador":"SV",
    "Panama":"PA","Honduras":"HN","Nicaragua":"NI","Belize":"BZ",
    "Argentina":"AR","Chile":"CL","Brazil":"BR","Uruguay":"UY",
    "Paraguay":"PY","Bolivia":"BO","Peru":"PE","Venezuela":"VE",
}
ALL_KNOWN_COUNTRIES = sorted(COUNTRY_PILLS.keys())
MONTH_MAP = {m: i+1 for i, m in enumerate([
    "january","february","march","april","may","june",
    "july","august","september","october","november","december",
])}
DISQ_RE = re.compile(
    r"\b(disqualif|disqualified|reject|rjected|duplicad[ao]?|repeated|"
    r"duplicate\s+of|duplicado|related|case\s+related|already\s+contacted|"
    r"entity\s+already|caso\s+relacionado|caso\s+duplicado|not\s+valid|"
    r"no\s+aplica|kasznar|kaznar|attended\s+by\s+kaz|"
    r"same\s+entity|rjected|repeated\s+case|already\s+processed)\b",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT REGION CONFIG
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_REGIONS = {
    "MCC": {
        "name": "México Central Caribe", "contact": "Tatiana Romero",
        "groups": [
            {"label": "Mexico",                   "countries": ["Mexico"],                                   "quota": 40},
            {"label": "DR, Panama, Costa Rica",   "countries": ["Costa Rica","Dominican Republic","Panama"], "quota": 40},
            {"label": "Nicaragua, GT, SV, BZ, HN","countries": ["Nicaragua","Guatemala","El Salvador","Belize","Honduras"], "quota": 40},
        ],
        "daily_min": 5, "daily_ideal": 7, "weekly_min": 26, "weekly_ideal": 35, "support": ["Luis"],
    },
    "CS": {
        "name": "Cono Sur", "contact": "Ignacio Duce",
        "groups": [
            {"label": "Argentina",          "countries": ["Argentina"],         "quota": 25},
            {"label": "Chile",              "countries": ["Chile"],             "quota": 20},
            {"label": "Ecuador, Colombia",  "countries": ["Ecuador","Colombia"],"quota": 35},
            {"label": "Peru",               "countries": ["Peru"],              "quota": 10},
            {"label": "Uruguay, Bolivia, Paraguay","countries": ["Uruguay","Bolivia","Paraguay"],"quota": 20},
        ],
        "daily_min": 5, "daily_ideal": 7, "weekly_min": 26, "weekly_ideal": 35, "support": [],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
EMPTY_DF = pd.DataFrame(columns=["date","case_id","country","investigator",
                                  "week_num","region","month_key"])
for k, v in [
    ("all_cases",        []),
    ("all_weeks",        []),
    ("current_week_idx", 0),
    ("prev_week_idx",    0),
    ("view",             "current"),   # "prev" | "current" | "full_month"
    ("file_name",        None),
    ("tab",              "MCC"),
    ("dark",             True),
    ("rcfg",             copy.deepcopy(DEFAULT_REGIONS)),
    ("_prev_dark",       None),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ─────────────────────────────────────────────────────────────────────────────
# THEME
# ─────────────────────────────────────────────────────────────────────────────
dark = st.session_state.dark
st.session_state._prev_dark = dark

BG   = "#1A1614" if dark else "#FEF9F5"
CARD = "#242120" if dark else "#FFFFFF"
BORD = "#3D3532" if dark else "#FED7AA"
TX   = "#FAFAF9" if dark else "#1C1917"
TX2  = "#A8A29E" if dark else "#78716C"
OL   = "#431407" if dark else "#FEF3EA"
OB   = "#7C2D12" if dark else "#FED7AA"
PLT  = "plotly_dark" if dark else "plotly_white"
ABSC = "#44403C" if dark else "#FEE2CC"

# ─────────────────────────────────────────────────────────────────────────────
# REGION HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def get_all_assigned():
    return {c: (rk, gi)
            for rk, rc in st.session_state.rcfg.items()
            for gi, g  in enumerate(rc["groups"])
            for c in g["countries"]}

def total_quota(rk):
    return sum(g["quota"] for g in st.session_state.rcfg[rk]["groups"])

def region_pills(rk):
    return [COUNTRY_PILLS.get(c, c[:2].upper())
            for g in st.session_state.rcfg[rk]["groups"] for c in g["countries"]]

# ─────────────────────────────────────────────────────────────────────────────
# TEXT / DATE HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def norm_country(c):
    if not c or str(c).strip() in ("","nan","None"): return ""
    t = str(c).strip()
    return COUNTRY_FIX.get(t.lower(), t)

def is_disq(qa):
    return bool(DISQ_RE.search(str(qa or "")))

def parse_date_val(val):
    if val is None: return None
    try:
        if isinstance(val, pd.Timestamp):
            return val.strftime("%Y-%m-%d") if pd.notna(val) else None
        if isinstance(val, datetime): return val.strftime("%Y-%m-%d")
        if isinstance(val, date):
            return datetime(val.year, val.month, val.day).strftime("%Y-%m-%d")
    except Exception: pass
    s = str(val).strip()
    if not s or s in ("nan","None","NaT","NaN",""): return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (2020 <= y <= 2035): return None
        mo, d = (b, a) if a > 12 else (a, b)
        if 1 <= mo <= 12 and 1 <= d <= 31: return f"{y}-{mo:02d}-{d:02d}"
    try:
        dt = pd.to_datetime(s, dayfirst=False, errors="coerce")
        if pd.notna(dt) and 2020 <= dt.year <= 2035:
            return dt.strftime("%Y-%m-%d")
    except Exception: pass
    return None

def fmt_day(ds):
    d = datetime.strptime(ds, "%Y-%m-%d")
    return f"{d.strftime('%b')} {d.day}"

def fmt_date_range(s1, s2):
    try:
        a = datetime.strptime(s1, "%Y-%m-%d")
        b = datetime.strptime(s2, "%Y-%m-%d")
        al = f"{a.strftime('%b')} {a.day}"
        bl = str(b.day) if a.month == b.month else f"{b.strftime('%b')} {b.day}"
        return f"{al}–{bl}"
    except Exception:
        return f"{s1}–{s2}"

def dot_color(n, mn, ideal):
    if not n:      return "#FEE2CC"
    if n >= ideal: return GRN
    if n >= mn:    return ORG
    return RED

def badge_for(total, wmin, wideal):
    if not total:       return "No data",    "#FEE2E2", RED
    if total >= wideal: return "Recommended","#DCFCE7", GRN
    if total >= wmin:   return "Minimum",    "#FEF9C3", "#CA8A04"
    return "Critical", "#FEE2E2", RED

# ─────────────────────────────────────────────────────────────────────────────
# XLSX PARSERS
# ─────────────────────────────────────────────────────────────────────────────
def _week_header(cell_val):
    """Return (week_num, date_range_str_or_None) from a cell like
    'Week 1' or 'Week 2\\nMay 11-15\\n'."""
    s = str(cell_val or "").strip()
    m = re.match(r"^Week\s+(\d+)(?:\s*[\r\n]+(.+?))?(?:\s*[\r\n].*)?$",
                 s, re.DOTALL)
    if m:
        return int(m.group(1)), (m.group(2).strip() if m.group(2) else None)
    return None, None

def _dates_from_range(dr_str, year):
    """Parse 'May 4-8' → ('2026-05-04','2026-05-08') or (None,None)."""
    if not dr_str: return None, None
    m = re.match(r"(\w+)\s+(\d+)-(\d+)", dr_str.strip())
    if m:
        mn = MONTH_MAP.get(m.group(1).lower())
        if mn:
            try:
                return (date(year, mn, int(m.group(2))).strftime("%Y-%m-%d"),
                        date(year, mn, int(m.group(3))).strftime("%Y-%m-%d"))
            except Exception: pass
    return None, None


def parse_summary_sheet(wb, sheet_name, month_key, year):
    """
    Parse one Summary-Month sheet.
    Layout confirmed from file:
      Col A  (idx 0): Week header ("Week N" or "Week N\\nMay 4-8")
      Col B  (idx 1): MCC region label / group name
      Col C  (idx 2): MCC quota
      Col E  (idx 4): MCC 'Generated' / 'Target Batch' label
      Col F  (idx 5): MCC generated count / target total
      Col H  (idx 7): CS region label / group name
      Col I  (idx 8): CS quota
      Col K  (idx 10): CS 'Generated' / 'Target Batch' label
      Col L  (idx 11): CS generated count / target total

    Returns list of week dicts:
      { week_num, month_key, label, date_range,
        start, end,
        mcc: { total, groups:[{label,countries,quota,generated}] },
        cs:  { total, groups:[...] } }
    """
    ws = wb[sheet_name]
    weeks = []
    cur = None
    mcc_on = mcc_done = False
    cs_on  = cs_done  = False

    for raw_row in ws.iter_rows(values_only=True):
        row = list(raw_row) + [None] * 15
        if not any(v is not None for v in row):
            continue

        # ── Week header (col A) ─────────────────────────────────────────────
        if row[0] is not None:
            wn, dr = _week_header(row[0])
            if wn is not None:
                if cur:
                    weeks.append(cur)
                s, e = _dates_from_range(dr, year)
                lbl = f"Week {wn}" + (f" · {dr.replace('-','–')}" if dr else "")
                cur = dict(
                    week_num=wn, month_key=month_key,
                    label=lbl, date_range=dr,
                    start=s, end=e,
                    mcc=dict(total=0, groups=[]),
                    cs =dict(total=0, groups=[]),
                )
                mcc_on = mcc_done = False
                cs_on  = cs_done  = False
                continue

        if cur is None:
            continue

        # ── "Meta del Batch:" starts data collection ─────────────────────────
        if str(row[1] or "").strip() == "Meta del Batch:":
            mcc_on = True
        if str(row[7] or "").strip() == "Meta del Batch:":
            cs_on = True

        # ── MCC side (cols 1-5) ──────────────────────────────────────────────
        if mcc_on and not mcc_done:
            lbl4 = str(row[4] or "").strip()
            if lbl4 == "Target Batch":
                try: cur["mcc"]["total"] = int(float(str(row[5])))
                except Exception: pass
                mcc_done = True
            elif lbl4 != "Remaining for Goal":
                name = str(row[1] or "").strip()
                if name and name != "Meta del Batch:" and row[2] is not None:
                    try:
                        quota = int(float(str(row[2])))
                        gen   = int(float(str(row[4]))) if row[4] is not None else 0
                        ctrs  = [c.strip() for c in re.split(r",\s*", name) if c.strip()]
                        cur["mcc"]["groups"].append(
                            dict(label=name, countries=ctrs, quota=quota, generated=gen))
                    except Exception:
                        pass

        # ── CS side (cols 7-11) ─────────────────────────────────────────────
        if cs_on and not cs_done:
            lbl10 = str(row[10] or "").strip()
            if lbl10 == "Target Batch":
                try: cur["cs"]["total"] = int(float(str(row[11])))
                except Exception: pass
                cs_done = True
            elif lbl10 != "Remaining for Goal":
                name = str(row[7] or "").strip()
                if name and name != "Meta del Batch:" and row[8] is not None:
                    try:
                        quota = int(float(str(row[8])))
                        gen   = int(float(str(row[10]))) if row[10] is not None else 0
                        ctrs  = [c.strip() for c in re.split(r",\s*", name) if c.strip()]
                        cur["cs"]["groups"].append(
                            dict(label=name, countries=ctrs, quota=quota, generated=gen))
                    except Exception:
                        pass

    if cur:
        weeks.append(cur)
    return weeks


def parse_data_sheet(wb, sheet_name, month_key):
    """
    Parse one data sheet (e.g. 'May').

    Column groups confirmed from file analysis:
      Header: [None, Date, CaseID, CaseName, Country, Investigator, QANotes, QA'd,
               None, Date, CaseID, ...] repeating every 8 cols offset by 9.
      Date positions: [1, 9, 17, 25, 33, 41, 49, 57]

    Groups alternate MCC / CS by index:
      group index 0 (dp=1)  → Week 1 MCC
      group index 1 (dp=9)  → Week 1 CS
      group index 2 (dp=17) → Week 2 MCC
      group index 3 (dp=25) → Week 2 CS  … etc.

    Week assignment is by column POSITION, not by date.
    Verified: group 0 = exactly 120 cases, matching Summary Week 1 MCC total.

    Returns list of case dicts:
      { date, case_id, country, investigator, week_num, region, month_key }
    """
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    header = list(rows[0])
    date_positions = [i for i, v in enumerate(header)
                      if str(v or "").strip() == "Date"]

    records = []
    seen    = set()

    for g_idx, dp in enumerate(date_positions):
        week_num = (g_idx // 2) + 1
        region   = "MCC" if g_idx % 2 == 0 else "CS"

        for raw_row in rows[1:]:
            row = list(raw_row)
            if dp >= len(row):
                continue
            try:
                # Offsets within each group: +0=Date, +1=CaseID, +2=CaseName,
                # +3=Country, +4=Investigator, +5=QANotes, +6=QA'd
                date_val    = row[dp]     if dp     < len(row) else None
                case_id_raw = row[dp+1]   if dp+1   < len(row) else None
                country_raw = row[dp+3]   if dp+3   < len(row) else None
                inv_raw     = row[dp+4]   if dp+4   < len(row) else None
                qa_notes    = row[dp+5]   if dp+5   < len(row) else None

                ds = parse_date_val(date_val)
                if not ds:
                    continue

                case_id = str(case_id_raw or "").strip().strip("\"'")
                if not case_id or case_id in ("nan","None",""):
                    continue

                country = norm_country(str(country_raw or ""))
                if not country:
                    continue

                investigator = str(inv_raw or "").strip()
                if not investigator or investigator in ("nan","None",""):
                    continue

                if is_disq(qa_notes):
                    continue

                key = f"{case_id}|{investigator}"
                if key in seen:
                    continue
                seen.add(key)

                records.append(dict(
                    date=ds, case_id=case_id,
                    country=country, investigator=investigator,
                    week_num=week_num, region=region, month_key=month_key,
                ))
            except Exception:
                continue

    return records


def load_xlsx(file_obj):
    """
    Load the uploaded workbook. Populates:
      st.session_state.all_weeks    – list of week dicts (all months, sorted)
      st.session_state.all_cases    – deduplicated case dicts
      st.session_state.current_week_idx / prev_week_idx
      st.session_state.rcfg         – updated from current week's Summary groups
    """
    try:
        wb = load_workbook(file_obj, data_only=True, read_only=True)
    except Exception as e:
        st.error(f"Could not open file: {e}")
        return False

    year        = datetime.today().year
    all_weeks   = []
    all_cases   = []
    seen_keys   = set()

    for sname in wb.sheetnames:
        slo = sname.strip().lower()

        if slo.startswith("summary"):
            # e.g. "Summary-May" → month part = "may"
            month_part = slo.split("-", 1)[1].strip() if "-" in slo else ""
            month_num  = MONTH_MAP.get(month_part)
            if month_num is None:
                continue
            month_key = f"{year}-{month_num:02d}"
            try:
                weeks = parse_summary_sheet(wb, sname, month_key, year)
                all_weeks.extend(weeks)
            except Exception as ex:
                st.warning(f"⚠ Could not parse {sname}: {ex}")
        else:
            # Plain month sheet e.g. "May", "April"
            month_num = MONTH_MAP.get(slo)
            if month_num is None:
                continue
            month_key = f"{year}-{month_num:02d}"
            try:
                cases = parse_data_sheet(wb, sname, month_key)
                for c in cases:
                    key = f"{c['case_id']}|{c['investigator']}"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_cases.append(c)
            except Exception as ex:
                st.warning(f"⚠ Could not parse {sname}: {ex}")

    wb.close()

    # Sort weeks chronologically
    all_weeks.sort(key=lambda w: (w["month_key"], w["week_num"]))

    # Fill missing date ranges (March/April have no dates in header)
    # Use min/max of actual case dates for that week group
    for w in all_weeks:
        if not w["start"] or not w["end"]:
            wk_dates = [c["date"] for c in all_cases
                        if c["month_key"] == w["month_key"]
                        and c["week_num"]  == w["week_num"]]
            if wk_dates:
                w["start"] = min(wk_dates)
                w["end"]   = max(wk_dates)
                w["label"] = (f"Week {w['week_num']} · "
                              f"{fmt_date_range(w['start'], w['end'])}")

    # Determine current week (work week containing today)
    today_str = date.today().strftime("%Y-%m-%d")
    cur_idx   = None
    for i, w in enumerate(all_weeks):
        if w.get("start") and w.get("end"):
            if w["start"] <= today_str <= w["end"]:
                cur_idx = i
                break
    if cur_idx is None:
        past = [i for i, w in enumerate(all_weeks)
                if w.get("end") and w["end"] < today_str]
        cur_idx = past[-1] if past else max(0, len(all_weeks) - 1)

    prev_idx = max(0, cur_idx - 1)

    # Update session state
    st.session_state.all_weeks        = all_weeks
    st.session_state.all_cases        = all_cases
    st.session_state.current_week_idx = cur_idx
    st.session_state.prev_week_idx    = prev_idx
    st.session_state.view             = "current"

    # Rebuild rcfg from current week's Summary so sidebar shows live data
    if all_weeks and cur_idx < len(all_weeks):
        cw = all_weeks[cur_idx]
        new_rcfg = copy.deepcopy(DEFAULT_REGIONS)
        for rk, rkey in (("MCC","mcc"),("CS","cs")):
            if cw[rkey]["groups"]:
                new_rcfg[rk]["groups"] = [
                    dict(label=g["label"], countries=g["countries"], quota=g["quota"])
                    for g in cw[rkey]["groups"]
                ]
        st.session_state.rcfg = new_rcfg

    n = len(all_cases)
    nw = len(all_weeks)
    st.toast(f"✅ {n} cases loaded across {nw} weeks", icon="📊")
    return True

# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
  .stApp{{background-color:{BG}!important}}
  .main .block-container{{padding:1rem 2rem 2rem;max-width:1440px}}
  #MainMenu,footer,header{{visibility:hidden}}
  [data-testid="stVerticalBlockBorderWrapper"]{{border:1px solid {BORD}!important;border-radius:14px!important;background:{CARD}!important}}
  .sec-lbl{{font-size:10px;font-weight:700;color:{ORG};letter-spacing:.08em;text-transform:uppercase;margin-bottom:12px}}
  .pw{{height:7px;background:{ABSC};border-radius:4px;margin:4px 0}}
  .pf{{height:100%;border-radius:4px}}
  .hl{{display:flex;align-items:flex-start;gap:8px;margin-bottom:10px}}
  .hd{{width:7px;height:7px;border-radius:50%;margin-top:4px;flex-shrink:0;display:inline-block}}
  [data-testid="stButton"] button{{transition:background .15s,border-color .15s!important}}
  [data-testid="stButton"] button[kind="primary"]{{background:{ORG}!important;color:#fff!important;border:none!important}}
  [data-testid="stButton"] button[kind="primary"]:hover{{background:#EA6C0A!important}}
  [data-testid="stButton"] button[kind="secondary"]{{background:{CARD}!important;color:{TX}!important;border:1px solid {BORD}!important}}
  [data-testid="stButton"] button[kind="secondary"]:hover{{background:{OL}!important;border-color:{ORG}!important;color:{ORG}!important}}
  [data-testid="stButton"] button:disabled{{opacity:.35!important}}
  [data-testid="stFileUploader"]{{background:{CARD}!important;border:1px dashed {BORD}!important;border-radius:8px!important}}
  hr{{border-color:{BORD};margin:6px 0}}
  p,span,label,div{{color:{TX}}}
  [data-testid="stSelectbox"]>div>div{{background:{CARD}!important;border-color:{BORD}!important;color:{TX}!important}}
  [data-baseweb="select"]>div{{background:{CARD}!important;border-color:{BORD}!important}}
  [data-baseweb="select"] span,[data-baseweb="select"] div{{color:{TX}!important}}
  [data-baseweb="select"] svg{{fill:{TX2}!important}}
  [data-baseweb="popover"]{{background:{CARD}!important;border:1px solid {BORD}!important;border-radius:8px!important;box-shadow:none!important}}
  [data-baseweb="menu"],[data-baseweb="list"]{{background:{CARD}!important}}
  [role="option"]{{background:{CARD}!important;color:{TX}!important}}
  [role="option"]:hover,[role="option"][aria-selected="true"]{{background:{OL}!important;color:{ORG}!important}}
  [data-testid="stSidebar"]{{background:{CARD}!important;border-right:1px solid {BORD}}}
  [data-testid="stSidebar"] p,[data-testid="stSidebar"] span,[data-testid="stSidebar"] label{{color:{TX}!important}}
  [data-testid="stSidebar"] [data-baseweb="select"]>div{{background:{BG}!important;border-color:{BORD}!important}}
  [data-testid="stSidebar"] input{{background:{BG}!important;color:{TX}!important;border-color:{BORD}!important}}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Country Configuration")
    st.caption("Changes apply instantly to all displayed data.")
    if st.button("↩ Reset to defaults", use_container_width=True):
        st.session_state.rcfg = copy.deepcopy(DEFAULT_REGIONS); st.rerun()
    st.markdown("---")
    assigned   = get_all_assigned()
    all_pool   = sorted(set(ALL_KNOWN_COUNTRIES) | set(assigned.keys()))
    unassigned = [c for c in all_pool if c not in assigned]
    for rk in ["MCC","CS"]:
        rc = st.session_state.rcfg[rk]
        st.markdown(f"### 🌎 {rc['name']}")
        st.caption(f"Total quota: **{total_quota(rk)}** cases")
        for gi, g in enumerate(list(rc["groups"])):
            with st.expander(f"📦 {g['label']} ({g['quota']})", expanded=False):
                nq = st.number_input("Quota", value=g["quota"], min_value=0, step=1,
                                     key=f"q_{rk}_{gi}")
                if nq != g["quota"]:
                    st.session_state.rcfg[rk]["groups"][gi]["quota"] = int(nq); st.rerun()
                nl = st.text_input("Name", value=g["label"], key=f"lbl_{rk}_{gi}")
                if nl != g["label"]:
                    st.session_state.rcfg[rk]["groups"][gi]["label"] = nl; st.rerun()
                st.markdown("**Countries:**")
                for ctr in list(g["countries"]):
                    ca, cb = st.columns([5,1]); ca.markdown(f"🌍 {ctr}")
                    if cb.button("✕", key=f"rm_{rk}_{gi}_{ctr}"):
                        st.session_state.rcfg[rk]["groups"][gi]["countries"].remove(ctr)
                        st.rerun()
                others  = [c for c,(r,_) in assigned.items() if r != rk]
                movable = sorted(set(unassigned + others))
                if movable:
                    pick = st.selectbox("Add / move", ["— select —"]+movable, key=f"add_{rk}_{gi}")
                    if pick and pick != "— select —":
                        for rk2 in st.session_state.rcfg:
                            for g2 in st.session_state.rcfg[rk2]["groups"]:
                                if pick in g2["countries"]: g2["countries"].remove(pick)
                        st.session_state.rcfg[rk]["groups"][gi]["countries"].append(pick)
                        st.rerun()
                cust = st.text_input("Add unlisted", placeholder="Country name",
                                     key=f"cust_{rk}_{gi}")
                if cust:
                    cn = cust.strip().title()
                    if cn and cn not in g["countries"]:
                        for rk2 in st.session_state.rcfg:
                            for g2 in st.session_state.rcfg[rk2]["groups"]:
                                if cn in g2["countries"]: g2["countries"].remove(cn)
                        st.session_state.rcfg[rk]["groups"][gi]["countries"].append(cn)
                        st.rerun()
                if not g["countries"]:
                    if st.button("🗑 Delete group", key=f"del_{rk}_{gi}"):
                        st.session_state.rcfg[rk]["groups"].pop(gi); st.rerun()
        with st.expander("➕ New group", expanded=False):
            nn = st.text_input("Name", placeholder="e.g. Venezuela", key=f"ng_{rk}")
            nq = st.number_input("Quota", value=5, min_value=0, key=f"ngq_{rk}")
            if st.button(f"Add to {rk}", key=f"ngb_{rk}") and nn:
                st.session_state.rcfg[rk]["groups"].append(
                    {"label":nn,"countries":[],"quota":int(nq)}); st.rerun()
        st.markdown("---")
    if unassigned:
        st.markdown("### ⚠️ Unassigned Countries")
        for c in unassigned: st.markdown(f"- {c}")

# ─────────────────────────────────────────────────────────────────────────────
# TOP BAR
# ─────────────────────────────────────────────────────────────────────────────
cfg   = st.session_state.rcfg[st.session_state.tab]
pills = region_pills(st.session_state.tab)
cl, cm, cs_, cr, ct = st.columns([1.4, 1, 1, 4.5, 0.5])

with cl:
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:8px;padding:5px 0">
      <div style="width:30px;height:30px;background:{ORG};border-radius:7px;display:flex;
                  align-items:center;justify-content:center;color:white;font-weight:800;font-size:14px">R</div>
      <div>
        <div style="font-weight:700;font-size:13px;color:{TX}">ruvixx</div>
        <div style="font-size:8px;color:{TX2};letter-spacing:.06em;text-transform:uppercase">Case Investigation</div>
      </div>
    </div>""", unsafe_allow_html=True)

with cm:
    if st.button("México CC", key="btn_mcc",
                 type="primary" if st.session_state.tab == "MCC" else "secondary",
                 use_container_width=True):
        st.session_state.tab = "MCC"; st.rerun()

with cs_:
    if st.button("Cono Sur", key="btn_cs",
                 type="primary" if st.session_state.tab == "CS" else "secondary",
                 use_container_width=True):
        st.session_state.tab = "CS"; st.rerun()

with cr:
    ph = "".join(
        f'<span style="font-size:9px;font-weight:700;background:{ORG};color:white;'
        f'border-radius:3px;padding:1px 4px;margin:0 1px">{p}</span>' for p in pills)
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:6px;background:{OL};border:1px solid {OB};
                border-radius:8px;padding:6px 10px;font-size:12px;color:#92400E;
                font-weight:500;flex-wrap:wrap">
      <span style="width:7px;height:7px;border-radius:50%;background:{ORG};
                   display:inline-block;flex-shrink:0"></span>
      {cfg["name"]} · {cfg["contact"]} &nbsp;{ph}
    </div>""", unsafe_allow_html=True)

with ct:
    if st.button("🌙" if not dark else "☀️", key="theme_btn", use_container_width=True):
        st.session_state.dark = not dark; st.rerun()

st.markdown(f'<hr style="border-color:{BORD}">', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# CONTROLS  —  FILE UPLOAD  +  VIEW SELECTOR
# ─────────────────────────────────────────────────────────────────────────────
all_weeks = st.session_state.all_weeks
cur_idx   = st.session_state.current_week_idx
prev_idx  = st.session_state.prev_week_idx
view      = st.session_state.view
has_weeks = bool(all_weeks)
has_prev  = has_weeks and (prev_idx != cur_idx)

c_up, c_pv, c_cw, c_fm, c_st = st.columns([2.5, 1.7, 1.7, 1.5, 2.1])

with c_up:
    uploaded = st.file_uploader(
        "xlsx", type=["xlsx"], label_visibility="collapsed",
        help="Upload the LATAM Internal Case Revision Excel file",
        key="xlsx_upload",
    )
    if uploaded is not None and uploaded.name != st.session_state.file_name:
        if load_xlsx(uploaded):
            st.session_state.file_name = uploaded.name
            st.rerun()
    if st.session_state.file_name:
        st.markdown(
            f'<div style="font-size:10px;color:{TX2};margin-top:2px">'
            f'📄 {st.session_state.file_name}</div>',
            unsafe_allow_html=True)

def _view_btn(col, key, label, view_id, enabled=True):
    with col:
        if st.button(label, key=key,
                     type="primary" if view == view_id else "secondary",
                     use_container_width=True, disabled=not enabled):
            st.session_state.view = view_id; st.rerun()

# Previous week button label
if has_prev and all_weeks[prev_idx].get("start"):
    pv_lbl = f"← {fmt_date_range(all_weeks[prev_idx]['start'], all_weeks[prev_idx]['end'])}"
else:
    pv_lbl = "← Prev Week"

# Current week button label
if has_weeks and all_weeks[cur_idx].get("start"):
    cw_lbl = f"★ {fmt_date_range(all_weeks[cur_idx]['start'], all_weeks[cur_idx]['end'])}"
else:
    cw_lbl = "★ Current Week"

_view_btn(c_pv, "btn_prev",  pv_lbl,       "prev",       has_prev)
_view_btn(c_cw, "btn_cur",   cw_lbl,        "current",    has_weeks)
_view_btn(c_fm, "btn_month", "📅 Full Month","full_month", has_weeks)

with c_st:
    if not has_weeks:
        st.markdown(
            f'<div style="font-size:11px;color:{ORG};padding-top:8px">'
            f'⬆️ Upload an XLSX file to begin</div>', unsafe_allow_html=True)
    else:
        df_all = pd.DataFrame(st.session_state.all_cases)
        nm = len(df_all[df_all["region"]=="MCC"]) if not df_all.empty else 0
        nc = len(df_all[df_all["region"]=="CS"])  if not df_all.empty else 0
        st.markdown(
            f'<div style="font-size:11px;color:{TX2};padding-top:4px;line-height:1.7">'
            f'<span style="color:{GRN}">● Loaded</span> · '
            f'{len(st.session_state.all_cases)} cases · {len(all_weeks)} wks<br>'
            f'MCC <b style="color:{ORG}">{nm}</b> · CS <b style="color:{ORG}">{nc}</b>'
            f'</div>', unsafe_allow_html=True)

# ── Empty state ──────────────────────────────────────────────────────────────
if not has_weeks:
    st.markdown(
        f'<div style="text-align:center;padding:80px 20px">'
        f'<div style="font-size:48px;margin-bottom:16px">📊</div>'
        f'<div style="font-size:18px;font-weight:600;color:{TX};margin-bottom:8px">'
        f'No data loaded</div>'
        f'<div style="font-size:13px;color:{TX2}">Upload the Ruvixx LATAM Internal '
        f'Case Revision Excel file above to get started.</div></div>',
        unsafe_allow_html=True)
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# COMPUTE
# ─────────────────────────────────────────────────────────────────────────────
tab           = st.session_state.tab
cfg           = st.session_state.rcfg[tab]
view          = st.session_state.view
view_is_month = (view == "full_month")

# Which week is selected as anchor
sel_idx  = prev_idx if view == "prev" else cur_idx
sel_week = all_weeks[sel_idx]

# Month context anchored on current week (not prev, not changed by view)
cur_month_key = all_weeks[cur_idx]["month_key"]
month_weeks   = [w for w in all_weeks if w["month_key"] == cur_month_key]

# ── Build DataFrame ──────────────────────────────────────────────────────────
cases_df = pd.DataFrame(st.session_state.all_cases) if st.session_state.all_cases else EMPTY_DF
has_data = not cases_df.empty

# Region-filtered pool (use the region column from column-position assignment)
r_data = cases_df[cases_df["region"] == tab].copy() if has_data else pd.DataFrame()

# Cases for the selected view
if view_is_month:
    # All cases this month for this region
    w_data = r_data[r_data["month_key"] == cur_month_key] if not r_data.empty else pd.DataFrame()
else:
    # Exact week (week_num + month_key – NOT date)
    w_data = r_data[
        (r_data["month_key"] == sel_week["month_key"]) &
        (r_data["week_num"]  == sel_week["week_num"])
    ] if not r_data.empty else pd.DataFrame()

# Month data (for "month total" on cards)
m_data = r_data[r_data["month_key"] == cur_month_key] if not r_data.empty else pd.DataFrame()

# ── Summary quota data (authoritative from xlsx) ──────────────────────────────
rkey = "mcc" if tab == "MCC" else "cs"

if view_is_month:
    tq = sum(w[rkey]["total"] for w in month_weeks)
    # Merge groups by label across all weeks of the month
    grp_map = {}
    for w in month_weeks:
        for g in w[rkey]["groups"]:
            lbl = g["label"]
            if lbl not in grp_map:
                grp_map[lbl] = dict(label=lbl, countries=g["countries"],
                                    quota=0, generated=0)
            grp_map[lbl]["quota"]     += g["quota"]
            grp_map[lbl]["generated"] += g["generated"]
    summary_groups = list(grp_map.values())
    view_label = datetime.strptime(cur_month_key, "%Y-%m").strftime("%B %Y")
else:
    tq             = sel_week[rkey]["total"]
    summary_groups = sel_week[rkey]["groups"]
    view_label     = sel_week["label"]

# Summary totals drive the headline numbers
total = sum(g["generated"] for g in summary_groups)
gap   = max(0, tq - total)
pct   = round(total / tq * 100) if tq else 0

# Group rows for breakdown panel (Summary is authoritative)
groups = [
    dict(label=g["label"], quota=g["quota"],
         eff_quota=g["quota"], done=g["generated"])
    for g in summary_groups
]

# ── Investigator stats from data sheet ───────────────────────────────────────
invs = []
if not w_data.empty:
    for inv_name, grp in sorted(w_data.groupby("investigator"),
                                key=lambda x: -len(x[1])):
        month_total = (len(m_data[m_data["investigator"] == inv_name])
                       if not m_data.empty else 0)
        invs.append(dict(
            name=inv_name, total=len(grp), month_total=month_total,
            by_day=grp.groupby("date").size().to_dict(),
            support=(inv_name in cfg.get("support", [])),
        ))

by_country = (w_data.groupby("country").size()
              .sort_values(ascending=False).to_dict()
              if not w_data.empty else {})

by_inv_stat = [dict(name=i["name"], total=i["total"],
                    pct=round(i["total"]/len(w_data)*100) if not w_data.empty else 0,
                    support=i["support"])
               for i in invs]

# ── w_days: work-day list for daily bars / chart ──────────────────────────────
_DAY = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

def _build_w_days(start_str, end_str):
    days = []
    if not start_str or not end_str: return days
    cur = datetime.strptime(start_str, "%Y-%m-%d")
    end = datetime.strptime(end_str,   "%Y-%m-%d")
    while cur <= end:
        ds = cur.strftime("%Y-%m-%d")
        n  = len(w_data[w_data["date"] == ds]) if not w_data.empty else 0
        days.append(dict(ds=ds, day=_DAY[cur.weekday()], label=fmt_day(ds), total=n))
        cur += timedelta(1)
    return days

if view_is_month:
    # All unique dates in the month that had activity
    if not w_data.empty:
        w_days = _build_w_days(w_data["date"].min(), w_data["date"].max())
    else:
        w_days = _build_w_days(sel_week.get("start"), sel_week.get("end"))
else:
    w_days = _build_w_days(sel_week.get("start"), sel_week.get("end"))

# ─────────────────────────────────────────────────────────────────────────────
# METRIC ROW
# ─────────────────────────────────────────────────────────────────────────────
period_lbl = "Monthly quota" if view_is_month else "Weekly quota"
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
    <div style="font-size:10px;color:{TX2}">{view_label}</div>
  </div>
</div>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN ROW
# ─────────────────────────────────────────────────────────────────────────────
mc1, mc2, mc3 = st.columns([1.5, 3, 2])

with mc1:
    with st.container(border=True):
        fig_g = go.Figure(go.Pie(
            values=[max(total, 0.0001), max(gap, 0.0001)],
            hole=0.72, sort=False, textinfo="none", hoverinfo="none",
            marker_colors=[ORG, ABSC], showlegend=False,
        ))
        for txt, yp, sz, col in [
            (f"<b>{total}</b>", 0.57, 26, TX),
            (f"/ {tq} cases",  0.44, 10, TX2),
            (f"<b>{pct}%</b>", 0.30, 14, ORG),
            (period_lbl.upper(), 0.16, 8, TX2),
        ]:
            fig_g.add_annotation(text=txt, x=0.5, y=yp, showarrow=False,
                                  font=dict(size=sz, color=col))
        fig_g.update_layout(margin=dict(t=5,b=5,l=5,r=5), height=200,
                             paper_bgcolor="rgba(0,0,0,0)",
                             plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_g, use_container_width=True,
                        config={"displayModeBar": False})
        st.markdown(
            f'<p style="text-align:center;font-size:12px;font-weight:700;'
            f'color:{ORG};margin-top:-20px">{gap} cases remaining</p>',
            unsafe_allow_html=True)

with mc2:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">Batch Quota · Group Breakdown</div>',
                    unsafe_allow_html=True)
        for g in groups:
            dq   = g["eff_quota"]
            left = max(0, dq - g["done"])
            bp   = min(100, g["done"] / dq * 100) if dq else 0
            bc   = GRN if left == 0 else (ORG if g["done"]/max(dq,1) >= 0.6 else RED)
            lbl  = "✓ done" if left == 0 else f"{left} left"
            st.markdown(f"""
            <div style="margin-bottom:9px">
              <div style="display:flex;justify-content:space-between;
                          font-size:12px;margin-bottom:3px">
                <span style="color:{TX}">{g['label']}</span>
                <span style="color:{TX2}">{g['done']}/{dq}
                  <span style="font-weight:700;color:{bc}">{lbl}</span></span>
              </div>
              <div class="pw"><div class="pf" style="width:{bp:.1f}%;background:{bc}">
              </div></div>
            </div>""", unsafe_allow_html=True)
        st.markdown(f"""
        <div style="margin-top:10px;padding-top:8px;border-top:1px solid {BORD};
                    display:flex;justify-content:space-between;
                    font-size:11px;color:{TX2}">
          <span>Target Batch <b style="color:{TX}">{tq}</b></span>
          <span>Remaining <b style="color:{ORG}">{gap}</b></span>
        </div>""", unsafe_allow_html=True)

with mc3:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">⚡ Key Highlights</div>',
                    unsafe_allow_html=True)
        hl = [{"c": ORG, "t": "Batch in progress",
               "s": f"{total}/{tq} — {gap} remaining"}]
        for g in groups:
            left = max(0, g["eff_quota"] - g["done"])
            hc   = GRN if left==0 else (ORG if g["done"]/max(g["eff_quota"],1) >= 0.6 else RED)
            hl.append({"c": hc, "t": g["label"],
                       "s": f"{g['done']}/{g['eff_quota']} — "
                            f"{'All complete ✓' if left==0 else f'{left} left'}"})
        if invs:
            tp = round(invs[0]["total"]/len(w_data)*100) if not w_data.empty else 0
            hl.append({"c": ORG, "t": "Top investigator",
                       "s": f"{invs[0]['name']} · {invs[0]['total']} ({tp}%)"})
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

# ─────────────────────────────────────────────────────────────────────────────
# INVESTIGATOR CARDS
# ─────────────────────────────────────────────────────────────────────────────
card_period = "Full Month" if view_is_month else sel_week["label"]
st.markdown(f"""
<div style="font-size:10px;font-weight:700;color:{TX2};letter-spacing:.07em;
            text-transform:uppercase;margin-bottom:8px">
  👤 Investigator Performance — Critical ≤4/day · Min {cfg['daily_min']}–
  {cfg['daily_ideal']-1}/day · Recommended ≥{cfg['daily_ideal']}/day ·
  {card_period}
  <span style="font-size:10px;font-weight:400;background:{OL};padding:2px 8px;
               border-radius:20px;border:1px dashed {OB};margin-left:8px">
    click card to expand ↓</span>
</div>""", unsafe_allow_html=True)

n_weeks = len(month_weeks) if view_is_month else 1
w_min   = cfg["weekly_min"]   * n_weeks
w_ideal = cfg["weekly_ideal"] * n_weeks
month_str = datetime.strptime(cur_month_key, "%Y-%m").strftime("%B %Y")


def make_card(inv):
    bl, bb, bc = (("Support","#F3F4F6","#6B7280") if inv["support"]
                  else badge_for(inv["total"], w_min, w_ideal))
    wk_pct = min(100, inv["total"] / w_ideal * 100) if w_ideal else 0
    bars   = ""
    for wd in w_days:
        n  = inv["by_day"].get(wd["ds"], 0)
        dc = dot_color(n, cfg["daily_min"], cfg["daily_ideal"])
        tc = TX if n else "#D1D5DB"
        bars += (
            f'<div style="flex:1;text-align:center;min-width:16px">'
            f'<div style="font-size:9px;font-weight:700;color:{tc};margin-bottom:2px">'
            f'{"–" if not n else n}</div>'
            f'<div style="height:22px;background:{dc};border-radius:3px"></div>'
            f'<div style="font-size:8px;color:{TX2};margin-top:2px">{wd["day"]}</div>'
            f'</div>')

    plbl  = "Month total" if view_is_month else "Week total"
    prog  = (
        f'<div style="display:flex;justify-content:space-between;font-size:12px;'
        f'color:{TX2};margin-bottom:3px"><span>{plbl}</span>'
        f'<span style="font-weight:700;color:{bc}">{inv["total"]} cases</span></div>'
        f'<div style="height:7px;background:{ABSC};border-radius:4px;margin-bottom:3px">'
        f'<div style="height:100%;width:{wk_pct:.1f}%;background:{bc};border-radius:4px">'
        f'</div></div>'
        f'<div style="display:flex;justify-content:space-between;font-size:10px;'
        f'color:{TX2};margin-bottom:6px">'
        f'<span>0</span><span>▲ min {w_min}</span>'
        f'<span style="color:{GRN}">ideal {w_ideal}</span></div>'
        + (f'<div style="font-size:11px;color:{TX2};margin-bottom:10px">'
           f'Month total: <b style="color:{ORG}">{inv["month_total"]}</b>'
           f' <span style="font-size:10px">({month_str})</span></div>'
           if not view_is_month else "")
    ) if not inv["support"] else (
        f'<div style="display:flex;justify-content:space-between;font-size:12px;'
        f'color:{TX2};margin-bottom:12px"><span>Cases contributed</span>'
        f'<span style="font-weight:700;color:{TX}">{inv["total"]}</span></div>'
    )

    sup_sub = (f'<div style="font-size:10px;color:{TX2}">Support role</div>'
               if inv["support"] else "")
    legend  = "".join(
        f'<span style="display:flex;align-items:center;gap:3px;font-size:10px;color:{TX2}">'
        f'<span style="width:9px;height:9px;background:{lc};border-radius:2px;'
        f'display:inline-block"></span>{ll}</span>'
        for lc, ll in [
            (GRN, f'≥{cfg["daily_ideal"]}'),
            (ORG, f'{cfg["daily_min"]}–{cfg["daily_ideal"]-1}'),
            (RED, f'1–{cfg["daily_min"]-1}'),
            ("#FEE2CC", "absent"),
        ])
    return f"""
    <div style="background:{CARD};border:1px solid {BORD};border-radius:14px;
                padding:14px 16px;margin-bottom:4px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:11px">
        <div style="width:32px;height:32px;border-radius:50%;background:{OL};
                    border:2px solid {OB};display:flex;align-items:center;
                    justify-content:center;font-weight:700;color:{ORG};font-size:13px">
          {inv['name'][0]}</div>
        <div><div style="font-weight:700;font-size:14px;color:{TX}">{inv['name']}</div>
          {sup_sub}</div>
        <span style="margin-left:auto;font-size:10px;font-weight:700;background:{bb};
                     color:{bc};padding:2px 8px;border-radius:20px">{bl}</span>
      </div>
      {prog}
      <div style="font-size:9px;color:{TX2};text-transform:uppercase;
                  letter-spacing:.07em;margin-bottom:6px">Daily Production</div>
      <div style="display:flex;gap:4px;align-items:flex-end;overflow:hidden">{bars}</div>
      <div style="margin-top:8px;display:flex;gap:7px;flex-wrap:wrap">{legend}</div>
    </div>"""


if not invs:
    for phc in st.columns(3):
        with phc:
            st.markdown(
                f'<div style="background:{CARD};border:1px solid {BORD};'
                f'border-radius:14px;padding:16px;height:130px;display:flex;'
                f'align-items:center;justify-content:center">'
                f'<span style="color:{TX2};font-size:13px">No cases for this period</span>'
                f'</div>', unsafe_allow_html=True)
else:
    n_cols   = min(4, len(invs))
    inv_cols = st.columns(n_cols)
    for idx, inv in enumerate(invs):
        with inv_cols[idx % n_cols]:
            st.markdown(make_card(inv), unsafe_allow_html=True)
            with st.expander(f"📊 {inv['name']} — detail", expanded=False):
                ex1, ex2 = st.columns(2)
                day_vals = [inv["by_day"].get(wd["ds"], 0) for wd in w_days]
                with ex1:
                    st.markdown(
                        f'<div style="font-size:10px;font-weight:700;color:{ORG};'
                        f'text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">'
                        f'Daily</div>', unsafe_allow_html=True)
                    fig_d = go.Figure(go.Bar(
                        x=[wd["label"] for wd in w_days], y=day_vals,
                        marker_color=[dot_color(n, cfg["daily_min"], cfg["daily_ideal"])
                                      for n in day_vals],
                        marker_line_width=0))
                    fig_d.update_layout(
                        height=150, margin=dict(t=5,b=5,l=5,r=5),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        template=PLT, xaxis=dict(showgrid=False),
                        yaxis=dict(showgrid=True))
                    st.plotly_chart(fig_d, use_container_width=True,
                                    config={"displayModeBar": False},
                                    key=f"d_{idx}_{tab}_{view}")
                with ex2:
                    st.markdown(
                        f'<div style="font-size:10px;font-weight:700;color:{ORG};'
                        f'text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">'
                        f'By country</div>', unsafe_allow_html=True)
                    if not w_data.empty:
                        ic = (w_data[w_data["investigator"]==inv["name"]]
                              .groupby("country").size().sort_values().to_dict())
                        if ic:
                            fig_c = go.Figure(go.Bar(
                                x=list(ic.values()), y=list(ic.keys()),
                                orientation="h", marker_color=ORG, marker_line_width=0))
                            fig_c.update_layout(
                                height=max(120, len(ic)*28),
                                margin=dict(t=5,b=5,l=5,r=5),
                                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                template=PLT, xaxis=dict(showgrid=True),
                                yaxis=dict(showgrid=False))
                            st.plotly_chart(fig_c, use_container_width=True,
                                            config={"displayModeBar": False},
                                            key=f"c_{idx}_{tab}_{view}")
                # Month breakdown (only in week views)
                if not view_is_month and not m_data.empty:
                    im = m_data[m_data["investigator"] == inv["name"]]
                    if not im.empty:
                        st.markdown(
                            f'<div style="font-size:10px;font-weight:700;color:{ORG};'
                            f'text-transform:uppercase;letter-spacing:.08em;margin:8px 0 6px">'
                            f'Month — {month_str}</div>', unsafe_allow_html=True)
                        mbd = im.groupby("date").size()
                        md  = sorted(mbd.index); mv = [mbd[d] for d in md]
                        fig_m = go.Figure(go.Bar(
                            x=[fmt_day(d) for d in md], y=mv,
                            marker_color=[dot_color(n, cfg["daily_min"],
                                                    cfg["daily_ideal"]) for n in mv],
                            marker_line_width=0))
                        fig_m.update_layout(
                            height=150, margin=dict(t=5,b=5,l=5,r=5),
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            template=PLT, xaxis=dict(showgrid=False, tickangle=-45),
                            yaxis=dict(showgrid=True))
                        st.plotly_chart(fig_m, use_container_width=True,
                                        config={"displayModeBar": False},
                                        key=f"m_{idx}_{tab}_{view}")

st.markdown("<br>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# DAILY PRODUCTION CHART
# ─────────────────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown(
        f'<div class="sec-lbl">Daily Case Production — {cfg["name"]} · {card_period}</div>',
        unsafe_allow_html=True)
    x_vals = [wd["label"] for wd in w_days]
    y_vals = [wd["total"] for wd in w_days]
    fig_l  = go.Figure()
    if has_data and any(y_vals):
        fig_l.add_trace(go.Scatter(
            x=x_vals, y=y_vals, mode="lines+markers",
            line=dict(color=ORG, width=2.5), marker=dict(color=ORG, size=8),
            fill="tozeroy", fillcolor="rgba(249,115,22,0.12)"))
    else:
        fig_l.add_trace(go.Scatter(
            x=x_vals, y=[0]*len(x_vals), mode="lines",
            line=dict(color=BORD, width=2)))
    fig_l.add_hline(y=cfg["daily_ideal"], line_dash="dash", line_color=GRN,
                    annotation_text="Ideal", annotation_position="right",
                    annotation_font_color=GRN)
    fig_l.add_hline(y=cfg["daily_min"],   line_dash="dash", line_color=RED,
                    annotation_text="Min",  annotation_position="right",
                    annotation_font_color=RED)
    fig_l.update_layout(
        height=220, margin=dict(t=10,b=10,l=10,r=60),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        template=PLT, showlegend=False,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(249,115,22,0.1)"))
    st.plotly_chart(fig_l, use_container_width=True, config={"displayModeBar": False})

st.markdown("<br>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# BOTTOM CHARTS
# ─────────────────────────────────────────────────────────────────────────────
def _no_data():
    return (f'<p style="color:{TX2};font-size:13px;padding:20px 0">'
            f'No cases for this period</p>')

bc1, bc2 = st.columns(2)
with bc1:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">Cases by Country</div>',
                    unsafe_allow_html=True)
        if by_country:
            fig_c = go.Figure(go.Bar(
                x=list(by_country.values()), y=list(by_country.keys()),
                orientation="h", marker_color=ORG, marker_line_width=0,
                text=list(by_country.values()), textposition="outside",
                textfont=dict(color=TX)))
            fig_c.update_layout(
                height=max(220, len(by_country)*30),
                margin=dict(t=5,b=5,l=10,r=40),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                template=PLT,
                xaxis=dict(showgrid=True, gridcolor="rgba(249,115,22,0.1)"),
                yaxis=dict(showgrid=False, autorange="reversed"))
            st.plotly_chart(fig_c, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            st.markdown(_no_data(), unsafe_allow_html=True)

with bc2:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">Cases by Investigator</div>',
                    unsafe_allow_html=True)
        if by_inv_stat:
            fig_i = go.Figure(go.Bar(
                x=[i["total"] for i in by_inv_stat],
                y=[i["name"]  for i in by_inv_stat],
                orientation="h", marker_color=ORG, marker_line_width=0,
                text=[f"{i['total']} ({i['pct']}%)" for i in by_inv_stat],
                textposition="outside", textfont=dict(color=TX)))
            fig_i.update_layout(
                height=max(220, len(by_inv_stat)*40),
                margin=dict(t=5,b=5,l=10,r=90),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                template=PLT,
                xaxis=dict(showgrid=True, gridcolor="rgba(249,115,22,0.1)"),
                yaxis=dict(showgrid=False, autorange="reversed"))
            st.plotly_chart(fig_i, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            st.markdown(_no_data(), unsafe_allow_html=True)
