"""Standalone scraper (no LLM). Supports --month and --quarter."""
import sys
from scraper import (find_weekly_thread, format_thread_output, get_monday,
                     get_mondays_in_month, get_all_mondays_in_quarter,
                     parse_month_input, parse_quarter_input, scrape_thread_comments)

# this is only used for quick testing and comes with no LLM costs
def main():
    tf = "week"
    args = sys.argv[1:]
    if "--quarter" in args: tf = "quarter"; args.remove("--quarter")
    elif "--month" in args: tf = "month"; args.remove("--month")
    date_input = " ".join(args) if args else input("📅 Enter date/month/quarter: ").strip()
    if not date_input: return

    if tf == "quarter":
        year, quarter = parse_quarter_input(date_input)
        mondays = get_all_mondays_in_quarter(year, quarter)
        print(f"\n📅 Quarter {year}-Q{quarter} — {len(mondays)} weeks")
    elif tf == "month":
        year, month = parse_month_input(date_input)
        mondays = get_mondays_in_month(year, month)
        print(f"\n📅 Month {year}-{month:02d} — {len(mondays)} weeks")
    else:
        mondays = [get_monday(date_input)]
        print(f"\n📅 Week of {mondays[0].strftime('%Y-%m-%d')}")

    for monday in mondays:
        print(f"\n{'─'*60}")
        post = find_weekly_thread(monday)
        if not post: print(f"  ❌ No thread for {monday.strftime('%Y-%m-%d')}"); continue
        comments = scrape_thread_comments(post["id"], expand_more=True)
        print(format_thread_output(post, comments))

    print(f"\n💡 For AI analysis: python agent.py --{tf} \"{date_input}\"")

if __name__ == "__main__":
    main()