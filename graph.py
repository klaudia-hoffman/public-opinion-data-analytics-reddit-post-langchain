"""
LangGraph pipelines: week / month / quarter.

WEEK:   scraper → analysis → END

MONTH:  START →Send(scrape_week)×N → monthly_review → analysis → END
        (parallel fan-out / fan-in)

QUARTER:
  START →Send(scrape_week)×N → group_monthly_reviews → quarterly_review → analysis → END
        (parallel fan-out for ALL weeks across 3 months,
         then 3 monthly reviews are generated in group_monthly_reviews,
         quarterly_review summarises the 3 monthly reviews,
         analysis gets everything)
"""

from __future__ import annotations

import calendar
import json
import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, StateGraph, START
from langgraph.types import Send
from langgraph.prebuilt import create_react_agent

from scraper import get_mondays_in_month, get_all_mondays_in_quarter, get_quarter_months


# _______________________________________________________________________________________
# State Graph

class WeekData(TypedDict, total=False):
    monday: str
    post_metadata: Optional[dict]
    comments: list[dict]
    scraper_summary: str


class PipelineState(TypedDict, total=False):
    # inputs
    user_date: str
    time_frame: str # week | month | quarter
    target_year: int
    target_month: int
    target_quarter: int

    # per-week accumulator (reducer: concatenate)
    weeks_data: Annotated[list[WeekData], operator.add]

    # single-week shorthand
    post_metadata: Optional[dict]
    comments: Optional[list[dict]]
    scraper_summary: str

    # month-level outputs
    monthly_review: str # single month mode
    monthly_reviews: dict[str, str] # quarter: {"2025-01": "...", ...}

    # quarter-level outputs
    quarterly_review: str
    quarter_label: str # e.g. "2025-Q1"

    # analysis
    analysis_report: str


# _______________________________________________________________________________________
# Prompts


SCRAPER_SYSTEM_PROMPT = """\
You are the Scraping Agent for r/books weekly reading threads.
Your ONLY job is to locate and scrape the correct thread:
1. parse_date_to_monday — convert to Monday.
2. search_reddit_thread — find the thread.
3. scrape_all_comments — scrape EVERY comment.
Respond with a short status. Do NOT analyse.
"""

MONTHLY_REVIEW_PROMPT = """\
You are the Monthly Review Agent. Write a SHORT monthly review (3–5 paragraphs)
covering: threads found, comment volume, most popular books, weekly patterns,
standout reactions. Keep it brief — in-depth analysis comes later.
"""

QUARTERLY_REVIEW_PROMPT = """\
You are the Quarterly Review Agent. You will receive 3 monthly reviews from
r/books reading threads. Write a concise "Quick Quarter Review" (3–5 paragraphs):

- Overall quarter at a glance: total volume, standout months
- Which books dominated across the quarter
- How reading trends shifted month-to-month
- Any notable new releases that generated excitement
- Biggest disappointments or controversial titles

Be concise and factual. The deep analysis follows separately.
"""

ANALYSIS_SYSTEM_PROMPT_WEEK = """\
You are the Analysis Agent — a literary market analyst.
Produce a comprehensive executive report from a single week's comments:
1. Executive Summary  2. Most Mentioned Books (ranked)
3. Positively Received  4. Negatively Received
5. Genre & Market Trends  6. Conclusions & Recommendations
Be specific, quantify, write for a publishing audience.
"""

ANALYSIS_SYSTEM_PROMPT_MONTH = """\
You are the Analysis Agent for a full month of r/books data.
Produce an executive report:
1. Executive Summary  2. Most Mentioned Books (ranked across ALL weeks)
3. Positively Received  4. Negatively Received
5. Week-over-Week Trends  6. Genre & Market Trends
7. Conclusions & Recommendations
"""

ANALYSIS_SYSTEM_PROMPT_QUARTER = """\
You are the Analysis Agent for an ENTIRE QUARTER of r/books data.

You will receive a quarterly review, 3 monthly reviews, and all comment data.
Produce a comprehensive quarterly executive report:

1. **Executive Summary** — the quarter's reading landscape at a glance.
2. **Most Mentioned Books** — ranked by total mentions across the quarter,
   with per-month breakdown and overall sentiment.
3. **Positively Received Books** — what users loved most and why.
4. **Negatively Received Books** — what users hated most, abandoned, or
   were disappointed by, with the most common criticisms.
5. **Exciting New Releases** — books users were most excited about,
   especially recent or upcoming releases generating buzz.
6. **Month-over-Month Trends** — how tastes shifted across the 3 months.
7. **Genre & Market Trends** — dominant and rising genres, market signals.
8. **Conclusions & Recommendations** — actionable takeaways for the quarter.

Be specific, quantify, compare across months, cite user observations.
"""


# _______________________________________________________________________________________
# utils/helper functions

def _extract_scraper_results(result):
    post_metadata = comments = None
    summary = ""
    for msg in result.get("messages", []):
        if msg.type == "tool":
            try:
                parsed = json.loads(msg.content)
                if isinstance(parsed, dict) and "id" in parsed and "title" in parsed:
                    post_metadata = parsed
                elif isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and "body" in parsed[0]:
                    comments = parsed
            except (json.JSONDecodeError, TypeError, IndexError):
                pass
        elif msg.type == "ai" and msg.content and isinstance(msg.content, str):
            summary = msg.content
    return post_metadata, comments, summary


def _format_week_comments_for_llm(week):
    meta = week.get("post_metadata") or {}
    comments = week.get("comments") or []
    monday = week.get("monday", "?")
    lines = [f"### Week of {monday}",
             f"Thread: {meta.get('title','?')} | Score: {meta.get('score',0)} | Comments: {len(comments)}", ""]
    for c in comments:
        if c.get("type") != "comment": continue
        body = c.get("body", "").strip()
        if body and body != "[deleted]":
            indent = "  " * c.get("depth", 0)
            lines.append(f"{indent}[u/{c.get('author','?')} | score:{c.get('score',0)}] {body}")
    return "\n".join(lines)


def _truncate(text, max_chars=120_000):
    return text[:max_chars] + "\n\n[... truncated]" if len(text) > max_chars else text


def _group_weeks_by_month(weeks):
    """Group WeekData list by month key 'YYYY-MM'. Returns sorted dict."""
    groups = {}
    for w in sorted(weeks, key=lambda x: x.get("monday", "")):
        monday = w.get("monday", "")
        month_key = monday[:7] if len(monday) >= 7 else "unknown"
        groups.setdefault(month_key, []).append(w)
    return dict(sorted(groups.items()))


def _build_monthly_review_prompt_for(month_key, weeks, llm):
    """Generate a monthly review for a specific month's weeks."""
    blocks = []
    total = 0
    for w in weeks:
        n = len(w.get("comments") or [])
        total += n
        meta = w.get("post_metadata") or {}
        blocks.append(f"- Week of {w['monday']}: \"{meta.get('title','?')}\" — {n} comments")

    prompt = f"# Monthly Data — {month_key}\n\n## Weeks\n" + "\n".join(blocks)
    prompt += f"\n\nTotal comments: {total}\n\n"

    for w in weeks:
        top = sorted([c for c in (w.get("comments") or [])
                       if c.get("depth", 0) == 0 and c.get("score", 0) >= 3],
                      key=lambda c: c.get("score", 0), reverse=True)[:20]
        if top:
            prompt += f"\n## Top comments — {w['monday']}\n"
            for c in top:
                body = c.get("body", "").strip().replace("\n", " ")[:200]
                prompt += f"[u/{c.get('author','?')} | +{c.get('score',0)}] {body}\n"

    prompt = _truncate(prompt, 50_000)
    prompt += "\n---\nWrite the monthly review."

    resp = llm.invoke([
        {"role": "system", "content": MONTHLY_REVIEW_PROMPT},
        {"role": "user", "content": prompt},
    ])
    return resp.content if hasattr(resp, "content") else str(resp)


# _______________________________________________________________________________________
# Node Builders

def _build_parallel_scraper_node(llm, tools):
    scraper_graph = create_react_agent(model=llm, tools=tools, prompt=SCRAPER_SYSTEM_PROMPT)

    def scrape_week(state: PipelineState) -> dict:
        monday_str = state.get("user_date", "")
        result = scraper_graph.invoke({
            "messages": [("user", f"Scrape the r/books weekly reading thread for: {monday_str}")]
        })
        post_metadata, comments, summary = _extract_scraper_results(result)
        return {"weeks_data": [{
            "monday": monday_str,
            "post_metadata": post_metadata,
            "comments": comments or [],
            "scraper_summary": summary,
        }]}

    return scrape_week


def _build_single_scraper_node(llm, tools):
    scraper_graph = create_react_agent(model=llm, tools=tools, prompt=SCRAPER_SYSTEM_PROMPT)

    def node(state: PipelineState) -> dict:
        user_date = state["user_date"]
        result = scraper_graph.invoke({
            "messages": [("user", f"Scrape the r/books weekly reading thread for: {user_date}")]
        })
        post_metadata, comments, summary = _extract_scraper_results(result)
        return {
            "post_metadata": post_metadata,
            "comments": comments,
            "scraper_summary": summary,
            "weeks_data": [{"monday": user_date, "post_metadata": post_metadata,
                            "comments": comments or [], "scraper_summary": summary}],
        }

    return node


def _build_monthly_review_node(llm):
    """Single-month mode: review all weeks in state."""
    def node(state: PipelineState) -> dict:
        weeks = sorted(state.get("weeks_data") or [], key=lambda w: w.get("monday", ""))
        if not weeks:
            return {"monthly_review": "No data scraped."}
        year = state.get("target_year", 0)
        month = state.get("target_month", 0)
        review = _build_monthly_review_prompt_for(f"{year}-{month:02d}", weeks, llm)
        return {"monthly_review": review}

    return node


def _build_group_monthly_reviews_node(llm):
    """Quarter mode: group weeks by month, generate 3 monthly reviews."""
    def node(state: PipelineState) -> dict:
        weeks = sorted(state.get("weeks_data") or [], key=lambda w: w.get("monday", ""))
        grouped = _group_weeks_by_month(weeks)

        reviews = {}
        for month_key, month_weeks in grouped.items():
            print(f"  📋 Generating monthly review for {month_key} ({len(month_weeks)} weeks)…")
            reviews[month_key] = _build_monthly_review_prompt_for(month_key, month_weeks, llm)

        return {"monthly_reviews": reviews}

    return node


def _build_quarterly_review_node(llm):
    """Summarise 3 monthly reviews into a quick quarter review."""
    def node(state: PipelineState) -> dict:
        monthly_reviews = state.get("monthly_reviews") or {}
        year = state.get("target_year", 0)
        quarter = state.get("target_quarter", 0)
        label = f"{year}-Q{quarter}"

        if not monthly_reviews:
            return {"quarterly_review": "No monthly reviews available.", "quarter_label": label}

        prompt = f"# Quarterly Data — {label}\n\n"
        for month_key in sorted(monthly_reviews.keys()):
            month_name = ""
            try:
                y, m = month_key.split("-")
                month_name = calendar.month_name[int(m)]
            except Exception:
                month_name = month_key
            prompt += f"## {month_name} {year} Review\n\n{monthly_reviews[month_key]}\n\n"

        prompt += "---\nNow write the Quick Quarter Review."

        resp = llm.invoke([
            {"role": "system", "content": QUARTERLY_REVIEW_PROMPT},
            {"role": "user", "content": prompt},
        ])

        return {
            "quarterly_review": resp.content if hasattr(resp, "content") else str(resp),
            "quarter_label": label,
        }

    return node


def _build_analysis_node(llm, mode: str):
    prompts = {
        "week": ANALYSIS_SYSTEM_PROMPT_WEEK,
        "month": ANALYSIS_SYSTEM_PROMPT_MONTH,
        "quarter": ANALYSIS_SYSTEM_PROMPT_QUARTER,
    }
    system_prompt = prompts.get(mode, ANALYSIS_SYSTEM_PROMPT_WEEK)

    def node(state: PipelineState) -> dict:
        weeks = sorted(state.get("weeks_data") or [], key=lambda w: w.get("monday", ""))
        all_comments = [c for w in weeks for c in (w.get("comments") or [])]

        if not all_comments:
            return {"analysis_report": "# Analysis Unavailable\n\nNo comments scraped."}

        week_texts = [_format_week_comments_for_llm(w) for w in weeks]
        full_text = _truncate("\n\n".join(week_texts))
        total = len(all_comments)
        top_level = len([c for c in all_comments if c.get("depth", 0) == 0])

        user_prompt = f"## Statistics\n- Weeks: {len(weeks)}\n- Total comments: {total}\n- Top-level: {top_level}\n\n"

        # Include monthly review(s)
        monthly_review = state.get("monthly_review", "")
        monthly_reviews = state.get("monthly_reviews") or {}
        quarterly_review = state.get("quarterly_review", "")

        if quarterly_review:
            user_prompt += f"## Quarterly Review\n\n{quarterly_review}\n\n"
        if monthly_reviews:
            for mk in sorted(monthly_reviews.keys()):
                user_prompt += f"## Monthly Review — {mk}\n\n{monthly_reviews[mk]}\n\n"
        elif monthly_review:
            user_prompt += f"## Monthly Review\n\n{monthly_review}\n\n"

        user_prompt += f"## All Comment Data\n\n{full_text}\n\n---\nProduce the full analysis report."

        resp = llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        return {"analysis_report": resp.content if hasattr(resp, "content") else str(resp)}

    return node


# _______________________________________________________________________________________
# Graph builders

def build_week_pipeline(llm, tools):
    g = StateGraph(PipelineState)
    g.add_node("scraper", _build_single_scraper_node(llm, tools))
    g.add_node("analysis", _build_analysis_node(llm, "week"))
    g.set_entry_point("scraper")
    g.add_conditional_edges("scraper", lambda s: "analysis" if s.get("comments") else END,
                            {"analysis": "analysis", END: END})
    g.add_edge("analysis", END)
    return g.compile()


def _dispatch_weeks(monday_strs, base_state_fields=None):
    """Create a dispatch function that fans out Send() for each Monday."""
    def dispatch(state: PipelineState) -> list[Send]:
        extra = base_state_fields or {}
        return [Send("scrape_week", {"user_date": m, **extra}) for m in monday_strs]
    return dispatch


def build_month_pipeline(llm, tools, year, month):
    mondays = get_mondays_in_month(year, month)
    if not mondays:
        raise ValueError(f"No Mondays in {year}-{month:02d}")
    monday_strs = [m.strftime("%Y-%m-%d") for m in mondays]

    g = StateGraph(PipelineState)
    g.add_node("scrape_week", _build_parallel_scraper_node(llm, tools))
    g.add_node("monthly_review", _build_monthly_review_node(llm))
    g.add_node("analysis", _build_analysis_node(llm, "month"))

    g.add_conditional_edges(START, _dispatch_weeks(monday_strs), ["scrape_week"])
    g.add_edge("scrape_week", "monthly_review")
    g.add_edge("monthly_review", "analysis")
    g.add_edge("analysis", END)
    return g.compile()


def build_quarter_pipeline(llm, tools, year, quarter):
    mondays = get_all_mondays_in_quarter(year, quarter)
    if not mondays:
        raise ValueError(f"No Mondays in {year}-Q{quarter}")
    monday_strs = [m.strftime("%Y-%m-%d") for m in mondays]

    g = StateGraph(PipelineState)
    g.add_node("scrape_week", _build_parallel_scraper_node(llm, tools))
    g.add_node("group_monthly_reviews", _build_group_monthly_reviews_node(llm))
    g.add_node("quarterly_review", _build_quarterly_review_node(llm))
    g.add_node("analysis", _build_analysis_node(llm, "quarter"))

    g.add_conditional_edges(START, _dispatch_weeks(monday_strs), ["scrape_week"])
    g.add_edge("scrape_week", "group_monthly_reviews")
    g.add_edge("group_monthly_reviews", "quarterly_review")
    g.add_edge("quarterly_review", "analysis")
    g.add_edge("analysis", END)
    return g.compile()


def build_pipeline(llm, tools, time_frame="week", year=0, month=0, quarter=0):
    if time_frame == "quarter":
        return build_quarter_pipeline(llm, tools, year, quarter)
    if time_frame == "month":
        return build_month_pipeline(llm, tools, year, month)
    return build_week_pipeline(llm, tools)