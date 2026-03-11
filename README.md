# 📚 r/books Reading Thread - Scrape & Analyse Pipeline

A **LangGraph** multi-agent pipeline that scrapes r/books reading threads
and produces executive analysis reports. Supports **week**, **month**, and
**quarter** time frames.

## Pipeline Modes

### Week
```
scraper → analysis → END
```

### Month (parallel for the 'week' scrapers)
```
START →Send(scrape_week)×N → monthly_review → analysis → END
```

### Quarter (parallel for the 'week' scrapers )
```
START →Send(scrape_week)×N → group_monthly_reviews → quarterly_review → analysis → END
          (all weeks from                (3 monthly          (summarises
           3 months in                    reviews              the 3 monthly
           parallel)                      generated)           reviews)
```

All weekly scraping runs **in parallel** via LangGraph's `Send()` API with an
`operator.add` reducer for automatic result merging.

**Quarter output order:**
1. **Quick Quarter Review** → concise summary of the 3 monthly reviews
2. **3 Monthly Reviews** → one per month, displayed individually
3. **Deep Analysis** → full executive report covering the entire quarter:
   book mention rankings, sentiment, new releases generating buzz,
   month-over-month trends, and market conclusions

## Architecture

```
graph.py           ← LangGraph StateGraph (week/month/quarter pipelines)
agent.py           ← CLI (OpenAI)          --month / --quarter flags
agent_anthropic.py ← CLI (Anthropic)       --month / --quarter flags
standalone.py      ← Scrape-only CLI       --month / --quarter flags
streamlit_app.py   ← Streamlit web UI      Week/Month/Quarter dropdown
tools.py           ← LangChain @tool definitions
scraper.py         ← Reddit JSON API + load-more expansion + quarter helpers
```

## Setup

```bash
pip install -r requirements.txt
# add API keys for OpenAI and Anthropic
```

## Usage

```bash
# Streamlit
streamlit run streamlit_app.py

# CLI — week
python agent.py "2025-01-13"

# CLI — month
python agent.py --month "2025-01"

# CLI — quarter
python agent.py --quarter "2025-Q1"
python agent.py --quarter "Q2 2025"

# Anthropic
python agent_anthropic.py --quarter "2025-Q1"

# Scrape only (no LLM)
python standalone.py --quarter "2025-Q1"
```