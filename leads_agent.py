"""
IBL.ai Leads Research Agent
Discovery: Serper.dev (Google Search) — site:linkedin.com/in queries
Enrichment: None — name/title/company parsed from search snippets
Output: CSV with name, title, company, LinkedIn URL, outreach message
"""

import requests
import csv
import os
import time
import re
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

SERPER_API_KEY   = os.getenv("SERPER_API_KEY", "")
OUTPUT_FILE      = "leads_output.csv"
LEADS_TARGET     = 10
MAX_SERPER_CALLS = 90    # free tier: 2500 total, cap per run at 90 to be safe
SERPER_DELAY     = 0.3   # seconds between calls

# ── Search Queries ─────────────────────────────────────────────────────────────

SEARCH_QUERIES = [
    'site:linkedin.com/in "Chief Technology Officer" "university"',
    'site:linkedin.com/in "Chief Information Officer" "university"',
    'site:linkedin.com/in "VP of Technology" "university"',
    'site:linkedin.com/in "Director of Technology" "university"',
    'site:linkedin.com/in "Chief Digital Officer" "university"',
    'site:linkedin.com/in "Head of Innovation" "university"',
    'site:linkedin.com/in "Director of Information Technology" "school district"',
    'site:linkedin.com/in "Chief Technology Officer" "college"',
    'site:linkedin.com/in "VP of Information Technology" "higher education"',
    'site:linkedin.com/in "Chief Academic Officer" "university"',
    'site:linkedin.com/in "Director of eLearning" "university"',
    'site:linkedin.com/in "Dean of Digital Learning" "university"',
    'site:linkedin.com/in "Chief Innovation Officer" "university"',
    'site:linkedin.com/in "Head of Digital Transformation" "university"',
    'site:linkedin.com/in "CTO" "school district"',
]


# ── Serper Search ──────────────────────────────────────────────────────────────

def serper_search(query: str, num: int = 10) -> list[dict]:
    """
    Search Google via Serper. Returns list of raw result dicts
    with keys: title, link, snippet.
    """
    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": min(num, 10)}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json().get("organic", [])
    except requests.HTTPError as e:
        print(f"  [Serper error] {e.response.status_code}: {e.response.text[:200]}")
        return []
    except Exception as e:
        print(f"  [Serper error] {e}")
        return []


# ── Education Filter ──────────────────────────────────────────────────────────

EDUCATION_TERMS = [
    "university", "college", "school", "district", "academy", "institute",
    "higher education", "edu", "faculty", "campus", "polytechnic", "seminary",
    "community college", "k-12", "kindergarten",
]

def is_education(text: str) -> bool:
    """Return True if the text contains an education-related term."""
    t = text.lower()
    return any(term in t for term in EDUCATION_TERMS)


# ── Snippet Parser ─────────────────────────────────────────────────────────────

def parse_lead(result: dict) -> dict | None:
    """
    Extract name, title, company from a LinkedIn Google search result.

    Google titles typically look like:
      "Jeff Ferranti - Chief Digital Officer at Duke Health | LinkedIn"
      "Jane Smith - VP of Technology at MIT | LinkedIn"
      "John Doe | Chief Information Officer at Stanford University"
    Snippets typically look like:
      "Chief Digital Officer at Duke University. Previously at..."
    """
    raw_title = result.get("title", "")
    link      = result.get("link", "")
    snippet   = result.get("snippet", "")

    if "linkedin.com/in/" not in link:
        return None

    linkedin_url = link.split("?")[0].rstrip("/")

    name, title, company = "", "", ""

    # ── Step 1: Parse name from title ────────────────────────────────────────
    # Strip trailing "| LinkedIn"
    clean = re.sub(r'\s*[|\-–]\s*LinkedIn\s*$', '', raw_title, flags=re.IGNORECASE).strip()

    # Split on first " - " / " – " / " | "
    parts = re.split(r'\s*[-–|]\s*', clean, maxsplit=1)
    if len(parts) == 2:
        name = parts[0].strip()
        rest = parts[1].strip()

        # rest is "Title at Company" or just "Title"
        at_split = re.split(r'\s+at\s+', rest, maxsplit=1, flags=re.IGNORECASE)
        if len(at_split) == 2:
            title   = at_split[0].strip()
            company = at_split[1].strip().rstrip(".")
        else:
            # whole rest is the title (company might be in snippet)
            title = rest

    # ── Step 2: Company fallback — parse from snippet ─────────────────────────
    if not company and snippet:
        # Snippet often starts with "Title at Company ..." or "Name · Title at Company"
        # Try: "at <Company>" pattern
        at_match = re.search(r'\bat\s+([A-Z][^.|\n]+?)(?:\s*[.\|·]|\s{2}|$)', snippet)
        if at_match:
            company = at_match.group(1).strip().rstrip(".")

    # ── Step 3: Clean up truncated company names (remove trailing "...") ──────
    company = re.sub(r'\s*\.\.\.$', '', company).strip()
    title   = re.sub(r'\s*\.\.\.$', '', title).strip()

    # ── Step 4: Fix bad title (sometimes the university name ends up as title) ─
    # If title looks like a company/institution name (no verb-like words), swap
    if title and not company and is_education(title):
        company = title
        title   = ""  # will try to fill from snippet below

    # Try to get title from snippet if missing
    if not title and snippet:
        # Snippet often starts with the title
        title_match = re.match(
            r'^(?:[A-Z][a-z]+(?: [A-Z][a-z]+)*\s*·\s*)?'  # optional "Name · "
            r'([A-Z][^.|\n·]{3,60}?)\s+at\s+',
            snippet
        )
        if title_match:
            title = title_match.group(1).strip()

    # ── Step 5: Validate — must have name + at least title or company ─────────
    if not name or len(name.split()) < 2:
        return None
    if not title and not company:
        return None

    # ── Step 6: Education filter — drop if no education signal anywhere ───────
    combined = f"{title} {company} {snippet}".lower()
    if not is_education(combined):
        return None

    return {
        "name":        name,
        "title":       title,
        "company":     company,
        "linkedin_url": linkedin_url,
        "snippet":     snippet,
    }


# ── Outreach Message ───────────────────────────────────────────────────────────

def draft_outreach(name: str, title: str, company: str) -> str:
    first        = name.split()[0] if name else "there"
    role_phrase  = f"as {title} " if title else ""
    at_phrase    = f"at {company}" if company else "at your institution"
    focus_phrase = f"at {company}" if company else "in your role"
    return (
        f"Hi {first},\n\n"
        f"I came across your profile and saw you're working {role_phrase}{at_phrase}. "
        f"I'm reaching out because IBL.ai builds AI infrastructure specifically for education — "
        f"helping schools and universities deliver personalised learning at scale without heavy IT lift.\n\n"
        f"Given your focus on technology and innovation {focus_phrase}, I thought it might be worth "
        f"a quick 20-minute chat to see if there's a fit. Would you be open to connecting this week?\n\n"
        f"Best,\n[Your Name]\nIBL.ai"
    )


# ── CSV Output ─────────────────────────────────────────────────────────────────

FIELDS = ["Name", "Title", "Company", "LinkedIn URL", "Outreach Message"]

def save_csv(leads: list[dict], path: str = OUTPUT_FILE):
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(leads)
    print(f"\n[+] Saved {len(leads)} leads -> {path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    collected_urls = set()
    leads = []
    serper_calls = 0

    print(f"[*] IBL.ai Lead Agent — target: {LEADS_TARGET} leads\n")

    for query in SEARCH_QUERIES:
        if len(leads) >= LEADS_TARGET:
            break
        if serper_calls >= MAX_SERPER_CALLS:
            print(f"[!] Serper call cap reached ({MAX_SERPER_CALLS}), stopping.")
            break

        print(f"[Search] {query[:80]}...")
        results = serper_search(query, num=10)
        serper_calls += 1
        print(f"         -> {len(results)} results  [calls used: {serper_calls}/{MAX_SERPER_CALLS}]")
        time.sleep(SERPER_DELAY)

        for result in results:
            if len(leads) >= LEADS_TARGET:
                break

            link = result.get("link", "")
            if "linkedin.com/in/" not in link:
                continue

            clean_url = link.split("?")[0].rstrip("/")
            if clean_url in collected_urls:
                continue
            collected_urls.add(clean_url)

            parsed = parse_lead(result)
            if not parsed:
                continue

            outreach = draft_outreach(parsed["name"], parsed["title"], parsed["company"])
            leads.append({
                "Name":             parsed["name"],
                "Title":            parsed["title"],
                "Company":          parsed["company"],
                "LinkedIn URL":     parsed["linkedin_url"],
                "Outreach Message": outreach,
            })
            print(f"  [{len(leads)}/{LEADS_TARGET}] {parsed['name']} — {parsed['title']} @ {parsed['company']}")

    if not leads:
        print("\n[!] No leads collected. Check API key or adjust queries.")
        return

    save_csv(leads)

    print("\n--- Preview ---")
    for i, lead in enumerate(leads, 1):
        print(f"\n{i}. {lead['Name']}")
        print(f"   Title:    {lead['Title']}")
        print(f"   Company:  {lead['Company']}")
        print(f"   LinkedIn: {lead['LinkedIn URL']}")
        print(f"   Message preview: {lead['Outreach Message'][:120]}...")

    print(f"\n[+] Done. Full output in {OUTPUT_FILE}")


if __name__ == "__main__":
    run()
