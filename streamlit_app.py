"""
Streamlit UI for r/books Scrape & Analyse Pipeline.
Supports Week / Month / Quarter time frames.
"""
import json, os, re, sys, time, calendar
from datetime import datetime, timedelta
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import (find_weekly_thread, format_thread_output, get_monday,
                     get_mondays_in_month, get_all_mondays_in_quarter,
                     scrape_thread_comments)
from pdf_utils import markdown_to_pdf

st.set_page_config(page_title="r/books Scraper & Analyst", page_icon="📚",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Literata:opsz,wght@7..72,400;7..72,600;7..72,700&family=DM+Sans:wght@400;500;600&display=swap');
.stApp{font-family:'DM Sans',sans-serif}
.hero{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);border-radius:16px;padding:2.5rem 2rem;margin-bottom:1.5rem;position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;top:-50%;right:-20%;width:400px;height:400px;background:radial-gradient(circle,rgba(233,69,96,.15) 0%,transparent 70%);pointer-events:none}
.hero h1{font-family:'Literata',serif;color:#e9e9e9;font-size:2.4rem;margin:0 0 .3rem 0}
.hero p{color:#8899aa;font-size:1.05rem;margin:0}
.hero .accent{color:#e94560;font-weight:600}
.thread-card{background:#fafbfc;border:1px solid #e2e6ea;border-left:4px solid #e94560;border-radius:10px;padding:1.5rem;margin-bottom:1rem}
.thread-card h3{font-family:'Literata',serif;color:#1a1a2e;margin:0 0 .5rem 0;font-size:1.3rem}
.thread-meta{display:flex;gap:1.5rem;flex-wrap:wrap;color:#556677;font-size:.88rem}
.thread-meta span{display:inline-flex;align-items:center;gap:.3rem}
.comment-block{border-left:3px solid #dee2e6;padding:.75rem 0 .75rem 1rem;margin:.4rem 0;transition:border-color .2s}
.comment-block:hover{border-left-color:#e94560}
.comment-author{font-weight:600;color:#1a1a2e;font-size:.88rem}
.comment-score{color:#888;font-size:.78rem;margin-left:.5rem}
.comment-body{color:#333;font-size:.92rem;line-height:1.55;margin-top:.25rem}
.comment-depth-1{margin-left:1.5rem}.comment-depth-2{margin-left:3rem}
.comment-depth-3{margin-left:4.5rem}.comment-depth-4{margin-left:6rem}
.metric-row{display:flex;gap:.75rem;margin:1rem 0;flex-wrap:wrap}
.metric-pill{background:#f0f2f5;border-radius:20px;padding:.4rem 1rem;font-size:.85rem;color:#445566;font-weight:500}
.metric-pill strong{color:#1a1a2e}
.agent-step{background:#f7f8fa;border-radius:8px;padding:.75rem 1rem;margin:.35rem 0;font-size:.85rem;font-family:'DM Mono','Fira Code',monospace;border-left:3px solid #0f3460}
.agent-step.scraper{border-left-color:#e94560}
.agent-step.review{border-left-color:#f39c12}
.agent-step.quarter{border-left-color:#2ecc71}
.agent-step.analysis{border-left-color:#8e44ad}
section[data-testid="stSidebar"]{background:#f7f8fa}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero"><h1>📚 r/books Scraper & Analyst</h1>
<p>Scrape <span class="accent">weekly, monthly, or quarterly</span> reading threads
and get an AI-powered <span class="accent">executive report</span></p></div>
""", unsafe_allow_html=True)

# ── Sidebar ──
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    mode = st.radio("Mode", ["Direct (scrape only)", "Agent Pipeline (scrape + analyse)"], index=0)
    if mode == "Agent Pipeline (scrape + analyse)":
        st.markdown("---")
        llm_provider = st.selectbox("Provider", ["OpenAI", "Anthropic"])
        if llm_provider == "OpenAI":
            api_key = st.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
            model_name = st.selectbox("Model", ["gpt-5.4", "gpt-5-mini", "gpt-4o-mini", "gpt-4o"])
        else:
            api_key = st.text_input("Anthropic API Key", type="password", value=os.getenv("ANTHROPIC_API_KEY", ""))
            model_name = st.selectbox("Model", ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"])
    st.markdown("---")
    max_depth = st.slider("Max comment depth", 1, 15, 10)
    sort_by = st.selectbox("Sort comments", ["Score (high → low)", "Newest first", "Oldest first", "Reddit default"])

# ── Main input ──
col_tf, col_date, col_btn = st.columns([1.5, 3, 1])
with col_tf:
    time_frame = st.selectbox("Time frame", ["Week", "Month", "Quarter"])

with col_date:
    today = datetime.now().date()
    if time_frame == "Week":
        selected_date = st.date_input("Pick a date", value=today - timedelta(days=7), max_value=today)
    elif time_frame == "Month":
        mc1, mc2 = st.columns(2)
        with mc1: sel_year = st.number_input("Year", 2020, today.year, today.year)
        with mc2: sel_month = st.number_input("Month", 1, 12, max(1, today.month - 1))
    else:
        qc1, qc2 = st.columns(2)
        with qc1: sel_year = st.number_input("Year", 2020, today.year, today.year, key="qy")
        with qc2: sel_quarter = st.number_input("Quarter", 1, 4, max(1, (today.month - 1) // 3), key="qq")

with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    run_clicked = st.button("🚀 Run", type="primary", use_container_width=True)


# _______________________________________________________________________________________
# utils/helper functions

def sort_comments(comments, method): #WIP: Improve sorting options
    groups, cur = [], []
    for c in comments:
        if c["depth"] == 0:
            if cur: groups.append(cur)
            cur = [c]
        else: cur.append(c)
    if cur: groups.append(cur)
    if method == "Score (high → low)": groups.sort(key=lambda g: g[0].get("score", 0), reverse=True)
    elif method == "Newest first": groups.sort(key=lambda g: g[0].get("created_utc", 0), reverse=True)
    elif method == "Oldest first": groups.sort(key=lambda g: g[0].get("created_utc", 0))
    return [c for g in groups for c in g]

def render_comment_html(c):
    d = min(c.get("depth", 0), 4)
    dc = f"comment-depth-{d}" if d > 0 else ""
    body = c.get("body","").replace("<","&lt;").replace(">","&gt;").replace("\n\n","<br><br>").replace("\n","<br>")
    s = c.get("score", 0)
    sd = f'<span class="comment-score">({s:+d})</span>' if s else ""
    return f'<div class="comment-block {dc}"><span class="comment-author">u/{c.get("author","?")}</span>{sd}<div class="comment-body">{body}</div></div>'

def extract_book_titles(comments):
    import re
    pats = [re.compile(r'["""](.+?)["""][\s,]*(?:by|[-–—])\s+([A-Z][a-zA-Z\s.]+)', re.M),
            re.compile(r'\*\*(.+?)\*\*[\s,]*(?:by|[-–—])\s+([A-Z][a-zA-Z\s.]+)', re.M),
            re.compile(r'(?<!\*)\*([^*]+?)\*(?!\*)[\s,]*(?:by|[-–—])\s+([A-Z][a-zA-Z\s.]+)', re.M)]
    found, seen = [], set()
    for c in comments:
        if c.get("type") != "comment": continue
        for p in pats:
            for m in p.finditer(c.get("body","")):
                t, a = m.group(1).strip(), m.group(2).strip().rstrip(".,;!")
                k = f"{t.lower()} by {a.lower()}"
                if k not in seen and len(t)>2 and len(a)>2: seen.add(k); found.append(f"**{t}** by {a}")
    return found


# _______________________________________________________________________________________
# Display

def display_comments_for_week(post, comments):
    actual = [c for c in comments if c.get("type") == "comment"]
    st.markdown(f'<div class="thread-card"><h3>{post["title"]}</h3>'
        f'<div class="thread-meta"><span>👤 u/{post["author"]}</span>'
        f'<span>📅 {post["created_date"]}</span><span>⬆️ {post["score"]}</span>'
        f'<span>💬 {len(actual)} comments</span></div></div>', unsafe_allow_html=True)
    st.markdown(f'🔗 [Open on Reddit]({post["url"]})')
    books = extract_book_titles(actual)
    if books:
        with st.expander(f"📖 Book mentions ({len(books)})"): [st.markdown(f"- {b}") for b in books[:50]]

    PER_PAGE = 50
    groups, cur = [], []
    for c in comments:
        if c["depth"]==0:
            if cur: groups.append(cur)
            cur=[c]
        else: cur.append(c)
    if cur: groups.append(cur)
    tp = max(1,(len(groups)+PER_PAGE-1)//PER_PAGE)
    page = st.number_input("Page", 1, tp, 1, key=f"p_{post.get('id','x')}") if tp > 1 else 1
    s = (page-1)*PER_PAGE
    st.markdown("\n".join(render_comment_html(c) for g in groups[s:s+PER_PAGE] for c in g), unsafe_allow_html=True)

def display_review(review, title):
    st.markdown(f'<div class="thread-card"><h3>{title}</h3></div>', unsafe_allow_html=True)
    st.markdown(review)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", title)
    pdf_bytes = markdown_to_pdf(review, title=title, subtitle="r/books Reading Thread Analysis")
    st.download_button("📥 Download PDF", pdf_bytes, f"{safe_name}.pdf", "application/pdf", use_container_width=True)

def display_analysis(report, label=""):
    st.markdown(f'<div class="thread-card"><h3>📊 Executive Analysis{" — "+label if label else ""}</h3></div>', unsafe_allow_html=True)
    st.markdown(report)
    title = f"Executive Analysis — {label}" if label else "Executive Analysis"
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", f"analysis_{label or 'report'}")
    pdf_bytes = markdown_to_pdf(report, title=title, subtitle="r/books Reading Thread Analysis")
    st.download_button("📥 Download PDF", pdf_bytes, f"{safe_name}.pdf", "application/pdf", use_container_width=True)


# _______________________________________________________________________________________
# quick mode, no agents, only scraping comments, no analysis

def _scrape_mondays(mondays, label):
    st.info(f"📅 {label} — {len(mondays)} weeks to scrape")
    progress = st.progress(0)
    weeks = []
    for i, monday in enumerate(mondays):
        progress.progress(int((i/len(mondays))*100), f"Week {i+1}/{len(mondays)}…")
        post = find_weekly_thread(monday)
        if not post: continue
        comments = scrape_thread_comments(post["id"], max_depth=max_depth, expand_more=True)
        weeks.append({"post": post, "comments": sort_comments(comments, sort_by)})
    progress.progress(100, "Done!"); time.sleep(.3); progress.empty()
    return weeks

def run_direct(tf):
    if tf == "week":
        monday = get_monday(selected_date.strftime("%Y-%m-%d"))
        weeks = _scrape_mondays([monday], monday.strftime("%A, %B %d, %Y"))
    elif tf == "month":
        weeks = _scrape_mondays(get_mondays_in_month(sel_year, sel_month), f"{sel_year}-{sel_month:02d}")
    else:
        weeks = _scrape_mondays(get_all_mondays_in_quarter(sel_year, sel_quarter), f"{sel_year}-Q{sel_quarter}")

    st.session_state.update(last_weeks=weeks, last_review="", last_report="",
                            last_monthly_reviews={}, last_quarterly_review="", last_tf=tf)
    for w in weeks:
        with st.expander(f"Week of {w['post']['created_date'][:10]} ({len(w['comments'])} comments)"):
            display_comments_for_week(w["post"], w["comments"])


# _______________________________________________________________________________________
# full agent pipeline with analysis

def run_pipeline_agent(tf):
    if not api_key: st.error("⚠️ Enter API key."); return
    try:
        if llm_provider == "OpenAI":
            os.environ["OPENAI_API_KEY"] = api_key
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=model_name, temperature=0)
        else:
            os.environ["ANTHROPIC_API_KEY"] = api_key
            from langchain_anthropic import ChatAnthropic
            llm = ChatAnthropic(model=model_name, temperature=0, anthropic_api_key=api_key)
        from graph import build_pipeline
        from tools import SCRAPING_TOOLS
    except ImportError as e:
        st.error(f"❌ Missing: `{e.name}`"); return

    year = month = quarter = 0
    if tf == "quarter":
        year, quarter = sel_year, sel_quarter
        date_str = f"{year}-Q{quarter}"
        from scraper import get_all_mondays_in_quarter as gaq
        total_weeks = len(gaq(year, quarter))
    elif tf == "month":
        year, month = sel_year, sel_month
        date_str = f"{year}-{month:02d}"
        total_weeks = len(get_mondays_in_month(year, month))
    else:
        date_str = selected_date.strftime("%Y-%m-%d")
        total_weeks = 1

    pipeline = build_pipeline(llm, SCRAPING_TOOLS, tf, year, month, quarter)
    init = {"user_date": date_str, "time_frame": tf,
            "target_year": year, "target_month": month, "target_quarter": quarter}

    log = st.expander("🤖 Pipeline Log", expanded=True)
    progress = st.progress(0, "Starting…")
    final = {"weeks_data": []}
    sc = 0
    total_nodes = total_weeks + (3 if tf == "quarter" else 2 if tf == "month" else 1)

    with log:
        for event in pipeline.stream(init, stream_mode="updates"):
            for name, out in event.items():
                pct = min(95, int((sc + 1) / total_nodes * 95))

                if "scrape_week" in name:
                    for w in (out.get("weeks_data") or []):
                        sc += 1; final["weeks_data"].append(w)
                        meta = w.get("post_metadata") or {}
                        progress.progress(pct, f"Scraped {sc}/{total_weeks}…")
                        st.markdown(f'<div class="agent-step scraper"><strong>📡 [{sc}]</strong> {meta.get("title","?")[:50]} — {len(w.get("comments",[]))} comments</div>', unsafe_allow_html=True)

                elif name == "scraper":
                    final.update(out); final["weeks_data"].extend(out.get("weeks_data") or [])
                    st.markdown(f'<div class="agent-step scraper"><strong>📡 Scraper</strong> done</div>', unsafe_allow_html=True)

                elif name == "group_monthly_reviews":
                    final.update(out)
                    mrs = out.get("monthly_reviews") or {}
                    for mk in sorted(mrs.keys()):
                        st.markdown(f'<div class="agent-step review"><strong>📋 Monthly Review — {mk}</strong></div>', unsafe_allow_html=True)
                    progress.progress(pct, "Monthly reviews done…")

                elif name == "monthly_review":
                    final.update(out)
                    st.markdown('<div class="agent-step review"><strong>📋 Monthly Review</strong> done</div>', unsafe_allow_html=True)

                elif name == "quarterly_review":
                    final.update(out)
                    st.markdown('<div class="agent-step quarter"><strong>📋 Quarterly Review</strong> done</div>', unsafe_allow_html=True)
                    progress.progress(pct, "Quarterly review done…")

                elif name == "analysis":
                    final.update(out)
                    st.markdown('<div class="agent-step analysis"><strong>📊 Analysis</strong> complete</div>', unsafe_allow_html=True)
                    progress.progress(95, "Done!")

    progress.progress(100); time.sleep(.3); progress.empty()

    # Store
    weeks_display = [{"post": w["post_metadata"], "comments": sort_comments(w["comments"], sort_by)}
                     for w in final.get("weeks_data", []) if w.get("post_metadata") and w.get("comments")]

    st.session_state.update(
        last_weeks=weeks_display,
        last_review=final.get("monthly_review", ""),
        last_monthly_reviews=final.get("monthly_reviews") or {},
        last_quarterly_review=final.get("quarterly_review", ""),
        last_report=final.get("analysis_report", ""),
        last_tf=tf,
        last_year=year, last_month=month, last_quarter=quarter if tf == "quarter" else 0,
    )
    display_full_results()


# _______________________________________________________________________________________
# results display helper

def display_full_results():
    weeks = st.session_state.get("last_weeks", [])
    mr = st.session_state.get("last_review", "")
    mrs = st.session_state.get("last_monthly_reviews") or {}
    qr = st.session_state.get("last_quarterly_review", "")
    report = st.session_state.get("last_report", "")
    tf = st.session_state.get("last_tf", "week")
    year = st.session_state.get("last_year", 0)
    month = st.session_state.get("last_month", 0)
    quarter = st.session_state.get("last_quarter", 0)

    if tf == "quarter" and (qr or mrs or report):
        tab_names = ["📋 Quarter Review"]
        if mrs: tab_names.append("📋 Monthly Reviews")
        tab_names += ["📊 Analysis", "💬 Comments"]
        tabs = st.tabs(tab_names)
        idx = 0

        with tabs[idx]:
            if qr: display_review(qr, f"📋 Quick Quarter Review — {year}-Q{quarter}")
            else: st.warning("No quarterly review.")
        idx += 1

        if mrs:
            with tabs[idx]:
                for mk in sorted(mrs.keys()):
                    try: mname = calendar.month_name[int(mk.split("-")[1])]
                    except: mname = mk
                    with st.expander(f"📋 {mname} {mk.split('-')[0]}", expanded=True):
                        st.markdown(mrs[mk])
            idx += 1

        with tabs[idx]:
            if report: display_analysis(report, f"{year}-Q{quarter}")
            else: st.warning("No analysis.")
        idx += 1

        with tabs[idx]:
            if weeks:
                for w in weeks:
                    with st.expander(f"Week of {w['post']['created_date'][:10]} ({len(w['comments'])} comments)"):
                        display_comments_for_week(w["post"], w["comments"])
            else: st.warning("No comments.")

    elif tf == "month" and (mr or report):
        tabs = st.tabs(["📋 Monthly Review", "📊 Analysis", "💬 Comments"])
        with tabs[0]:
            if mr: display_review(mr, f"📋 Monthly Review — {year}-{month:02d}")
            else: st.warning("No review.")
        with tabs[1]:
            if report: display_analysis(report, f"{year}-{month:02d}")
            else: st.warning("No analysis.")
        with tabs[2]:
            for w in weeks:
                with st.expander(f"Week of {w['post']['created_date'][:10]}"):
                    display_comments_for_week(w["post"], w["comments"])

    elif report:
        tabs = st.tabs(["📊 Analysis", "💬 Comments"])
        with tabs[0]:
            label = weeks[0]["post"]["created_date"][:10] if weeks else ""
            display_analysis(report, label)
        with tabs[1]:
            if weeks: display_comments_for_week(weeks[0]["post"], weeks[0]["comments"])

    elif weeks:
        for w in weeks:
            with st.expander(f"Week of {w['post']['created_date'][:10]}"):
                display_comments_for_week(w["post"], w["comments"])


# _______________________________________________________________________________________
# let's run it!

if run_clicked:
    tf = time_frame.lower()
    if mode == "Direct (scrape only)":
        # quick mode, no agents, only scraping comments, no analysis
        run_direct(tf)
    else:
        run_pipeline_agent(tf)
elif st.session_state.get("last_weeks") or st.session_state.get("last_report"):
    display_full_results()