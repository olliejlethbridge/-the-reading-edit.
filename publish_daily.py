"""The Reading Edit — character-first, duplicate-safe daily publisher.

Uses the OpenAI Responses API with web search. Appends to articles.json;
never rewrites or removes an existing article. Library selections remain in the app.
Requires the GitHub Actions secret OPENAI_API_KEY.
"""
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

FEED = Path(__file__).resolve().parent / "articles.json"
NOW = datetime.now(ZoneInfo("Europe/London"))


def norm_url(value):
    try:
        p = urlsplit(str(value).strip())
        if p.scheme.lower() != "https" or not p.hostname:
            return ""
        host = p.hostname.lower().removeprefix("www.")
        path = re.sub(r"/+", "/", p.path).rstrip("/")
        return urlunsplit(("https", host, path, "", ""))
    except (ValueError, TypeError):
        return ""


def norm_title(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def norm_person(value):
    simple = unicodedata.normalize("NFKD", str(value).casefold())
    simple = "".join(c for c in simple if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", simple).strip()


def person_key(article):
    """Recognise the founding personalities even in old records with no subject field."""
    aliases = {
        "gianni agnelli": ("agnelli",),
        "porfirio rubirosa": ("rubirosa",),
        "aristotle onassis": ("onassis", "christina o"),
        "gunter sachs": ("gunter sachs", "potemkin playboys"),
        "lady diana cooper": ("diana cooper",),
    }
    raw = norm_person(article.get("subject") or "")
    body = norm_person(" ".join(str(article.get(k, "")) for k in ("title", "description")))
    for canonical, variants in aliases.items():
        if any(v in raw for v in variants) or any(v in body for v in variants):
            return canonical
    return raw


def reachable(url):
    """Check an actual HTML article page; never invent a working URL."""
    if not norm_url(url):
        return False
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; ReadingEdit/1.0)",
                          "Accept": "text/html,application/xhtml+xml"})
        with urllib.request.urlopen(req, timeout=18) as res:
            return (200 <= res.status < 300 and
                    "html" in res.headers.get("Content-Type", "text/html").lower())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def api_call(key, prompt):
    """One web-grounded discovery pass. Requiring the tool prevents unsearched suggestions."""
    fields = {
        "title": {"type": "string"},
        "publication": {"type": "string"},
        "date": {"type": "string"},
        "minutes": {"type": "integer"},
        "description": {"type": "string"},
        "url": {"type": "string"},
        "subject": {"type": "string"},
    }
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
        "tools": [{"type": "web_search", "search_context_size": "medium"}],
        "tool_choice": "required",
        "input": prompt,
        "reasoning": {"effort": "low"},
        "max_output_tokens": 7000,
        "text": {"format": {
            "type": "json_schema", "name": "reading_edit_articles", "strict": True,
            "schema": {"type": "object", "properties": {
                "articles": {"type": "array", "items": {
                    "type": "object", "properties": fields,
                    "required": list(fields), "additionalProperties": False}}},
                "required": ["articles"], "additionalProperties": False},
        }},
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=210) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        # Never print auth header or full request.
        print(f"OpenAI API HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        raise

    output = data.get("output", [])
    snippets = [c.get("text", "") for item in output if item.get("type") == "message"
                for c in item.get("content", []) if c.get("type") == "output_text"]
    raw = "".join(snippets).strip()
    usage = data.get("usage", {})
    print("API response status:", data.get("status"),
          "; web searches:", sum(1 for x in output if x.get("type") == "web_search_call"),
          "; output tokens:", usage.get("output_tokens"), flush=True)
    if data.get("status") != "completed":
        print("Incomplete details:", data.get("incomplete_details"), flush=True)
    if not raw:
        print("No readable JSON returned (output item types:",
              [x.get("type") for x in output], ")", flush=True)
        return []
    try:
        obj = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw))
    except json.JSONDecodeError:
        print("Invalid JSON returned; first 120 chars:", repr(raw[:120]), flush=True)
        return []
    return obj.get("articles", []) if isinstance(obj, dict) and isinstance(obj.get("articles"), list) else []


def main():
    # The workflow is scheduled for both 07:00 and 08:00 UTC for UK DST.
    # Manual dispatch can run at any time.
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and NOW.hour < 8:
        print("Scheduled before 08:00 in London; skipping", flush=True)
        return

    existing = json.loads(FEED.read_text(encoding="utf-8"))
    if not isinstance(existing, list) or not all(isinstance(a, dict) for a in existing):
        raise ValueError("articles.json must be a list of article objects")
    day = NOW.date().isoformat()
    if any(a.get("added_on") == day for a in existing):
        print("Today's edition is already published; no changes", flush=True)
        return

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Missing OPENAI_API_KEY secret")

    old_urls = {norm_url(a.get("url", "")) for a in existing}
    old_titles = {norm_title(a.get("title", "")) for a in existing}
    recent_people = {person_key(a) for a in existing[-8:]} - {""}
    # Short, concrete discovery instructions. Keep nuanced editorial choices in
    # the prompt, but don't demand that every page has an accessible full text.
    historic_titles = [a.get("title", "") for a in existing]
    scene = [
        "forgotten magnetic adventurers, daring explorers and charismatic spies",
        "stylish Hollywood rogues, magnetic artists, spectacular eccentrics",
        "American originals, extraordinary Kennedys, captivating heiresses and socialites",
        "witty British adventurers, international charmers, charismatic rebels",
        "bold women, bohemian legends, eccentric aristocrats and outrageous characters",
        "colourful jet-set personalities and larger-than-life historical figures",
        "audacious gamblers, extraordinary photographers, aviators and wandering writers",
    ][NOW.toordinal() % 7]

    base = f"""Find outstanding EXISTING magazine profiles or beautifully reported narrative articles
about extraordinarily COOL, CHARISMATIC, FASCINATING real personalities.
We love people with swagger, charm, wit, daring, eccentricity, unlikely adventures,
scandalous friends, outrageous lives and fascinating stories. Think the spirit of
Agnelli, Rubirosa, Gunter Sachs, Aly Khan, Robert Capa, Peter Fleming or a magnetic
Kennedy, NOT more of the same articles about these particular people.
They may be women or men, admirable or flawed, world-famous or forgotten.
We want to think: 'God, I wish I'd met this person.' Great prose and vivid scenes
matter. Not generic luxury, lists, fashion, business advice, dry biography,
news politics, generic celebrity news, or hospitality founders.
For today, look especially for {scene}.
Search Vanity Fair archives, Esquire, The New Yorker, Tatler, Town & Country,
The Paris Review, Smithsonian, excellent newspapers and other quality archives.
ARCHIVAL ARTICLES ARE ENCOURAGED. Choose diverse *central people*.
Do NOT suggest any previously published titles: {json.dumps(historic_titles, ensure_ascii=False)}.
Use web search and cite only genuine direct HTTPS ORIGINAL article pages you find.
Return 5 to 8 promising articles in best-first order with a vivid, accurate
1-2-sentence description; include original publication and date if known, otherwise
'Date not stated'. Reading time is an estimate, in minutes.
This is candidate DISCOVERY, not final approval: suggest a good range of strong
possibilities rather than applying an impossible proof standard. Do not invent URLs.
Return JSON matching the schema."""

    candidates = api_call(key, base)
    print("First discovery pass returned", len(candidates), "candidate(s)", flush=True)
    # One bounded fallback, only if the source model found nothing at all.
    # This costs an additional API call; it is not an unbounded retry loop.
    if not candidates:
        fallback = ("Search the web for 5 to 8 real, compelling long-form personality "
                    "profiles of eccentric adventurers, charismatic rogues, "
                    "unforgettable American socialites, daring explorers or film legends. "
                    "Favour beautiful narrative journalism, especially archival "
                    "Vanity Fair, Esquire, New Yorker, Smithsonian and Tatler. "
                    "Return genuine, directly linked articles, not generic lists. "
                    f"Do not repeat these titles: {json.dumps(historic_titles, ensure_ascii=False)}. "
                    "Use web search; return JSON matching the schema, with real URLs, "
                    "dates or 'Date not stated', subject name and engaging summaries. "
                    "These are suggestions for later validation, not a demand for "
                    "conclusive proof of every anecdote before returning candidates.")
        candidates = api_call(key, fallback)
        print("Fallback discovery returned", len(candidates), "candidate(s)", flush=True)

    added = []
    people_today = set()
    for a in candidates[:10]:
        if not isinstance(a, dict) or not all(a.get(f) for f in (
                "title", "publication", "date", "description", "url", "subject")):
            print("REJECT missing metadata", flush=True)
            continue
        title, url, person = norm_title(a["title"]), norm_url(a["url"]), person_key(a)
        if not url or url in old_urls:
            print("REJECT invalid/duplicate URL:", str(a["title"])[:90], flush=True)
            continue
        if not title or any(SequenceMatcher(None, title, p).ratio() >= .88 for p in old_titles if p):
            print("REJECT repeated title:", str(a["title"])[:90], flush=True)
            continue
        if person and (person in recent_people or person in people_today):
            print("REJECT repeated personality:", a["subject"], flush=True)
            continue
        if not reachable(str(a["url"])):
            print("REJECT inaccessible original article:", str(a["url"])[:140], flush=True)
            continue
        try:
            minutes = max(2, min(95, int(a.get("minutes", 15))))
        except (TypeError, ValueError):
            minutes = 15
        article = {
            "id": f"daily-{NOW:%Y%m%d}-{len(added)+1}",
            "title": str(a["title"]).strip(),
            "publication": str(a["publication"]).strip(),
            "date": str(a["date"]).strip(),
            "minutes": minutes,
            "description": str(a["description"]).strip(),
            "url": str(a["url"]).strip(),
            "subject": str(a["subject"]).strip(),
            "added_on": day,
        }
        added.append(article)
        old_urls.add(url)
        old_titles.add(title)
        people_today.add(person)
        print("ACCEPT:", article["title"], "—", article["subject"], flush=True)
        if len(added) == 4:
            break

    if not added:
        # FAIL VISIBLY; otherwise GitHub shows green despite an empty edition.
        raise RuntimeError(f"No articles published: {len(candidates)} candidates returned, "
                           "none passed validation. Existing articles.json untouched.")

    FEED.write_text(json.dumps(existing + added, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"SUCCESS: appended {len(added)} articles (now {len(existing) + len(added)} total)", flush=True)


if __name__ == "__main__":
    main()
