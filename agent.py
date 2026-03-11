"""
CLI entry point.

Usage:
    python agent.py "2025-01-13"                  # week
    python agent.py --month "2025-01"              # month
    python agent.py --quarter "2025-Q1"            # quarter
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()

from langchain_openai import ChatOpenAI
from graph import build_pipeline
from scraper import parse_month_input, parse_quarter_input
from tools import SCRAPING_TOOLS


def run(date_input, time_frame="week"):
    llm = ChatOpenAI(model=os.getenv("LLM_MODEL", "gpt-5.4"), temperature=0)
    year = month = quarter = 0

    if time_frame == "quarter":
        year, quarter = parse_quarter_input(date_input)
        print(f"\n🤖 Pipeline: QUARTER {year}-Q{quarter}")
    elif time_frame == "month":
        year, month = parse_month_input(date_input)
        print(f"\n🤖 Pipeline: MONTH {year}-{month:02d}")
    else:
        print(f"\n🤖 Pipeline: WEEK {date_input}")
    print("═" * 70)

    pipeline = build_pipeline(llm, SCRAPING_TOOLS, time_frame, year, month, quarter)
    init = {"user_date": date_input, "time_frame": time_frame,
            "target_year": year, "target_month": month, "target_quarter": quarter}

    final = {"weeks_data": []}
    sc = 0
    for event in pipeline.stream(init, stream_mode="updates"):
        for name, out in event.items():
            if "scrape_week" in name:
                for w in (out.get("weeks_data") or []):
                    sc += 1
                    final["weeks_data"].append(w)
                    meta = w.get("post_metadata") or {}
                    print(f"  📡 [{sc}] {meta.get('title','?')[:50]} — {len(w.get('comments',[]))} comments")
            elif name == "scraper":
                final.update(out)
                final["weeks_data"].extend(out.get("weeks_data") or [])
                print(f"  📡 Scraper done")
            elif name == "group_monthly_reviews":
                final.update(out)
                for mk in sorted((out.get("monthly_reviews") or {}).keys()):
                    print(f"  📋 Monthly review: {mk}")
            elif name == "monthly_review":
                final.update(out)
                print(f"  📋 Monthly review done")
            elif name == "quarterly_review":
                final.update(out)
                print(f"  📋 Quarterly review done")
            elif name == "analysis":
                final.update(out)
                print(f"  📊 Analysis done")
        print("─" * 70)

    # Print results in order
    qr = final.get("quarterly_review", "")
    mrs = final.get("monthly_reviews") or {}
    mr = final.get("monthly_review", "")
    report = final.get("analysis_report", "(none)")

    if qr:
        print("\n" + "═" * 70)
        print("📋  QUICK QUARTER REVIEW")
        print("═" * 70)
        print(qr)

    if mrs:
        for mk in sorted(mrs.keys()):
            print("\n" + "═" * 70)
            print(f"📋  MONTHLY REVIEW — {mk}")
            print("═" * 70)
            print(mrs[mk])
    elif mr:
        print("\n" + "═" * 70)
        print("📋  MONTHLY REVIEW")
        print("═" * 70)
        print(mr)

    print("\n" + "═" * 70)
    print("📊  EXECUTIVE ANALYSIS REPORT")
    print("═" * 70)
    print(report)
    print("═" * 70)


def main():
    tf = "week"
    args = sys.argv[1:]
    if "--quarter" in args: tf = "quarter"; args.remove("--quarter")
    elif "--month" in args: tf = "month"; args.remove("--month")

    if args:
        run(" ".join(args), tf)
    else:
        print("📚 r/books Pipeline")
        t = input("Time frame [week/month/quarter]: ").strip().lower()
        if t.startswith("q"): tf = "quarter"
        elif t.startswith("m"): tf = "month"
        prompts = {"quarter": "Enter quarter (e.g. 2025-Q1): ",
                   "month": "Enter month (e.g. 2025-01): ",
                   "week": "Enter date: "}
        d = input(f"📅 {prompts[tf]}").strip()
        if d: run(d, tf)

if __name__ == "__main__":
    main()