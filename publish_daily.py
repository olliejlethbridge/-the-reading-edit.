"""The Reading Edit: resilient daily publisher (2026-11-22).

Strategy:
1. Ask the OpenAI Responses API to discover new personality-led archival articles.
2. Independently reject repeat URLs, titles, and recently featured people.
3. If discovery is empty/blocked, draw from a LIMITED manually researched,
   original-source archival reserve. This prevents an empty edition when search
   returns [] but is not a substitute for ongoing new discovery indefinitely.
4. Append only to articles.json. Never delete or replace published entries.

GitHub Actions supplies OPENAI_API_KEY. No third-party Python dependencies.
"""

import html
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
TODAY = NOW.date().isoformat()

# Pre-researched original-source pieces, not model-generated links.
# Research verified titles/source URLs on 22 Nov 2026. Magazine archive
# subscriptions may still be necessary, and URLs can change in future.
# Keep this deliberately finite, so adding new editorial material remains a
# visible requirement rather than recycling the same eight familiar profiles.
EDITORIAL_RESERVE = [
    {
        "title": "The Legend of Peter Beard", "publication": "Vanity Fair", "date": "September 2020",
        "minutes": 19, "subject": "Peter Beard",
        "description": "Photographer, Kenyan wilderness adventurer and notorious society wild man: an extraordinary life spent between African game trails and New York's most glamorous parties.",
        "url": "https://www.vanityfair.com/style/2020/09/the-legend-of-peter-beard",
    },
    {
        "title": "Robert Capa's Longest Day", "publication": "Vanity Fair", "date": "June 2014",
        "minutes": 24, "subject": "Robert Capa",
        "description": "The swaggering, romantic war photographer lands at Omaha Beach on D-Day, producing eleven surviving photographs and one of journalism's most extraordinary stories.",
        "url": "https://www.vanityfair.com/culture/2014/06/photographer-robert-capa-d-day",
    },
    {
        "title": "The Last Queen of Paris", "publication": "Vanity Fair", "date": "September 2010",
        "minutes": 24, "subject": "Jacqueline de Ribes",
        "description": "The mysterious French countess at the heart of postwar high society recalls outrageous masked balls, Diana Vreeland, Cecil Beaton and a lifetime of immaculate reinvention.",
        "url": "https://www.vanityfair.com/news/2010/09/jacqueline-deribes-201009",
    },
    {
        "title": "A Short, Bumpy Ride with Steve McQueen", "publication": "Esquire", "date": "June 1967",
        "minutes": 15, "subject": "Steve McQueen",
        "description": "A vintage encounter with Hollywood's king of cool, capturing the combustible star in the middle of his sixties fame rather than looking back from a safe distance.",
        "url": "https://classic.esquire.com/article/1967/6/1/a-short-bumpy-ride-with-steve-mcqueen",
    },
    {
        "title": "The Wild Life and Many Loves of Ava Gardner", "publication": "Vanity Fair", "date": "June 2020",
        "minutes": 17, "subject": "Ava Gardner",
        "description": "A fiercely independent movie star with legendary allure, tempestuous romances and a gift for turning the most improbable evenings into Hollywood folklore.",
        "url": "https://www.vanityfair.com/hollywood/2020/06/ava-gardner-biography-frank-sinatra",
    },
    {
        "title": "Mad, Bad, and Dangerous to Know: The Mythical Life of Errol Flynn", "publication": "Vanity Fair", "date": "April 2021",
        "minutes": 18, "subject": "Errol Flynn",
        "description": "A rakish screen legend who made his own life almost as wildly improbable as his swashbuckling films, leaving a trail of scandal and self-mythology.",
        "url": "https://www.vanityfair.com/hollywood/2021/04/errol-flynn-autobiography-wicked-wicked-ways",
    },
    {
        "title": "All That Glittered", "publication": "Vanity Fair", "date": "August 1998",
        "minutes": 28, "subject": "Charles de Beistegui",
        "description": "Inside the extravagant life of the Mexican-born host whose legendary 1951 Venice costume ball helped define a vanished world of European society.",
        "url": "https://www.vanityfair.com/magazine/1998/08/dunne199808",
    },
    {
        "title": "Bye Society", "publication": "Vanity Fair", "date": "April 1988",
        "minutes": 32, "subject": "Truman Capote",
        "description": "Truman Capote charms his way into the confidence of New York's most dazzling women, then loses the world he craved by putting its secrets into print.",
        "url": "https://www.vanityfair.com/news/1988/04/truman-capote-198804",
    },
    {
        "title": "Homicide at Rough Point", "publication": "Vanity Fair", "date": "July/August 2020",
        "minutes": 26, "subject": "Doris Duke",
        "description": "At a Newport mansion, one of America's richest and most formidable heiresses becomes embroiled in a death that refuses to fade from society's memory.",
        "url": "https://www.vanityfair.com/style/2020/07/did-doris-duke-get-away-with-murder",
    },
    {
        "title": "At Her Globe-Spanning Nightclubs, This Black Entertainer Hosted a 'Who's Who' of the 20th Century", "publication": "Smithsonian", "date": "2024",
        "minutes": 17, "subject": "Bricktop",
        "description": "Meet the magnetic singer and nightclub proprietor whose rooms from Paris to Rome drew writers, royalty, stars and a century of extraordinary conversations.",
        "url": "https://www.smithsonianmag.com/history/at-her-globe-spanning-nightclubs-this-black-entertainer-hosted-whos-whos-20th-century-180984224/",
    },
    {
        "title": "The Forbidden Love of Sammy Davis Jr. and Kim Novak", "publication": "Vanity Fair", "date": "March 1999",
        "minutes": 22, "subject": "Sammy Davis Jr.",
        "description": "Show-business charisma, Hollywood intrigue and a secret romance collide in a richly reported portrait of two stars under extraordinary pressure.",
        "url": "https://www.vanityfair.com/style/1999/03/sammy-davis-kim-novak-dating",
    },
    {
        "title": "African Dreamer", "publication": "Vanity Fair", "date": "November 1996",
        "minutes": 25, "subject": "Peter Beard",
        "description": "A vivid contemporary portrait of photographer and adventurer Peter Beard, living between the African wilderness, nightclub glamour, debt and magnificent recklessness.",
        "url": "https://archive.vanityfair.com/article/1996/11/african-dreamer",
    },
    {
        "title": "Robert Harrison's Scandalous Confidential Magazine", "publication": "Vanity Fair", "date": "April 2003",
        "minutes": 21, "subject": "Robert Harrison",
        "description": "The slick, cheerful scandal merchant who built a Hollywood gossip empire, made enemies of the biggest stars and helped invent the modern celebrity exposé.",
        "url": "https://www.vanityfair.com/hollywood/2003/04/robert-harrison-confidential-magazine",
    },
    {
        "title": "The Cult of Diana", "publication": "Vanity Fair", "date": "November 1993",
        "minutes": 20, "subject": "Diana Vreeland",
        "description": "The fabulously eccentric arbiter of taste whose wit, theatrical imagination and larger-than-life pronouncements created an enduring legend.",
        "url": "https://www.vanityfair.com/culture/1993/11/diana-vreeland-199311",
    },
    {
        "title": "The Rockefeller and the Ballet Boys", "publication": "Vanity Fair", "date": "February 1987",
        "minutes": 26, "subject": "George de Cuevas",
        "description": "The flamboyant ballet impresario and his fabulous social world, culminating in a spectacular Biarritz masked ball and extraordinary artistic intrigues.",
        "url": "https://www.vanityfair.com/magazine/1987/02/dunne198702",
    },
    {
        "title": "Anjelica Huston on Her Father, John Huston: 'He Was Extremely Well-Endowed'", "publication": "Vanity Fair", "date": "November 2013",
        "minutes": 14, "subject": "John Huston",
        "description": "Anjelica Huston remembers her swashbuckling filmmaker father, an audacious gambler and irresistible storyteller, and the extraordinary world of her Irish childhood.",
        "url": "https://www.vanityfair.com/hollywood/2013/11/anjelica-huston-father-memoir",
    },
    {
        "title": "The Struggle of John F. Kennedy Jr., American Prince", "publication": "Vanity Fair", "date": "July 2019",
        "minutes": 27, "subject": "John F. Kennedy Jr.",
        "description": "A revealing account of the charming, restless Kennedy heir, his magazine ambitions, complicated private life and the immense expectations of an American dynasty.",
        "url": "https://www.vanityfair.com/news/2019/07/inside-the-struggle-of-john-f-kennedy-jr-american-prince",
    },
    {
        "title": "Madame Claude and Her High-Profile Client List", "publication": "Vanity Fair", "date": "September 2014",
        "minutes": 20, "subject": "Madame Claude",
        "description": "A journey into the shadowy, high-society world of a Parisian fixer whose astonishing circle reportedly included politicians, tycoons and international playboys.",
        "url": "https://www.vanityfair.com/style/society/2014/09/madame-claude-paris-prostitution",
    },
    {
        "title": "The Heiress and the Hairdresser", "publication": "Vanity Fair", "date": "March 2001",
        "minutes": 25, "subject": "Libet Johnson",
        "description": "The irrepressible Johnson & Johnson heiress and her astonishing romantic life, extravagant parties and determination to do exactly as she pleased.",
        "url": "https://archive.vanityfair.com/article/2001/3/the-heiress-and-the-hairdresser",
    },
    {
        "title": "Private Camelot", "publication": "Vanity Fair", "date": "May 2004",
        "minutes": 28, "subject": "Jacqueline Kennedy",
        "description": "Behind the Kennedy White House's gleaming public image: Jackie's intimate dinners, cultural ambitions, private tensions and remarkable social world.",
        "url": "https://www.vanityfair.com/news/2004/05/jackie-kennedy-200405",
    },
    {
        "title": "The Last Onassis", "publication": "Vanity Fair", "date": "May 2005",
        "minutes": 25, "subject": "Athina Onassis",
        "description": "Inside the life of the reserved young heiress to an extraordinary shipping fortune and the turbulent family story behind the last Onassis name.",
        "url": "https://www.vanityfair.com/news/2005/05/athina200505",
    },
    {
        "title": "The Jockey and the Showman", "publication": "Vanity Fair", "date": "January 2009",
        "minutes": 23, "subject": "John Huston and the Paris art world",
        "description": "A richly anecdotal journey through a glamorous postwar circle of artists, collectors, gamblers, writers and Hollywood personalities in Paris.",
        "url": "https://www.vanityfair.com/news/2009/01/pearson200901",
    },
]


def canonical_url(value):
    try:
        p = urlsplit(str(value).strip())
        if p.scheme.lower() != "https" or not p.hostname:
            return ""
        path = re.sub(r"/+", "/", p.path).rstrip("/")
        return urlunsplit(("https", p.hostname.lower().removeprefix("www."), path, "", ""))
    except (ValueError, TypeError):
        return ""


def tidy(text):
    s = unicodedata.normalize("NFKD", str(text).casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def known_person(article):
    if article.get("subject"):
        return tidy(article["subject"])
    body = tidy(" ".join(str(article.get(k, "")) for k in ("title", "description")))
    aliases = {
        "gianni agnelli": ("agnelli",),
        "porfirio rubirosa": ("rubirosa",),
        "aristotle onassis": ("onassis", "christina o"),
        "gunter sachs": ("gunter sachs", "potemkin playboys"),
        "lady diana cooper": ("diana cooper",),
        "lee radziwill": ("a delicate balance", "lee radziwill"),
    }
    for person, keys in aliases.items():
        if any(x in body for x in keys):
            return person
    return ""


def from_api(key, previous_titles):
    """One short discovery attempt; an empty result is expected occasionally."""
    prompt = (
        "Search the web for 6 real, directly linked, substantial magazine or archival "
        "articles profiling people with extraordinary CHARISMA, swagger, outrageous "
        "adventures, irresistibly unconventional lives or magnetic personalities. "
        "We want the spirit of Peter Beard, Steve McQueen, Truman Capote, Ava Gardner, "
        "Kennedy family, daredevil explorers, colourful rogues and high-society "
        "eccentrics. Discover *different* people, not those same examples. "
        "Prioritise good storytelling and original magazine sources such as "
        "Vanity Fair, Esquire, Smithsonian, The New Yorker, and Tatler. "
        "Avoid news, fashion/shopping lists, corporate biographies and generic luxury. "
        "Use authentic article titles, accurate dates or 'Date not stated', short vivid "
        "descriptions and HTTPS links. Do not invent links or titles. "
        "Do not repeat these published article titles: "
        + json.dumps(previous_titles[-35:], ensure_ascii=False)
        + ". Return JSON of the requested shape; fewer than six if necessary."
    )
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
        "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        "input": prompt,
        "tools": [{"type": "web_search", "search_context_size": "medium"}],
        "reasoning": {"effort": "low"},
        "max_output_tokens": 6000,
        "text": {"format": {
            "type": "json_schema", "name": "reading_edit_discovery", "strict": True,
            "schema": {"type": "object", "properties": {"articles": {
                "type": "array", "items": {"type": "object", "properties": fields,
                "required": list(fields), "additionalProperties": False}}},
                "required": ["articles"], "additionalProperties": False},
        }},
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=200) as r:
        response = json.load(r)
    content = "".join(
        c.get("text", "") for m in response.get("output", [])
        if m.get("type") == "message" for c in m.get("content", [])
        if c.get("type") == "output_text"
    ).strip()
    print("Research:", response.get("status"),
          "web_search calls", sum(1 for x in response.get("output", [])
                                 if x.get("type") == "web_search_call"),
          "output tokens", response.get("usage", {}).get("output_tokens"), flush=True)
    if not content:
        print("::warning::OpenAI provided no readable output; reserve will be used", flush=True)
        return []
    try:
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", content))
        return data.get("articles", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, TypeError):
        print("::warning::OpenAI response was not valid JSON; reserve will be used", flush=True)
        return []


def check_discovery_url(url):
    """Check new model-proposed links live, unlike the human-vetted archive bank.

    Returns False on 404 or bot blocks. A 403 can be a legitimate publisher
    bot restriction, but don't publish an unverified AI suggestion in that case.
    """
    if not canonical_url(url):
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return 200 <= r.status < 300 and "html" in r.headers.get("Content-Type", "text/html")
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return False


def valid_new(article, existing, chosen, *, reserve=False):
    if not isinstance(article, dict) or not all(article.get(k) for k in
        ("title", "publication", "date", "description", "url", "subject")):
        return False
    uri, title = canonical_url(article["url"]), tidy(article["title"])
    if not uri or not title:
        return False
    compare = list(existing) + list(chosen)
    if any(canonical_url(old.get("url")) == uri for old in compare):
        return False
    if any(SequenceMatcher(None, title, tidy(old.get("title", ""))).ratio() >= 0.88
           for old in compare):
        return False
    person = tidy(article["subject"])
    if person and person in {known_person(x) for x in compare[-10:]}:
        return False
    # For human-researched reserve articles, the URLs have already been
    # inspected in publisher/archive listings. Publishers can return 403 to
    # GitHub runners while the article page remains accessible to readers.
    if not reserve and not check_discovery_url(article["url"]):
        return False
    return True


def append_article(source, n):
    try:
        minutes = max(2, min(90, int(source["minutes"])))
    except (KeyError, ValueError, TypeError):
        minutes = 15
    return {
        "id": f"daily-{TODAY.replace('-', '')}-{n}",
        "title": str(source["title"]).strip(),
        "publication": str(source["publication"]).strip(),
        "date": str(source["date"]).strip(),
        "minutes": minutes,
        "description": str(source["description"]).strip(),
        "url": str(source["url"]).strip(),
        "subject": str(source["subject"]).strip(),
        "added_on": TODAY,
    }


def main():
    # Two UTC cron triggers cover UK daylight-savings clock changes. Don't
    # block a delayed runner; a date-tagged edition prevents repeats.
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and NOW.hour < 8:
        print("Before 08:00 Europe/London; skipping", flush=True)
        return

    existing = json.loads(FEED.read_text(encoding="utf-8"))
    if not isinstance(existing, list) or not all(isinstance(x, dict) for x in existing):
        raise ValueError("articles.json must contain an array of article objects")
    if any(x.get("added_on") == TODAY for x in existing):
        print("Already published an edition today; skipping", flush=True)
        return
    selected = []
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        try:
            suggestions = from_api(api_key, [x.get("title", "") for x in existing])
        except (urllib.error.URLError, ValueError, TimeoutError, KeyError) as exc:
            print("::warning::OpenAI discovery unavailable:", type(exc).__name__, flush=True)
            suggestions = []
        print("API suggested", len(suggestions), "articles", flush=True)
        for article in suggestions:
            if valid_new(article, existing, selected):
                selected.append(append_article(article, len(selected) + 1))
                print("ACCEPT API:", article["title"], flush=True)
                if len(selected) == 2:
                    break
    else:
        print("::warning::Missing API key: publishing researched reserve only", flush=True)

    # Always fill from independently researched archival pieces if the model's
    # discovery is thin. 3 articles is the daily target; no weak padding.
    for article in EDITORIAL_RESERVE:
        if len(selected) >= 3:
            break
        if valid_new(article, existing, selected, reserve=True):
            selected.append(append_article(article, len(selected) + 1))
            print("ACCEPT RESERVE:", article["title"], flush=True)
    if not selected:
        # Protect library rather than silently claiming a new edition appeared.
        raise RuntimeError("No new verified articles available; curated reserve exhausted and no new model-suggested links passed validation. Existing library untouched.")

    # No read/saved/favourite status is stored in this file. The app's local
    # selections remain on the user's phone. Append only; don't rewrite old IDs.
    FEED.write_text(json.dumps(existing + selected, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print("PUBLISHED", len(selected), "articles; total", len(existing) + len(selected), flush=True)
    print("Reserve items remaining:", sum(valid_new(item, existing, selected, reserve=True)
                                           for item in EDITORIAL_RESERVE), flush=True)


if __name__ == "__main__":
    main()
