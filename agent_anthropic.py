"""CLI using Anthropic Claude. Supports --month and --quarter."""
import os, sys
from dotenv import load_dotenv
load_dotenv()
from langchain_anthropic import ChatAnthropic
from graph import build_pipeline
from scraper import parse_month_input, parse_quarter_input
from tools import SCRAPING_TOOLS

def main():
    tf = "week"
    args = sys.argv[1:]
    if "--quarter" in args: tf = "quarter"; args.remove("--quarter")
    elif "--month" in args: tf = "month"; args.remove("--month")
    date_input = " ".join(args) if args else input("📅 Enter date/month/quarter: ").strip()

    llm = ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                         temperature=0, anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"))
    year = month = quarter = 0
    if tf == "quarter": year, quarter = parse_quarter_input(date_input)
    elif tf == "month": year, month = parse_month_input(date_input)

    result = build_pipeline(llm, SCRAPING_TOOLS, tf, year, month, quarter).invoke(
        {"user_date": date_input, "time_frame": tf,
         "target_year": year, "target_month": month, "target_quarter": quarter})

    for key in ["quarterly_review", "monthly_reviews", "monthly_review", "analysis_report"]:
        val = result.get(key, "")
        if not val: continue
        if key == "monthly_reviews":
            for mk in sorted(val.keys()):
                print(f"\n{'═'*70}\n📋 MONTHLY REVIEW — {mk}\n{'═'*70}\n{val[mk]}")
        else:
            labels = {"quarterly_review": "📋 QUICK QUARTER REVIEW",
                      "monthly_review": "📋 MONTHLY REVIEW",
                      "analysis_report": "📊 EXECUTIVE ANALYSIS"}
            print(f"\n{'═'*70}\n{labels[key]}\n{'═'*70}\n{val}")

if __name__ == "__main__":
    main()