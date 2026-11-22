"""The Reading Edit: the charismatic, outrageous, adventurous, impossibly cool.

Reads existing articles.json and keeps every entry unchanged. A failed API call,
invalid result or empty selection never overwrites the reading library.
Requires the OPENAI_API_KEY GitHub Actions repository secret.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
FEED = ROOT / "articles.json"
NOW = datetime.now(ZoneInfo("Europe/London"))

# These are deliberately broad: no one personality should dominate successive
# editions, even if different publications have written about them.
SUBJECT_ALIASES = {
    "gianni agnelli": ["agnelli", "l'avvocato"],
    "aristotle onassis": ["onassis", "christina o"],
    "porfirio rubirosa": ["rubirosa"],
    "gunter sachs": ["gunter sachs", "günter sachs"],
    "aly khan": ["aly khan", "ali khan"],
    "lady diana cooper": ["diana cooper", "lady diana manners"],
    "cecil beaton": ["cecil beaton"],
    "mitford sisters": ["mitford", "nancy mitford", "diana mosley", "deborah devonshire"],
    "wallis simpson": ["wallis simpson", "duchess of windsor"],
    "barbara hutton": ["barbara hutton"],
    "princess margaret": ["princess margaret"],
    "gloria guinness": ["gloria guinness"],
    "rita hayworth": ["rita hayworth"],
    # Different Kennedys should be eligible in different editions; a whole
    # dynasty is not a single person for editorial rotation.
    "john f. kennedy": ["john f. kennedy", "john f kennedy", "jfk"],
    "robert f. kennedy": ["robert f. kennedy", "robert f kennedy", "rfk"],
    "jacqueline kennedy": ["jackie kennedy", "jacqueline kennedy", "jackie onassis"],
    "kathleen kennedy": ["kick kennedy", "kathleen kennedy"],
    "rosemary kennedy": ["rosemary kennedy"],
    "joseph kennedy": ["joe kennedy", "joseph kennedy"],
    "edward kennedy": ["ted kennedy", "edward kennedy"],
    "kennedy family": ["kennedys", "the kennedys", "kennedy family", "kennedy dynasty"],
    "rockefeller family": ["rockefeller", "rockefellers"],
    "vanderbilt family": ["vanderbilt", "vanderbilts"],
    "astor family": ["astor family", "the astors", "astor dynasty"],
    "bouvier family": ["bouvier", "bouviers"],
    "truman capote": ["truman capote", "capote"],
    "babe paley": ["babe paley"],
    "doris duke": ["doris duke"],
    "william randolph hearst": ["william randolph hearst"],
}



def request_json(url, payload, api_key):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def clean_url(value):
    """Normalize obvious tracking/formatting differences for duplicate checks."""
    try:
        parts = urlsplit(str(value).strip())
        if parts.scheme.lower() != "https" or not parts.hostname:
            return ""
        domain = parts.hostname.lower().removeprefix("www.")
        path = re.sub(r"/+", "/", parts.path).rstrip("/")
        return urlunsplit(("https", domain, path, "", ""))
    except ValueError:
        return ""


def tidy_title(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def identify_subject(article):
    provided = str(article.get("subject", "")).strip().casefold()
    if provided:
        for subject, aliases in SUBJECT_ALIASES.items():
            if provided == subject or provided in aliases:
                return subject
        return provided
    body = f"{article.get('title', '')} {article.get('description', '')}".casefold()
    for subject, aliases in SUBJECT_ALIASES.items():
        if any(alias in body for alias in aliases):
            return subject
    return ""


def readable(url):
    if not clean_url(url):
        return False
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ReadingEdit/1.0)"},
        )
        with urllib.request.urlopen(request, timeout=18) as response:
            return (
                response.status == 200
                and "text/html" in response.headers.get("Content-Type", "text/html")
            )
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def extract_articles(api_response):
    """Avoid overwriting the feed when a model response is empty/incomplete."""
    chunks = []
    for item in api_response.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    chunks.append(content.get("text", ""))
    raw = "".join(chunks).strip()
    if not raw:
        print(
            "No article text from API:",
            json.dumps({
                "status": api_response.get("status"),
                "incomplete_details": api_response.get("incomplete_details"),
            }),
            file=sys.stderr,
        )
        return []
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        print("API returned invalid JSON; existing feed is untouched", file=sys.stderr)
        return []
    if isinstance(result, dict):
        result = result.get("articles", [])
    return result if isinstance(result, list) else []


def main():
    # Schedule has 07:00 & 08:00 UTC triggers for BST/GMT. A GitHub runner
    # can start late; permit late runs but never start before 08:00 London.
    if os.getenv("GITHUB_EVENT_NAME") == "schedule" and NOW.hour < 8:
        print("Before 08:00 London time; skipping")
        return

    existing = json.loads(FEED.read_text(encoding="utf-8"))
    if not isinstance(existing, list):
        raise ValueError("articles.json must be a JSON array")
    if any(item.get("added_on") == NOW.date().isoformat() for item in existing):
        print("Already published today; skipping")
        return

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing from GitHub Actions secrets")

    known_urls = {clean_url(a.get("url", "")) for a in existing}
    known_titles = {tidy_title(a.get("title", "")) for a in existing}
    recent_articles = existing[-12:]
    recent_subjects = {identify_subject(a) for a in recent_articles} - {""}

    # Rotate discovery angles to uncover people we have never heard of, not
    # another article about yesterday's headline personality.
    discovery_angles = [
        "magnetic rogues, irresistible charmers and playboys or playgirls who lived outrageously",
        "daring explorers, spies and adventurers with swagger, wit and improbably good stories",
        "stylish outsiders, fascinating eccentrics and iconoclastic artists or filmmakers",
        "charismatic American figures, larger-than-life Kennedys, glamorous troublemakers and Hollywood originals",
        "audacious aristocrats, jet-set icons, legendary hosts and people with unforgettable circles of friends",
        "beautifully written portraits of bohemians, daring aviators, gamblers and adventurous women",
        "people history nearly forgot: magnetic rebels, fearless travellers and extravagant personalities",
    ]
    lens = discovery_angles[NOW.toordinal() % len(discovery_angles)]
    history = [{"title": a.get("title", ""), "url": a.get("url", "")}
               for a in existing]

    prompt = f"""You are editor-in-chief of THE READING EDIT, a deeply selective
    personal reading collection about THE COOLEST, MOST CHARISMATIC,
    OUTRAGEOUS AND FASCINATING REAL PEOPLE who ever lived.
    Today is {NOW.date().isoformat()}.

    THIS IS NOT A HISTORY LESSON AND NOT A COLLECTION OF 'IMPORTANT PEOPLE'.
    The PERSON must be the draw: someone with real charm, swagger, wit,
    magnetism, bravado, a surprising personality or a wildly unconventional
    life. Fascinating company: someone you would give anything to have dinner
    with just to hear their stories. Search for lives full of deliciously
    unlikely adventures, glamorous friendships, remarkable romance,
    breathtaking risks, reckless decisions, absurd anecdotes, intrigue,
    astonishing talent or scandal. We like flair, individuality, style,
    charisma and people who lived on their own terms. Not all characters
    need to be glamorous, rich, admirable or even likeable.

    GIANNI AGNELLI, GUNTER SACHS, PORFIRIO RUBIROSA and ALY KHAN explain
    the *spirit*, NOT a shortlist to repeat. Other useful directions:
    a particularly compelling Kennedy, an unconventional American heiress,
    a daredevil, an irresistible Hollywood rogue, a British eccentric, a
    witty spy, a legendary photographer, an explorer with incredible personal
    adventures, an extraordinary woman, a flamboyant artist, a forgotten
    international charmer. Lesser-known names are actively preferred if the
    story is better. People can come from any country or period.

    TODAY'S DISCOVERY ANGLE (a nudge, not a quota): {lens}.

    HARD REJECTION TEST: Would this be exciting even if the person had no
    famous surname or job title? Is there specific evidence from the article
    of charisma, daring, coolness, delightful eccentricity or a thrillingly
    unusual personality? Is this a GREAT STORY, full of scenes, detail and
    narrative, rather than dry career milestones? If any answer is no,
    reject it. Brilliant prose is equally essential. Strongly prefer
    vivid long-form profiles and archival narrative journalism, roughly
    15-40 minutes where available. Two genuinely terrific articles beat five
    merely competent ones. Sometimes one is enough. Do not chase quotas.

    Search Vanity Fair's historic profiles, Esquire, The New Yorker,
    The Paris Review, Smithsonian, The Atlantic, Tatler, Town & Country,
    high-quality newspaper magazines, historical archives and other strong
    long-form sources. Articles from any decade are eligible. Avoid boring
    biographies, dry factual profiles, obituary roundups, generic wealth
    articles, fashion/luxury shopping, contemporary hospitality founders,
    clickbait, political updates, 'most influential' lists and trivia.
    A renowned person is NOT necessarily an interesting person.

    NEVER repeat an article already in this reading library, under any URL
    variant, syndicated copy, updated headline or archive republication:
    {json.dumps(history, ensure_ascii=False)}
    RECENTLY COVERED SUBJECTS, GIVE THEM A REST:
    {json.dumps(sorted(recent_subjects), ensure_ascii=False)}
    Deliver DIFFERENT central characters today; don't publish several pieces
    about the same person. Don't keep coming back to Agnelli or Rubirosa.

    Browse using web_search, find the exact original article, and inspect
    source pages before proposing. For each candidate, provide two brief,
    SPECIFIC, ARTICLE-SUPPORTED reasons: 'magnetic_detail' identifies a
    concrete action/anecdote/behaviour showing why the person is cool or
    unusually charismatic; 'storytelling_detail' describes evidence that
    the piece is gripping first-class narrative journalism. Do not invent
    these to fill a quota. If the original text isn't accessible enough to
    verify these details, reject the candidate. Check exact title, source,
    date and original HTTPS link. When the date isn't confirmed, say
    'Date not stated'; reading time must be a reasonable integer estimate.
    The description should be vivid, specific, accurate and spoiler-light.

    Return up to 8 STRONG candidate articles, ordered best-first, as
    structured JSON. The script may reject inaccessible links and will
    publish no more than 4. If quality is lacking, return fewer or none.
    Every object must have: title, publication, date, minutes (integer),
    description (1-2 detailed sentences), url, subject (person's full name),
    magnetic_detail, storytelling_detail."""

    article_properties = {
        "title": {"type": "string"},
        "publication": {"type": "string"},
        "date": {"type": "string"},
        "minutes": {"type": "integer"},
        "description": {"type": "string"},
        "url": {"type": "string"},
        "subject": {"type": "string"},
        "magnetic_detail": {"type": "string"},
        "storytelling_detail": {"type": "string"},
    }
    response_format = {
        "type": "json_schema", "name": "reading_edit_candidates", "strict": True,
        "schema": {
            "type": "object",
            "properties": {"articles": {"type": "array", "items": {
                "type": "object", "properties": article_properties,
                "required": list(article_properties), "additionalProperties": False,
            }}},
            "required": ["articles"], "additionalProperties": False,
        },
    }
    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        "tools": [{"type": "web_search"}],
        "input": prompt,
        "reasoning": {"effort": "low"},
        "max_output_tokens": 9500,
        "text": {"format": response_format},
    }
    response = request_json("https://api.openai.com/v1/responses", payload, api_key)
    candidates = extract_articles(response)
    print(f"Research returned {len(candidates)} candidate article(s)", flush=True)
    if not candidates:
        print("::warning::No candidate articles found; nothing was published.")

    additions = []
    subjects_today = set()
    for candidate in candidates[:12]:
        if not isinstance(candidate, dict):
            continue
        if not all(candidate.get(field) for field in (
            "title", "publication", "date", "description", "url", "subject",
            "magnetic_detail", "storytelling_detail"
        )):
            print("Skipping incomplete article")
            continue

        # Require concrete editorial justifications, not automatic "great person"
        # praise. Both fields are review notes, not app-facing text.
        if (len(str(candidate["magnetic_detail"]).strip()) < 35
                or len(str(candidate["storytelling_detail"]).strip()) < 30):
            print("Skipping insufficiently justified personality/quality:",
                  candidate["title"], flush=True)
            continue
        url = str(candidate["url"]).strip()
        canon = clean_url(url)
        title = tidy_title(candidate["title"])
        subject = identify_subject(candidate)
        if not canon or canon in known_urls:
            print("Skipping duplicate/invalid URL:", url)
            continue
        if not title or any(SequenceMatcher(None, title, previous).ratio() >= 0.88
                            for previous in known_titles if previous):
            print("Skipping repeated or near-duplicate title:", candidate["title"])
            continue
        if subject and (subject in recent_subjects or subject in subjects_today):
            print("Skipping overused subject:", subject)
            continue
        if not readable(url):
            print("Skipping unreachable article:", url)
            continue

        try:
            minutes = max(2, min(100, int(candidate["minutes"])))
        except (ValueError, TypeError):
            minutes = 15
        article = {
            "id": f"daily-{NOW:%Y%m%d}-{len(additions)+1}",
            "title": str(candidate["title"]).strip(),
            "publication": str(candidate["publication"]).strip(),
            "date": str(candidate["date"]).strip(),
            "minutes": minutes,
            "description": str(candidate["description"]).strip(),
            "url": url,
            "subject": str(candidate["subject"]).strip(),
            "added_on": NOW.date().isoformat(),
        }
        additions.append(article)
        known_urls.add(canon)
        known_titles.add(title)
        if subject:
            subjects_today.add(subject)
        print("ACCEPTED:", article["title"], "—", url, flush=True)
        if len(additions) == 4:
            break

    if not additions:
        print(f"::warning::No new articles published from {len(candidates)} candidate(s); "
              "all were rejected or none was returned. Existing library unchanged.", flush=True)
        return
    # Append only. No published article or saved/read/favourite status is deleted.
    FEED.write_text(json.dumps(existing + additions, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"Published {len(additions)} carefully selected new articles", flush=True)


if __name__ == "__main__":
    main()
