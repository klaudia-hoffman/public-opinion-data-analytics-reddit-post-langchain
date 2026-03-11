import json
from datetime import datetime

from langchain_core.tools import tool

from scraper import (
    find_weekly_thread,
    get_monday,
    scrape_thread_comments,
)

# Scraping

@tool
def parse_date_to_monday(date_str: str) -> str:
    """
    Given a date string, find the Monday that starts that week.
    If the date IS a Monday, it returns that same date.
    Accepts formats like: YYYY-MM-DD, MM/DD/YYYY, Month DD YYYY, etc.

    Args:
        date_str: A date string in any common format.

    Returns:
        The Monday date in YYYY-MM-DD format.
    """
    try:
        monday = get_monday(date_str)
        parsed = None
        for fmt in [
            "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%B %d, %Y",
            "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%m-%d-%Y",
            "%d/%m/%Y", "%Y/%m/%d",
        ]:
            try:
                parsed = datetime.strptime(date_str.strip(), fmt)
                break
            except ValueError:
                continue

        note = ""
        if parsed and parsed.weekday() != 0:
            note = (
                f" (Note: {date_str} is a {parsed.strftime('%A')}; "
                f"adjusted to the Monday of that week)"
            )
        return f"{monday.strftime('%Y-%m-%d')}{note}"
    except ValueError as e:
        return f"ERROR: {e}"


@tool
def search_reddit_thread(monday_date: str) -> str:
    """
    Search r/books for the weekly reading thread posted on the given Monday.

    Args:
        monday_date: A Monday date in YYYY-MM-DD format.

    Returns:
        JSON string with post metadata (no post body), or an error message.
    """
    try:
        target = datetime.strptime(monday_date.strip(), "%Y-%m-%d")
    except ValueError:
        return "ERROR: monday_date must be in YYYY-MM-DD format."

    result = find_weekly_thread(target)
    if result is None:
        return (
            f"No weekly reading thread found for the week of {monday_date}. "
            f"Try an adjacent week."
        )
    return json.dumps(result, indent=2)


@tool
def scrape_all_comments(post_id: str) -> str:
    """
    Scrape ALL comments and replies from a Reddit post, including
    expanding every "load more comments" stub.

    This returns the complete comment dataset for analysis.

    Args:
        post_id: The Reddit post ID (e.g. '1row2u5').

    Returns:
        JSON string with an array of every comment object.
    """
    comments = scrape_thread_comments(post_id, expand_more=True)
    return json.dumps(comments, indent=2, default=str)


# Collect scraping tools
SCRAPING_TOOLS = [
    parse_date_to_monday,
    search_reddit_thread,
    scrape_all_comments,
]
