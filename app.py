import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import re, io, copy, unicodedata, requests

# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Ruvixx · Case Investigation", page_icon="🔶",
                   layout="wide", initial_sidebar_state="collapsed")

# ──────────────────────────────────────────────────────────────────────────────
# GITHUB CONFIG  (set in Streamlit Secrets or .streamlit/secrets.toml)
# ──────────────────────────────────────────────────────────────────────────────
GITHUB_TOKEN     = st.secrets.get("GITHUB_TOKEN", "")
GITHUB_REPO      = st.secrets.get("GITHUB_REPO", "")
GITHUB_DATA_PATH = st.secrets.get("GITHUB_DATA_PATH", "data/dashboard_data.json")

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
ORG, GRN, RED = "#F97316", "#16A34A", "#EF4444"

COUNTRY_FIX = {
    "domican republic": "Dominican Republic", "dominican repbulic": "Dominican Republic",
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
    r"\b(disqualif|reject|rjected|duplicad[ao]?|repeated|duplicate\s+of|"
    r"related|case\s+related|already\s+contacted|entity\s+already|"
    r"caso\s+relacionado|caso\s+duplicado)\b", re.IGNORECASE,
)

# ──────────────────────────────────────────────────────────────────────────────
# DEFAULT REGION CONFIG
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_REGIONS = {
    "MCC": {
        "name": "México Central Caribe", "contact": "Tatiana Romero",
        "groups": [
            {"label": "Mexico",                 "countries": ["Mexico"],                                   "quota": 25},
            {"label": "CR + Dom. Rep. + Panama", "countries": ["Costa Rica","Dominican Republic","Panama"], "quota": 25},
            {"label": "Nicaragua",               "countries": ["Nicaragua"],                                "quota": 1},
            {"label": "Guatemala",               "countries": ["Guatemala"],                                "quota": 1},
            {"label": "El Salvador",             "countries": ["El Salvador"],                              "quota": 1},
            {"label": "Honduras",                "countries": ["Honduras"],                                 "quota": 1},
            {"label": "Belize",                  "countries": ["Belize"],                                   "quota": 1},
        ],
        "daily_min": 5, "daily_ideal": 8, "weekly_min": 25, "weekly_ideal": 40, "support": ["Luis"],
    },
    "CS": {
        "name": "Cono Sur", "contact": "Ignacio Duce",
        "groups": [
            {"label": "Colombia + Ecuador", "countries": ["Colombia","Ecuador"], "quota": 30},
            {"label": "Argentina",          "countries": ["Argentina"],          "quota": 20},
            {"label": "Chile",              "countries": ["Chile"],              "quota": 25},
            {"label": "Peru",               "countries": ["Peru"],               "quota": 25},
            {"label": "Bolivia",            "countries": ["Bolivia"],            "quota": 5},
            {"label": "Paraguay",           "countries": ["Paraguay"],           "quota": 5},
            {"label": "Uruguay",            "countries": ["Uruguay"],            "quota": 5},
        ],
        "daily_min": 5, "daily_ideal": 8, "weekly_min": 25, "weekly_ideal": 40, "support": [],
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────────────────────
EMPTY_DF = pd.DataFrame(columns=["date","case_id","country","investigator","source_file"])

for k, v in [
    ("data",               EMPTY_DF),
    ("files",              []),
    ("tab",                "MCC"),
    ("dark",               False),
    ("rcfg",               copy.deepcopy(DEFAULT_REGIONS)),
    ("week_quotas",        {}),
    ("summary_file_weeks", {}),
    ("last_refresh",       None),
    ("_init_fetch",        False),
    ("_pending_fetch",     False),
    ("_wk_month_key",      None),
    ("_prev_dark",         None),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ──────────────────────────────────────────────────────────────────────────────
# THEME  (must come before any CSS or color usage)
# ──────────────────────────────────────────────────────────────────────────────
dark = st.session_state.dark

# Detect theme-only reruns so we can skip data operations
_theme_just_changed = (st.session_state._prev_dark is not None and
                       st.session_state._prev_dark != dark)
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

# ──────────────────────────────────────────────────────────────────────────────
# REGION HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def get_all_assigned():
    return {c: (rk, gi)
            for rk, rc in st.session_state.rcfg.items()
            for gi, g in enumerate(rc["groups"])
            for c in g["countries"]}

def get_region(country):
    return get_all_assigned().get(country, (None, None))[0]

def total_quota(rk):
    return sum(g["quota"] for g in st.session_state.rcfg[rk]["groups"])

def effective_quota(rk, week_start):
    t = st.session_state.week_quotas.get(week_start, {}).get(rk, {}).get("total", 0)
    return t if t > 0 else total_quota(rk)

def region_pills(rk):
    return [COUNTRY_PILLS.get(c, c[:2].upper())
            for g in st.session_state.rcfg[rk]["groups"] for c in g["countries"]]

def with_region(df):
    if df.empty:
        return df.assign(region=pd.Series(dtype=str))
    am  = get_all_assigned()
    out = df.copy()
    out["region"] = out["country"].map(lambda c: am.get(c, (None,None))[0])
    return out

# ──────────────────────────────────────────────────────────────────────────────
# TEXT / DATE HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def safe(s):
    n = unicodedata.normalize('NFKD', str(s or ""))
    return n.encode('latin-1', 'ignore').decode('latin-1')

def norm_country(c):
    if not c or str(c).strip() in ("","nan","None"): return ""
    t = str(c).strip()
    return COUNTRY_FIX.get(t.lower(), t)

def is_disq(qa):
    return bool(DISQ_RE.search(str(qa or "")))

def parse_date_val(val):
    if val is None: return None
    try:
        if isinstance(val, pd.Timestamp): return val.strftime("%Y-%m-%d") if pd.notna(val) else None
        if isinstance(val, datetime):     return val.strftime("%Y-%m-%d")
        if isinstance(val, date):         return datetime(val.year,val.month,val.day).strftime("%Y-%m-%d")
    except Exception: pass
    s = str(val).strip()
    if not s or s in ("nan","None","NaT","NaN",""): return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        a,b,y = int(m.group(1)),int(m.group(2)),int(m.group(3))
        if not (2020 <= y <= 2035): return None
        mo,d = (b,a) if a>12 else (a,b)
        if 1<=mo<=12 and 1<=d<=31: return f"{y}-{mo:02d}-{d:02d}"
    try:
        dt = pd.to_datetime(s, dayfirst=False, errors="coerce")
        if pd.notna(dt) and 2020<=dt.year<=2035: return dt.strftime("%Y-%m-%d")
    except Exception: pass
    return None

def get_weeks(year, month):
    weeks, first = [], date(year, month, 1)
    last = date(year,12,31) if month==12 else date(year,month+1,1)-timedelta(1)
    cur  = first - timedelta(first.weekday())
    while cur <= last:
        end = cur + timedelta(4)
        if end>=first and cur<=last:
            weeks.append({"start":cur.strftime("%Y-%m-%d"),"end":end.strftime("%Y-%m-%d"),
                          "label":f"{cur.strftime('%b')} {cur.day} – {end.strftime('%b')} {end.day}"})
        cur += timedelta(7)
    return weeks

def current_week_idx(weeks):
    today_str = date.today().strftime("%Y-%m-%d")
    for i,w in enumerate(weeks):
        if w["start"] <= today_str <= w["end"]: return i
    return max(0, len(weeks)-1)

def fmt_day(ds):
    d = datetime.strptime(ds, "%Y-%m-%d")
    return f"{d.strftime('%b')} {d.day}"

def dot_color(n, mn, ideal):
    if not n: return "#FEE2CC"
    if n >= ideal: return GRN
    if n >= mn: return ORG
    return RED

def badge_for(total, wmin, wideal):
    if not total:       return "No data",  "#FEE2E2", RED
    if total >= wideal: return "Ideal",     "#DCFCE7", GRN
    if total >= wmin:   return "Above min", "#FEF9C3", "#CA8A04"
    return "Below min", "#FEE2E2", RED

# ──────────────────────────────────────────────────────────────────────────────
# FILE PARSERS
# ──────────────────────────────────────────────────────────────────────────────
def parse_wide(df_raw, source_file=""):
    rows = df_raw.values.tolist()
    if len(rows) < 2: return EMPTY_DF.copy()
    headers = [str(h).strip() if h is not None and str(h)!="nan" else "" for h in rows[0]]
    date_positions = [i for i,h in enumerate(headers) if h=="Date"]
    records, seen = [], set()
    skip_disq = skip_blank = 0
    for dp in date_positions:
        for row in rows[1:]:
            try:
                ds  = parse_date_val(row[dp]   if dp   < len(row) else None)
                cid = str(row[dp+1] if dp+1<len(row) else "").strip().strip("\"'")
                ctr = norm_country(row[dp+3]   if dp+3<len(row) else "")
                inv = str(row[dp+4] if dp+4<len(row) else "").strip()
                qa  = str(row[dp+5] if dp+5<len(row) else "")
                if not ds or not cid or not ctr or not inv or inv in ("nan","None",""): skip_blank+=1; continue
                if is_disq(qa): skip_disq+=1; continue
                key = f"{cid}|{inv}"
                if key in seen: continue
                seen.add(key)
                records.append({"date":ds,"case_id":cid,"country":ctr,
                                 "investigator":inv,"source_file":source_file})
            except Exception: continue
    if not records:
        st.warning(f"⚠️ **{source_file}**: 0 valid cases. Filtered — disqualified:{skip_disq}, blank:{skip_blank}.")
        return EMPTY_DF.copy()
    return pd.DataFrame(records)

def _next_int(row, start, look=6):
    for i in range(start, min(start+look, len(row))):
        try:
            v = int(float(str(row[i]).strip()))
            if v > 0: return v
        except Exception: pass
    return None

def _week_start(week_num, year, month):
    weeks = get_weeks(year, month)
    return weeks[week_num-1]["start"] if 0<=week_num-1<len(weeks) else None

def parse_summary_csv(df_raw, filename):
    month_num = next((v for k,v in MONTH_MAP.items() if k in filename.lower()), None)
    if not month_num:
        st.warning(f"⚠️ Cannot determine month from **{filename}**.")
        return
    year = (int(st.session_state.data["date"].str[:4].mode()[0])
            if not st.session_state.data.empty else datetime.today().year)
    rows = [[str(c).strip() if c is not None and str(c) not in ("nan","None","NaT","") else ""
             for c in row] for row in df_raw.values.tolist()]
    cur_week=in_meta=None; mcc_col=cs_col=None; loaded_weeks=[]
    for row in rows:
        joined=" ".join(row).lower()
        for cell in row:
            wm=re.match(r"^week\s+(\d+)$",cell.lower().strip())
            if wm: cur_week=int(wm.group(1)); in_meta=False; mcc_col=cs_col=None; break
        if cur_week is None: continue
        if "meta del batch" in joined:
            pos=[i for i,c in enumerate(row) if "meta del batch" in c.lower()]
            mcc_col=pos[0] if pos else None; cs_col=pos[1] if len(pos)>1 else None
            in_meta=True; continue
        if not in_meta: continue
        if "remaining for goal" in joined: continue
        if "target batch" in joined:
            for ci,cell in enumerate(row):
                if "target batch" not in cell.lower(): continue
                val=_next_int(row,ci+1)
                if not val: continue
                if mcc_col is not None and cs_col is not None:
                    region="MCC" if ci<cs_col else "CS"
                else:
                    wst_=_week_start(cur_week,year,month_num)
                    region=("CS" if st.session_state.week_quotas.get(wst_,{}).get("MCC",{}).get("total",0)>0 else "MCC")
                wst=_week_start(cur_week,year,month_num)
                if wst:
                    st.session_state.week_quotas.setdefault(wst,{"MCC":{"total":0,"groups":{}},"CS":{"total":0,"groups":{}}})
                    st.session_state.week_quotas[wst][region]["total"]=val
                    st.session_state.summary_file_weeks.setdefault(filename,[])
                    if wst not in st.session_state.summary_file_weeks[filename]:
                        st.session_state.summary_file_weeks[filename].append(wst)
                    if wst not in loaded_weeks: loaded_weeks.append(wst)
            continue
        for col_idx,region in [(mcc_col,"MCC"),(cs_col,"CS")]:
            if col_idx is None or col_idx>=len(row): continue
            name=row[col_idx].strip()
            if not name or "meta del batch" in name.lower(): continue
            val=_next_int(row,col_idx+1)
            if val:
                wst=_week_start(cur_week,year,month_num)
                if wst:
                    st.session_state.week_quotas.setdefault(wst,{"MCC":{"total":0,"groups":{}},"CS":{"total":0,"groups":{}}})
                    st.session_state.week_quotas[wst][region]["groups"][name]=val

def sheet_to_df(csv_text):
    try:
        return pd.read_csv(io.StringIO(csv_text), header=None, sep=',',
                           dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()

# ──────────────────────────────────────────────────────────────────────────────
# GITHUB FETCH
# ──────────────────────────────────────────────────────────────────────────────
def fetch_from_github(show_spinner=True):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        st.error("⚠️ GITHUB_TOKEN and GITHUB_REPO not configured in Streamlit Secrets.")
        return False
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_DATA_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept": "application/vnd.github.v3.raw", "User-Agent": "Ruvixx-Dashboard"}
    try:
        if show_spinner:
            with st.spinner("Fetching data from GitHub..."):
                resp = requests.get(url, headers=headers, timeout=30)
        else:
            resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 404:
            st.error("Data file not found. Run pushToGitHub() from Apps Script first.")
            return False
        if resp.status_code == 401:
            st.error("GitHub authentication failed — check GITHUB_TOKEN.")
            return False
        resp.raise_for_status()
        payload = resp.json()
    except requests.exceptions.Timeout:
        st.error("Request timed out — try again."); return False
    except requests.exceptions.RequestException as e:
        st.error(f"Connection error: {e}"); return False
    except ValueError:
        st.error("Could not parse data file."); return False

    if payload.get("status") != "ok":
        st.error(f"Data error: {payload.get('message','Unknown')}"); return False
    sheets = payload.get("sheets", {})
    if not sheets:
        st.warning("No sheets found."); return False

    st.session_state.data               = EMPTY_DF.copy()
    st.session_state.files              = []
    st.session_state.week_quotas        = {}
    st.session_state.summary_file_weeks = {}

    for sheet_name, csv_text in sheets.items():
        if "summary" in sheet_name.lower() or not csv_text.strip(): continue
        df = sheet_to_df(csv_text)
        if df.empty: continue
        fname  = f"{sheet_name}.csv"
        parsed = parse_wide(df, source_file=fname)
        if not parsed.empty:
            combined = pd.concat([st.session_state.data, parsed], ignore_index=True)
            combined = combined.drop_duplicates(subset=["case_id","investigator"], keep="first")
            st.session_state.data = combined
            st.session_state.files.append(fname)

    for sheet_name, csv_text in sheets.items():
        if "summary" not in sheet_name.lower() or not csv_text.strip(): continue
        df = sheet_to_df(csv_text)
        if df.empty: continue
        fname = f"{sheet_name}.csv"
        parse_summary_csv(df, fname)
        st.session_state.files.append(fname)

    st.session_state.last_refresh = payload.get("timestamp", datetime.now().isoformat())
    st.toast(f"✅ {len(st.session_state.data)} cases loaded", icon="📊")
    return True

# ──────────────────────────────────────────────────────────────────────────────
# STARTUP: pending fetch (tab switch) — skipped on theme-only reruns
# ──────────────────────────────────────────────────────────────────────────────
if st.session_state._pending_fetch and not _theme_just_changed:
    st.session_state._pending_fetch  = False
    st.session_state._wk_month_key   = None
    fetch_from_github(show_spinner=False)

# First-load auto-fetch
if not st.session_state._init_fetch:
    st.session_state._init_fetch = True
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            ok = fetch_from_github(show_spinner=False)
            if ok: st.rerun()
        except Exception as e:
            st.warning(f"Auto-fetch failed: {e}. Press Refresh to retry.")

# ──────────────────────────────────────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
  .stApp {{ background-color:{BG} !important; }}
  .main .block-container {{ padding:1rem 2rem 2rem; max-width:1440px; }}
  #MainMenu,footer,header {{ visibility:hidden; }}
  [data-testid="stVerticalBlockBorderWrapper"] {{
      border:1px solid {BORD} !important; border-radius:14px !important;
      background:{CARD} !important; }}
  .sec-lbl {{ font-size:10px;font-weight:700;color:{ORG};
              letter-spacing:.08em;text-transform:uppercase;margin-bottom:12px; }}
  .pw {{ height:7px;background:{ABSC};border-radius:4px;margin:4px 0; }}
  .pf {{ height:100%;border-radius:4px; }}
  .hl {{ display:flex;align-items:flex-start;gap:8px;margin-bottom:10px; }}
  .hd {{ width:7px;height:7px;border-radius:50%;margin-top:4px;flex-shrink:0;display:inline-block; }}
  [data-testid="stButton"] button {{ transition:background .15s,border-color .15s !important; }}
  [data-testid="stButton"] button[kind="primary"] {{
      background:{ORG} !important;color:#fff !important;border:none !important; }}
  [data-testid="stButton"] button[kind="primary"]:hover {{ background:#EA6C0A !important; }}
  [data-testid="stButton"] button[kind="secondary"] {{
      background:{CARD} !important;color:{TX} !important;border:1px solid {BORD} !important; }}
  [data-testid="stButton"] button[kind="secondary"]:hover {{
      background:{OL} !important;border-color:{ORG} !important;color:{ORG} !important; }}
  hr {{ border-color:{BORD};margin:6px 0; }}
  p,span,label,div {{ color:{TX}; }}
  [data-testid="stSelectbox"] > div > div {{
      background:{CARD} !important;border-color:{BORD} !important;color:{TX} !important; }}
  [data-baseweb="select"] > div {{
      background:{CARD} !important;border-color:{BORD} !important; }}
  [data-baseweb="select"] span,[data-baseweb="select"] div {{ color:{TX} !important; }}
  [data-baseweb="select"] svg {{ fill:{TX2} !important; }}
  [data-baseweb="popover"] {{
      background:{CARD} !important;border:1px solid {BORD} !important;
      border-radius:8px !important;box-shadow:none !important; }}
  [data-baseweb="menu"],[data-baseweb="list"] {{ background:{CARD} !important; }}
  [role="option"] {{ background:{CARD} !important;color:{TX} !important; }}
  [role="option"]:hover,[role="option"][aria-selected="true"] {{
      background:{OL} !important;color:{ORG} !important; }}
  [data-testid="stSidebar"] {{
      background:{CARD} !important;border-right:1px solid {BORD}; }}
  [data-testid="stSidebar"] p,
  [data-testid="stSidebar"] span,
  [data-testid="stSidebar"] label {{ color:{TX} !important; }}
  [data-testid="stSidebar"] [data-baseweb="select"] > div {{
      background:{BG} !important;border-color:{BORD} !important; }}
  [data-testid="stSidebar"] input {{
      background:{BG} !important;color:{TX} !important;border-color:{BORD} !important; }}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR — COUNTRY CONFIG
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Country Configuration")
    st.caption("Changes apply instantly to all displayed data.")
    if st.button("↩ Reset to defaults", use_container_width=True):
        st.session_state.rcfg = copy.deepcopy(DEFAULT_REGIONS); st.rerun()
    if st.session_state.week_quotas:
        st.markdown("---")
        st.markdown("**📋 Summary Quotas**")
        for ws,reg in sorted(st.session_state.week_quotas.items()):
            st.caption(f"Wk {fmt_day(ws)}: MCC={reg.get('MCC',{}).get('total',0)} · CS={reg.get('CS',{}).get('total',0)}")
    st.markdown("---")
    assigned   = get_all_assigned()
    all_pool   = sorted(set(ALL_KNOWN_COUNTRIES)|set(assigned.keys()))
    unassigned = [c for c in all_pool if c not in assigned]
    for rk in ["MCC","CS"]:
        rc=st.session_state.rcfg[rk]
        st.markdown(f"### 🌎 {rc['name']}")
        st.caption(f"Total quota: **{total_quota(rk)}** cases")
        for gi,g in enumerate(list(rc["groups"])):
            with st.expander(f"📦 {g['label']} ({g['quota']})", expanded=False):
                nq=st.number_input("Quota",value=g["quota"],min_value=0,step=1,key=f"q_{rk}_{gi}")
                if nq!=g["quota"]: st.session_state.rcfg[rk]["groups"][gi]["quota"]=int(nq); st.rerun()
                nl=st.text_input("Name",value=g["label"],key=f"lbl_{rk}_{gi}")
                if nl!=g["label"]: st.session_state.rcfg[rk]["groups"][gi]["label"]=nl; st.rerun()
                st.markdown("**Countries:**")
                for country in list(g["countries"]):
                    ca,cb=st.columns([5,1]); ca.markdown(f"🌍 {country}")
                    if cb.button("✕",key=f"rm_{rk}_{gi}_{country}"):
                        st.session_state.rcfg[rk]["groups"][gi]["countries"].remove(country); st.rerun()
                others=[c for c,(r,_) in assigned.items() if r!=rk]
                movable=sorted(set(unassigned+others))
                if movable:
                    pick=st.selectbox("Add / move",["— select —"]+movable,key=f"add_{rk}_{gi}")
                    if pick and pick!="— select —":
                        for rk2 in st.session_state.rcfg:
                            for g2 in st.session_state.rcfg[rk2]["groups"]:
                                if pick in g2["countries"]: g2["countries"].remove(pick)
                        st.session_state.rcfg[rk]["groups"][gi]["countries"].append(pick); st.rerun()
                cust=st.text_input("Add unlisted",placeholder="Country name",key=f"cust_{rk}_{gi}")
                if cust:
                    cn=cust.strip().title()
                    if cn and cn not in g["countries"]:
                        for rk2 in st.session_state.rcfg:
                            for g2 in st.session_state.rcfg[rk2]["groups"]:
                                if cn in g2["countries"]: g2["countries"].remove(cn)
                        st.session_state.rcfg[rk]["groups"][gi]["countries"].append(cn); st.rerun()
                if not g["countries"]:
                    if st.button("🗑 Delete group",key=f"del_{rk}_{gi}"):
                        st.session_state.rcfg[rk]["groups"].pop(gi); st.rerun()
        with st.expander("➕ New group",expanded=False):
            nn=st.text_input("Name",placeholder="e.g. Venezuela",key=f"ng_{rk}")
            nq=st.number_input("Quota",value=5,min_value=0,key=f"ngq_{rk}")
            if st.button(f"Add to {rk}",key=f"ngb_{rk}") and nn:
                st.session_state.rcfg[rk]["groups"].append({"label":nn,"countries":[],"quota":int(nq)}); st.rerun()
        st.markdown("---")
    if unassigned:
        st.markdown("### ⚠️ Unassigned Countries")
        for c in unassigned: st.markdown(f"- {c}")

# ──────────────────────────────────────────────────────────────────────────────
# TOP BAR
# ──────────────────────────────────────────────────────────────────────────────
cfg   = st.session_state.rcfg[st.session_state.tab]
pills = region_pills(st.session_state.tab)
cl,cm,cs_,cr,ct = st.columns([1.4,1,1,4.5,0.5])

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
                 type="primary" if st.session_state.tab=="MCC" else "secondary",
                 use_container_width=True):
        st.session_state.tab           = "MCC"
        st.session_state._pending_fetch = True
        st.session_state._wk_month_key  = None
        st.rerun()

with cs_:
    if st.button("Cono Sur", key="btn_cs",
                 type="primary" if st.session_state.tab=="CS" else "secondary",
                 use_container_width=True):
        st.session_state.tab           = "CS"
        st.session_state._pending_fetch = True
        st.session_state._wk_month_key  = None
        st.rerun()

with cr:
    ph="".join(f'<span style="font-size:9px;font-weight:700;background:{ORG};color:white;'
               f'border-radius:3px;padding:1px 4px;margin:0 1px">{p}</span>' for p in pills)
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:6px;background:{OL};border:1px solid {OB};
                border-radius:8px;padding:6px 10px;font-size:12px;color:#92400E;font-weight:500;flex-wrap:wrap">
      <span style="width:7px;height:7px;border-radius:50%;background:{ORG};display:inline-block;flex-shrink:0"></span>
      {cfg["name"]} · {cfg["contact"]}  {ph}
    </div>""", unsafe_allow_html=True)

with ct:
    if st.button("🌙" if not dark else "☀️", key="theme_btn", use_container_width=True):
        st.session_state.dark = not dark
        st.rerun()

st.markdown(f'<hr style="border-color:{BORD}">', unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# CONTROLS
# ──────────────────────────────────────────────────────────────────────────────
raw_data  = st.session_state.data
full_data = with_region(raw_data)
has_data  = not full_data.empty

months_avail = []
if has_data:
    for ms in sorted(full_data["date"].str[:7].unique()):
        y,m = int(ms[:4]),int(ms[5:7])
        months_avail.append({"year":y,"month":m,"label":datetime(y,m,1).strftime("%B %Y")})
if not months_avail:
    t = datetime.today()
    months_avail = [{"year":t.year,"month":t.month,"label":t.strftime("%B %Y")}]

today_label  = datetime.today().strftime("%B %Y")
avail_labels = [m["label"] for m in months_avail]
default_m_idx = avail_labels.index(today_label) if today_label in avail_labels else len(months_avail)-1

c1,c2,c3,c4 = st.columns([2.2, 2.4, 1.0, 3.4])

with c1:
    sel_m_lbl = st.selectbox("Month", avail_labels, index=default_m_idx,
                              label_visibility="collapsed", key="sel_month")
    sel_month = next(m for m in months_avail if m["label"]==sel_m_lbl)

with c2:
    weeks   = get_weeks(sel_month["year"], sel_month["month"])
    w_disp  = [
        f"★ Week of {w['label']}" if w["start"] in st.session_state.week_quotas
        else f"Week of {w['label']}"
        for w in weeks
    ]
    # Reset week to current when month or tab changes (include tab in key)
    month_key = f"{sel_month['year']}-{sel_month['month']}-{st.session_state.tab}"
    if st.session_state._wk_month_key != month_key:
        st.session_state._wk_month_key = month_key
        st.session_state["sel_week"]   = w_disp[current_week_idx(weeks)]

    sel_w_disp = st.selectbox("Week", w_disp, label_visibility="collapsed", key="sel_week")
    sel_week   = weeks[w_disp.index(sel_w_disp)]

with c3:
    if st.button("🔄 Refresh", key="refresh_btn", type="secondary",
                 use_container_width=True,
                 help="Pull the latest data from GitHub"):
        ok = fetch_from_github(show_spinner=True)
        if ok:
            st.session_state._wk_month_key = None
            st.rerun()

with c4:
    if st.session_state.last_refresh:
        try:
            ts  = datetime.fromisoformat(st.session_state.last_refresh.replace("Z","+00:00"))
            ts_str = ts.strftime("%b %d, %H:%M UTC")
        except Exception:
            ts_str = str(st.session_state.last_refresh)[:16]
        n_mcc = len(full_data[full_data["region"]=="MCC"]) if has_data else 0
        n_cs  = len(full_data[full_data["region"]=="CS"])  if has_data else 0
        st.markdown(
            f'<div style="font-size:11px;color:{TX2};padding-top:6px;line-height:1.7">'
            f'<span style="color:{GRN}">● Connected to GitHub</span> &nbsp;·&nbsp; '
            f'Last push: <b>{ts_str}</b><br>'
            f'{len(raw_data)} cases &nbsp;·&nbsp; '
            f'MCC: <b style="color:{ORG}">{n_mcc}</b> &nbsp;·&nbsp; '
            f'CS: <b style="color:{ORG}">{n_cs}</b></div>', unsafe_allow_html=True)
    elif GITHUB_TOKEN and GITHUB_REPO:
        st.markdown(f'<div style="font-size:11px;color:{TX2};padding-top:8px">'
                    f'<span style="color:{ORG}">○ Not loaded</span> — press Refresh</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="font-size:11px;color:{RED};padding-top:8px">'
                    f'⚠️ GITHUB_TOKEN / GITHUB_REPO not set in Secrets</div>',
                    unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# COMPUTE
# ──────────────────────────────────────────────────────────────────────────────
cfg    = st.session_state.rcfg[st.session_state.tab]
tq     = effective_quota(st.session_state.tab, sel_week["start"])
r_data = full_data[full_data["region"]==st.session_state.tab].copy() if has_data else pd.DataFrame()
w_data = (r_data[(r_data["date"]>=sel_week["start"])&(r_data["date"]<=sel_week["end"])]
          if not r_data.empty else pd.DataFrame())
m_pfx  = f"{sel_month['year']:04d}-{sel_month['month']:02d}"
m_data = r_data[r_data["date"].str.startswith(m_pfx)] if not r_data.empty else pd.DataFrame()

total = len(w_data); gap=max(0,tq-total); pct=min(100,round(total/tq*100)) if tq else 0

groups = [{**g,"done":len(w_data[w_data["country"].isin(g["countries"])]) if not w_data.empty else 0}
          for g in cfg["groups"]]
invs = []
if not w_data.empty:
    for inv_name,grp in sorted(w_data.groupby("investigator"),key=lambda x:-len(x[1])):
        invs.append({"name":inv_name,"total":len(grp),
                     "month_total":len(m_data[m_data["investigator"]==inv_name]) if not m_data.empty else 0,
                     "by_day":grp.groupby("date").size().to_dict(),
                     "support":inv_name in cfg.get("support",[])})
w_days=[]
d_cur=datetime.strptime(sel_week["start"],"%Y-%m-%d")
d_end=datetime.strptime(sel_week["end"],  "%Y-%m-%d")
while d_cur<=d_end:
    ds=d_cur.strftime("%Y-%m-%d")
    w_days.append({"ds":ds,"label":fmt_day(ds),"day":str(d_cur.day),
                   "total":len(w_data[w_data["date"]==ds]) if not w_data.empty else 0})
    d_cur+=timedelta(1)
by_country=(w_data.groupby("country").size().sort_values(ascending=False).to_dict()
            if not w_data.empty else {})
by_inv_stat=[{"name":i["name"],"total":i["total"],
              "pct":round(i["total"]/total*100) if total else 0,"support":i["support"]}
             for i in invs]
quota_from_summary=bool(st.session_state.week_quotas.get(sel_week["start"]))

# ──────────────────────────────────────────────────────────────────────────────
# METRIC ROW
# ──────────────────────────────────────────────────────────────────────────────
src_tag=(f' <span style="font-size:9px;color:{GRN};background:#DCFCE7;'
         f'padding:1px 6px;border-radius:10px">★ summary</span>'
         if quota_from_summary else "")
st.markdown(f"""
<div style="display:flex;justify-content:flex-end;align-items:center;gap:28px;padding:8px 0 12px">
  <div style="text-align:center">
    <div style="font-size:22px;font-weight:800;color:{ORG};line-height:1">{total}</div>
    <div style="font-size:9px;color:{TX2};text-transform:uppercase;letter-spacing:.06em">Cases Generated</div>
  </div>
  <div style="text-align:center">
    <div style="font-size:22px;font-weight:800;color:{ORG};line-height:1">{gap}</div>
    <div style="font-size:9px;color:{TX2};text-transform:uppercase;letter-spacing:.06em">Quota Gap</div>
  </div>
  <div style="text-align:center">
    <div style="font-size:22px;font-weight:800;color:{ORG};line-height:1">{pct}%{src_tag}</div>
    <div style="font-size:9px;color:{TX2};text-transform:uppercase;letter-spacing:.06em">Quota Progress</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:12px;font-weight:700;color:{TX}">Trimble LATAM</div>
    <div style="font-size:10px;color:{TX2}">{sel_week["label"]}, {sel_month["year"]}</div>
  </div>
</div>""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# MAIN ROW
# ──────────────────────────────────────────────────────────────────────────────
mc1,mc2,mc3 = st.columns([1.5,3,2])
with mc1:
    with st.container(border=True):
        fig_g=go.Figure(go.Pie(values=[max(total,0.0001),max(gap,0.0001)],hole=0.72,
                               sort=False,textinfo="none",hoverinfo="none",
                               marker_colors=[ORG,ABSC],showlegend=False))
        for txt,yp,sz,col in [(f"<b>{total}</b>",0.57,26,TX),(f"/ {tq} cases",0.44,10,TX2),
                               (f"<b>{pct}%</b>",0.30,14,ORG),("WEEKLY QUOTA",0.16,9,TX2)]:
            fig_g.add_annotation(text=txt,x=0.5,y=yp,showarrow=False,font=dict(size=sz,color=col))
        fig_g.update_layout(margin=dict(t=5,b=5,l=5,r=5),height=200,
                             paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_g,use_container_width=True,config={"displayModeBar":False})
        st.markdown(f'<p style="text-align:center;font-size:12px;font-weight:700;'
                    f'color:{ORG};margin-top:-20px">{gap} cases to go</p>',unsafe_allow_html=True)

with mc2:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">Batch Quota · Group Breakdown</div>',unsafe_allow_html=True)
        sg=st.session_state.week_quotas.get(sel_week["start"],{}).get(st.session_state.tab,{}).get("groups",{})
        for g in groups:
            sq=next((v for sn,v in sg.items() if any(c.lower() in sn.lower() or sn.lower() in c.lower()
                     for c in g["countries"])),None)
            dq=sq if sq else g["quota"]; left=max(0,dq-g["done"])
            bp=min(100,g["done"]/dq*100) if dq else 0
            bc=GRN if left==0 else (ORG if g["done"]/max(dq,1)>=0.6 else RED)
            lbl="✓ done" if left==0 else f"{left} left"
            st.markdown(f"""
            <div style="margin-bottom:9px">
              <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">
                <span style="color:{TX}">{g['label']}{'<span style="font-size:9px;color:'+GRN+'"> ★</span>' if sq else ''}</span>
                <span style="color:{TX2}">{g['done']}/{dq}
                  <span style="font-weight:700;color:{bc}">{lbl}</span>
                </span>
              </div>
              <div class="pw"><div class="pf" style="width:{bp:.1f}%;background:{bc}"></div></div>
            </div>""",unsafe_allow_html=True)
        st.markdown(f"""
        <div style="margin-top:10px;padding-top:8px;border-top:1px solid {BORD};
                    display:flex;justify-content:space-between;font-size:11px;color:{TX2}">
          <span>Target Batch <b style="color:{TX}">{tq} cases</b></span>
          <span>Remaining <b style="color:{ORG}">{gap} cases</b></span>
        </div>""",unsafe_allow_html=True)

with mc3:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">⚡ Key Highlights</div>',unsafe_allow_html=True)
        hl=[{"c":ORG,"t":"Batch in progress","s":f"{total}/{tq} — {gap} cases remaining"}]
        for g in groups:
            left=max(0,g["quota"]-g["done"]); hc=GRN if left==0 else (ORG if g["done"]/max(g["quota"],1)>=0.6 else RED)
            hl.append({"c":hc,"t":g["label"],"s":f"{g['done']}/{g['quota']} — {'All complete ✓' if left==0 else f'{left} cases left'}"})
        if invs:
            tp=round(invs[0]["total"]/total*100) if total else 0
            hl.append({"c":ORG,"t":"Top investigator","s":f"{invs[0]['name']} · {invs[0]['total']} cases ({tp}%)"})
        for h in hl[:9]:
            st.markdown(f"""
            <div class="hl">
              <span class="hd" style="background:{h['c']}"></span>
              <div>
                <div style="font-size:11px;color:{TX2}">{h['t']}</div>
                <div style="font-size:11px;font-weight:700;color:{h['c']}">{h['s']}</div>
              </div>
            </div>""",unsafe_allow_html=True)

st.markdown("<br>",unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# INVESTIGATOR CARDS
# ──────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="font-size:10px;font-weight:700;color:{TX2};letter-spacing:.07em;
            text-transform:uppercase;margin-bottom:8px">
  👤 Investigator Quota Performance — Min {cfg['daily_min']}/day · Ideal {cfg['daily_ideal']}/day · {sel_week['label']}
  <span style="font-size:10px;font-weight:400;background:{OL};padding:2px 8px;
               border-radius:20px;border:1px dashed {OB};margin-left:8px">click card to expand ↓</span>
</div>""",unsafe_allow_html=True)

def make_card(inv):
    bl,bb,bc=(("Support","#F3F4F6","#6B7280") if inv["support"]
              else badge_for(inv["total"],cfg["weekly_min"],cfg["weekly_ideal"]))
    wk_pct=min(100,inv["total"]/cfg["weekly_ideal"]*100) if cfg["weekly_ideal"] else 0
    bars=""
    for wd in w_days:
        n=inv["by_day"].get(wd["ds"],0); dc,tc=dot_color(n,cfg["daily_min"],cfg["daily_ideal"]),TX if n else "#D1D5DB"
        bars+=(f'<div style="flex:1;text-align:center">'
               f'<div style="font-size:10px;font-weight:700;color:{tc};margin-bottom:3px">{"–" if not n else n}</div>'
               f'<div style="height:24px;background:{dc};border-radius:4px"></div>'
               f'<div style="font-size:9px;color:{TX2};margin-top:3px">{wd["day"]}</div></div>')
    prog=(
        f'<div style="display:flex;justify-content:space-between;font-size:12px;color:{TX2};margin-bottom:3px">'
        f'<span>Week total</span><span style="font-weight:700;color:{bc}">{inv["total"]} cases</span></div>'
        f'<div style="height:7px;background:{ABSC};border-radius:4px;margin-bottom:3px">'
        f'<div style="height:100%;width:{wk_pct:.1f}%;background:{bc};border-radius:4px"></div></div>'
        f'<div style="display:flex;justify-content:space-between;font-size:10px;color:{TX2};margin-bottom:6px">'
        f'<span>0</span><span>▲ min {cfg["weekly_min"]}</span><span style="color:{GRN}">ideal {cfg["weekly_ideal"]}</span></div>'
        f'<div style="font-size:11px;color:{TX2};margin-bottom:10px">'
        f'Month total: <b style="color:{ORG}">{inv["month_total"]} cases</b>'
        f'<span style="font-size:10px"> ({sel_month["label"]})</span></div>'
    ) if not inv["support"] else (
        f'<div style="display:flex;justify-content:space-between;font-size:12px;color:{TX2};margin-bottom:12px">'
        f'<span>Cases contributed</span><span style="font-weight:700;color:{TX}">{inv["total"]} cases</span></div>'
    )
    sup_sub=f'<div style="font-size:10px;color:{TX2}">Support role</div>' if inv["support"] else ""
    legend="".join(
        f'<span style="display:flex;align-items:center;gap:3px;font-size:10px;color:{TX2}">'
        f'<span style="width:9px;height:9px;background:{lc};border-radius:2px;display:inline-block"></span>{ll}</span>'
        for lc,ll in [(GRN,f'≥{cfg["daily_ideal"]} ideal'),(ORG,f'{cfg["daily_min"]}–{cfg["daily_ideal"]-1} min'),
                      (RED,f'1–{cfg["daily_min"]-1} low'),("#FEE2CC","0 absent")])
    return f"""
    <div style="background:{CARD};border:1px solid {BORD};border-radius:14px;padding:14px 16px;margin-bottom:4px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:11px">
        <div style="width:32px;height:32px;border-radius:50%;background:{OL};border:2px solid {OB};
                    display:flex;align-items:center;justify-content:center;font-weight:700;color:{ORG};font-size:13px">{inv['name'][0]}</div>
        <div><div style="font-weight:700;font-size:14px;color:{TX}">{inv['name']}</div>{sup_sub}</div>
        <span style="margin-left:auto;font-size:10px;font-weight:700;background:{bb};color:{bc};padding:2px 8px;border-radius:20px">{bl}</span>
      </div>
      {prog}
      <div style="font-size:9px;color:{TX2};text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">Daily Production</div>
      <div style="display:flex;gap:5px;align-items:flex-end">{bars}</div>
      <div style="margin-top:8px;display:flex;gap:7px;flex-wrap:wrap">{legend}</div>
    </div>"""

if not invs:
    ph=st.columns(3)
    for phc in ph:
        with phc:
            st.markdown(f'<div style="background:{CARD};border:1px solid {BORD};border-radius:14px;'
                        f'padding:16px;height:130px;display:flex;align-items:center;justify-content:center">'
                        f'<span style="color:{TX2};font-size:13px">Press Refresh to load data</span></div>',
                        unsafe_allow_html=True)
else:
    n_cols=min(4,len(invs)); inv_cols=st.columns(n_cols)
    for idx,inv in enumerate(invs):
        with inv_cols[idx%n_cols]:
            st.markdown(make_card(inv),unsafe_allow_html=True)
            with st.expander(f"📊 {inv['name']} — detail",expanded=False):
                ex1,ex2=st.columns(2)
                day_vals=[inv["by_day"].get(wd["ds"],0) for wd in w_days]
                with ex1:
                    st.markdown(f'<div style="font-size:10px;font-weight:700;color:{ORG};'
                                f'text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">Daily (week)</div>',
                                unsafe_allow_html=True)
                    fig_d=go.Figure(go.Bar(x=[wd["label"] for wd in w_days],y=day_vals,
                                           marker_color=[dot_color(n,cfg["daily_min"],cfg["daily_ideal"]) for n in day_vals],
                                           marker_line_width=0))
                    fig_d.update_layout(height=150,margin=dict(t=5,b=5,l=5,r=5),
                                        paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                                        template=PLT,xaxis=dict(showgrid=False),yaxis=dict(showgrid=True))
                    st.plotly_chart(fig_d,use_container_width=True,config={"displayModeBar":False})
                with ex2:
                    st.markdown(f'<div style="font-size:10px;font-weight:700;color:{ORG};'
                                f'text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">By country</div>',
                                unsafe_allow_html=True)
                    if not w_data.empty:
                        ic=(w_data[w_data["investigator"]==inv["name"]].groupby("country").size().sort_values().to_dict())
                        if ic:
                            fig_c=go.Figure(go.Bar(x=list(ic.values()),y=list(ic.keys()),
                                                   orientation="h",marker_color=ORG,marker_line_width=0))
                            fig_c.update_layout(height=max(120,len(ic)*28),margin=dict(t=5,b=5,l=5,r=5),
                                                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                                                template=PLT,xaxis=dict(showgrid=True),yaxis=dict(showgrid=False))
                            st.plotly_chart(fig_c,use_container_width=True,config={"displayModeBar":False})
                if not m_data.empty:
                    im=m_data[m_data["investigator"]==inv["name"]]
                    if not im.empty:
                        st.markdown(f'<div style="font-size:10px;font-weight:700;color:{ORG};'
                                    f'text-transform:uppercase;letter-spacing:.08em;margin:8px 0 6px">'
                                    f'Month — {sel_month["label"]}</div>',unsafe_allow_html=True)
                        mbd=im.groupby("date").size(); md=sorted(mbd.index); mv=[mbd[d] for d in md]
                        fig_m=go.Figure(go.Bar(x=[fmt_day(d) for d in md],y=mv,
                                               marker_color=[dot_color(n,cfg["daily_min"],cfg["daily_ideal"]) for n in mv],
                                               marker_line_width=0))
                        fig_m.update_layout(height=150,margin=dict(t=5,b=5,l=5,r=5),
                                            paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                                            template=PLT,xaxis=dict(showgrid=False,tickangle=-45),yaxis=dict(showgrid=True))
                        st.plotly_chart(fig_m,use_container_width=True,config={"displayModeBar":False})

st.markdown("<br>",unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# DAILY PRODUCTION CHART
# ──────────────────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown(f'<div class="sec-lbl">Daily Case Production — {cfg["name"]}</div>',unsafe_allow_html=True)
    x_vals=[wd["label"] for wd in w_days]; y_vals=[wd["total"] for wd in w_days]
    fig_line=go.Figure()
    if has_data and any(y_vals):
        fig_line.add_trace(go.Scatter(x=x_vals,y=y_vals,mode="lines+markers",
                                       line=dict(color=ORG,width=2.5),marker=dict(color=ORG,size=8),
                                       fill="tozeroy",fillcolor="rgba(249,115,22,0.12)"))
    else:
        fig_line.add_trace(go.Scatter(x=x_vals,y=[0]*len(x_vals),mode="lines",line=dict(color=BORD,width=2)))
    fig_line.add_hline(y=cfg["weekly_ideal"]/5,line_dash="dash",line_color=GRN,
                       annotation_text="Ideal",annotation_position="right",annotation_font_color=GRN)
    fig_line.add_hline(y=cfg["weekly_min"]/5,line_dash="dash",line_color=RED,
                       annotation_text="Min",annotation_position="right",annotation_font_color=RED)
    fig_line.update_layout(height=220,margin=dict(t=10,b=10,l=10,r=60),
                            paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                            template=PLT,showlegend=False,
                            xaxis=dict(showgrid=False),
                            yaxis=dict(showgrid=True,gridcolor="rgba(249,115,22,0.1)"))
    st.plotly_chart(fig_line,use_container_width=True,config={"displayModeBar":False})

st.markdown("<br>",unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# BOTTOM CHARTS
# ──────────────────────────────────────────────────────────────────────────────
def empty_msg():
    return f'<p style="color:{TX2};font-size:13px;padding:20px 0">No data for this week</p>'

bc1,bc2=st.columns(2)
with bc1:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">Cases by Country</div>',unsafe_allow_html=True)
        if by_country:
            fig_ctr=go.Figure(go.Bar(x=list(by_country.values()),y=list(by_country.keys()),
                                      orientation="h",marker_color=ORG,marker_line_width=0,
                                      text=list(by_country.values()),textposition="outside",textfont=dict(color=TX)))
            fig_ctr.update_layout(height=max(220,len(by_country)*30),margin=dict(t=5,b=5,l=10,r=40),
                                   paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",template=PLT,
                                   xaxis=dict(showgrid=True,gridcolor="rgba(249,115,22,0.1)"),
                                   yaxis=dict(showgrid=False,autorange="reversed"))
            st.plotly_chart(fig_ctr,use_container_width=True,config={"displayModeBar":False})
        else:
            st.markdown(empty_msg(),unsafe_allow_html=True)

with bc2:
    with st.container(border=True):
        st.markdown('<div class="sec-lbl">Cases by Investigator</div>',unsafe_allow_html=True)
        if by_inv_stat:
            fig_inv=go.Figure(go.Bar(x=[i["total"] for i in by_inv_stat],y=[i["name"] for i in by_inv_stat],
                                      orientation="h",marker_color=ORG,marker_line_width=0,
                                      text=[f"{i['total']} ({i['pct']}%)" for i in by_inv_stat],
                                      textposition="outside",textfont=dict(color=TX)))
            fig_inv.update_layout(height=max(220,len(by_inv_stat)*40),margin=dict(t=5,b=5,l=10,r=90),
                                   paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",template=PLT,
                                   xaxis=dict(showgrid=True,gridcolor="rgba(249,115,22,0.1)"),
                                   yaxis=dict(showgrid=False,autorange="reversed"))
            st.plotly_chart(fig_inv,use_container_width=True,config={"displayModeBar":False})
        else:
            st.markdown(empty_msg(),unsafe_allow_html=True)
