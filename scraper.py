"""
Reddit scraper for r/books weekly reading threads.

Uses Reddit's public JSON API (no authentication needed).
Supports expanding "load more comments" stubs to retrieve ALL comments.
"""

import json
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

# ── constants ──────────────────────────────────────────────────────────────────
SUBREDDIT = "books"
THREAD_TITLE_PATTERN = re.compile(
    r"what\b.*\breading\b.*\bweek", re.IGNORECASE
)
REDDIT_SEARCH_URL = "https://www.reddit.com/r/{subreddit}/search.json"
REDDIT_COMMENTS_URL = "https://www.reddit.com/comments/{post_id}.json"
REDDIT_MORECHILDREN_URL = "https://www.reddit.com/api/morechildren.json"
USER_AGENT = (
    "Mozilla/5.0 (compatible; RedditBooksScraper/1.0; "
    "+https://github.com/example/reddit-books-scraper)"
)
HEADERS = {"User-Agent": USER_AGENT}

EXAMPLE_LINKS = [
    "https://www.reddit.com/r/books/comments/1row2u5/what_books_did_you_start_or_finish_reading_this/",
    "https://www.reddit.com/r/books/comments/1ripuyz/what_books_did_you_start_or_finish_reading_this/",
]


# ── helpers ────────────────────────────────────────────────────────────────────

def get_monday(date_str: str) -> datetime:
    """Parse a date string and return the Monday of that ISO week."""
    date_obj = _parse_date(date_str)
    days_since_monday = date_obj.weekday()
    return date_obj - timedelta(days=days_since_monday)


def _parse_date(date_str: str) -> datetime:
    """Try multiple date formats."""
    date_str = date_str.strip()
    formats = [
        "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%B %d, %Y",
        "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%m-%d-%Y",
        "%d/%m/%Y", "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Could not parse date '{date_str}'. "
        f"Use a format like YYYY-MM-DD or Month DD, YYYY."
    )


def _safe_get(url: str, params: Optional[dict] = None, retries: int = 3) -> dict:
    """GET with retry + rate-limit back-off. Returns parsed JSON."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 5))
                print(f"  ⏳ Rate-limited, waiting {wait}s …")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise RuntimeError(f"Request failed after {retries} attempts: {exc}")
    return {}


# ── core scraping ─────────────────────────────────────────────────────────────

def find_weekly_thread(target_monday: datetime) -> Optional[dict]:
    """
    Search r/books for the weekly reading thread posted on *target_monday*.

    Returns post metadata dict (selftext/body is discarded) or None.
    """
    print(f"  🔍 Searching r/{SUBREDDIT} for thread near {target_monday.strftime('%Y-%m-%d')} …")

    params = {
        "q": 'title:"reading this week"',
        "restrict_sr": "on",
        "sort": "new",
        "t": "year",
        "limit": 50,
        "type": "link",
    }
    data = _safe_get(REDDIT_SEARCH_URL.format(subreddit=SUBREDDIT), params=params)

    posts = data.get("data", {}).get("children", [])
    print(f"  📄 Got {len(posts)} search results, filtering by date …")

    best_match = None
    best_diff = float("inf")

    for post in posts:
        pdata = post.get("data", {})
        title = pdata.get("title", "")
        created_utc = pdata.get("created_utc", 0)

        if not THREAD_TITLE_PATTERN.search(title):
            continue

        post_dt = datetime.utcfromtimestamp(created_utc)
        diff = abs((post_dt - target_monday).total_seconds())

        if diff < 2 * 86400 and diff < best_diff:
            best_diff = diff
            best_match = {
                "id": pdata.get("id"),
                "title": title,
                "url": f"https://www.reddit.com{pdata.get('permalink', '')}",
                "author": pdata.get("author", "[deleted]"),
                "created_utc": created_utc,
                "created_date": post_dt.strftime("%Y-%m-%d %H:%M UTC"),
                "num_comments": pdata.get("num_comments", 0),
                "score": pdata.get("upvotes", pdata.get("score", 0)),
                # selftext deliberately omitted — we only want comments
            }

    if best_match:
        print(f"  ✅ Found: \"{best_match['title']}\" ({best_match['created_date']})")
    else:
        print(f"  ❌ No matching thread found for {target_monday.strftime('%Y-%m-%d')}")

    return best_match


def scrape_thread_comments(
    post_id: str,
    max_depth: int = 10,
    expand_more: bool = True,
) -> list[dict]:
    """
    Fetch ALL comments for a Reddit post, including expanding "load more"
    stubs via the morechildren API.

    Args:
        post_id:     Reddit post ID (e.g. '1row2u5').
        max_depth:   Maximum nesting depth.
        expand_more: If True, chase "load more comments" stubs to get
                     every comment. Set False for faster partial scrapes.

    Returns:
        Flat list of comment dicts with depth information.
    """
    url = REDDIT_COMMENTS_URL.format(post_id=post_id)
    params = {"limit": 500, "depth": max_depth, "sort": "top"}

    print(f"  💬 Fetching comments for post {post_id} …")
    data = _safe_get(url, params=params)

    if not isinstance(data, list) or len(data) < 2:
        print("  ⚠️  Unexpected response structure")
        return []

    comments_listing = data[1]
    children = comments_listing.get("data", {}).get("children", [])

    all_comments = []
    more_stubs = []  # collect (depth, children_ids) from "more" nodes
    _flatten_comments(children, all_comments, more_stubs, depth=0)

    print(f"  📝 Initial pass: {len(all_comments)} comments, {len(more_stubs)} 'more' stubs")

    # ── Expand "load more comments" stubs ──────────────────────────────────
    if expand_more and more_stubs:
        link_id = f"t3_{post_id}"
        total_expanded = 0

        for stub_depth, child_ids in more_stubs:
            if not child_ids:
                continue

            # The API accepts up to ~100 IDs per call
            for batch_start in range(0, len(child_ids), 100):
                batch = child_ids[batch_start:batch_start + 100]
                print(f"  📥 Expanding {len(batch)} more comments (depth {stub_depth}) …")

                try:
                    more_data = _safe_get(
                        REDDIT_MORECHILDREN_URL,
                        params={
                            "api_type": "json",
                            "link_id": link_id,
                            "children": ",".join(batch),
                            "sort": "top",
                            "limit_children": "false",
                        },
                    )

                    things = (
                        more_data
                        .get("json", {})
                        .get("data", {})
                        .get("things", [])
                    )

                    for thing in things:
                        if thing.get("kind") != "t1":
                            continue
                        cdata = thing.get("data", {})
                        depth = cdata.get("depth", stub_depth)

                        all_comments.append({
                            "type": "comment",
                            "depth": depth,
                            "author": cdata.get("author", "[deleted]"),
                            "score": cdata.get("score", 0),
                            "created_utc": cdata.get("created_utc", 0),
                            "body": cdata.get("body", "[deleted]"),
                        })
                        total_expanded += 1

                except Exception as exc:
                    print(f"  ⚠️  Failed to expand batch: {exc}")

                # Be respectful of rate limits
                time.sleep(1)

        print(f"  📝 Expanded {total_expanded} additional comments")

    total = len(all_comments)
    print(f"  ✅ Total: {total} comments scraped")
    return all_comments


def _flatten_comments(
    children: list,
    acc: list,
    more_stubs: list,
    depth: int,
):
    """Recursively flatten the nested comment tree.

    Collects "more" stubs into more_stubs as (depth, [child_id, ...]) tuples
    so they can be expanded later.
    """
    for child in children:
        kind = child.get("kind", "")
        cdata = child.get("data", {})

        if kind == "more":
            child_ids = cdata.get("children", [])
            if child_ids:
                more_stubs.append((depth, child_ids))
            continue

        if kind != "t1":
            continue

        acc.append({
            "type": "comment",
            "depth": depth,
            "author": cdata.get("author", "[deleted]"),
            "score": cdata.get("score", 0),
            "created_utc": cdata.get("created_utc", 0),
            "body": cdata.get("body", "[deleted]"),
        })

        replies = cdata.get("replies", "")
        if isinstance(replies, dict):
            reply_children = replies.get("data", {}).get("children", [])
            _flatten_comments(reply_children, acc, more_stubs, depth + 1)


# ── month helpers ─────────────────────────────────────────────────────────────

def get_mondays_in_month(year: int, month: int) -> list[datetime]:
    """Return all Monday dates within a given year/month."""
    from calendar import monthrange
    _, num_days = monthrange(year, month)
    mondays = []
    for day in range(1, num_days + 1):
        dt = datetime(year, month, day)
        if dt.weekday() == 0:  # Monday
            mondays.append(dt)
    return mondays


def parse_month_input(month_str: str) -> tuple[int, int]:
    """Parse 'YYYY-MM', 'January 2025', 'Jan 2025', etc. → (year, month)."""
    month_str = month_str.strip()
    # Try YYYY-MM
    for fmt in ["%Y-%m", "%B %Y", "%b %Y", "%m/%Y"]:
        try:
            dt = datetime.strptime(month_str, fmt)
            return dt.year, dt.month
        except ValueError:
            continue
    raise ValueError(
        f"Could not parse month '{month_str}'. "
        f"Use YYYY-MM, 'January 2025', or 'Jan 2025'."
    )


# ── quarter helpers ───────────────────────────────────────────────────────────

def get_quarter_months(year: int, quarter: int) -> list[tuple[int, int]]:
    """Return [(year, month), ...] for the 3 months in the given quarter."""
    if quarter < 1 or quarter > 4:
        raise ValueError(f"Quarter must be 1–4, got {quarter}")
    start_month = (quarter - 1) * 3 + 1
    return [(year, start_month + i) for i in range(3)]


def parse_quarter_input(q_str: str) -> tuple[int, int]:
    """Parse 'YYYY-Q1', '2025-Q3', 'Q1 2025', etc. → (year, quarter)."""
    import re
    q_str = q_str.strip().upper()
    m = re.match(r"(\d{4})\s*-?\s*Q(\d)", q_str)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"Q(\d)\s*-?\s*(\d{4})", q_str)
    if m:
        return int(m.group(2)), int(m.group(1))
    raise ValueError(
        f"Could not parse quarter '{q_str}'. Use YYYY-Q1, Q2-2025, etc."
    )


def get_all_mondays_in_quarter(year: int, quarter: int) -> list[datetime]:
    """Return all Mondays across the 3 months of a quarter."""
    mondays = []
    for y, m in get_quarter_months(year, quarter):
        mondays.extend(get_mondays_in_month(y, m))
    return sorted(mondays)


# ── formatting ─────────────────────────────────────────────────────────────────

def format_thread_output(post: dict, comments: list[dict]) -> str:
    """Format a scraped thread into readable CLI output."""
    lines = []
    sep = "=" * 80

    lines.append(sep)
    lines.append(f"📚  r/{SUBREDDIT} — Weekly Reading Thread")
    lines.append(sep)
    lines.append(f"Title:    {post['title']}")
    lines.append(f"Author:   u/{post['author']}")
    lines.append(f"Date:     {post['created_date']}")
    lines.append(f"URL:      {post['url']}")
    lines.append(f"Score:    {post['score']}  |  Comments: {post['num_comments']}")
    lines.append(sep)
    lines.append(f"COMMENTS ({len([c for c in comments if c['type'] == 'comment'])} loaded)")
    lines.append(sep)

    for c in comments:
        indent = "  " * c["depth"]
        author_str = f"u/{c['author']}" if c["author"] else "[deleted]"
        score_str = f"[{c['score']:+d}]" if c["score"] != 0 else ""
        prefix = "├─" if c["depth"] > 0 else "▸"

        lines.append(f"\n{indent}{prefix} {author_str} {score_str}")
        for body_line in c["body"].splitlines():
            lines.append(f"{indent}  {body_line}")

    lines.append(f"\n{sep}")
    lines.append(f"END OF THREAD — {len(comments)} items total")
    lines.append(sep)

    return "\n".join(lines)