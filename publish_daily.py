"""Daily editorial selection for The Reading Edit. Requires OPENAI_API_KEY."""
import json, os, re, sys, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
FEED = ROOT / 'articles.json'
TODAY = datetime.now(ZoneInfo('Europe/London'))


def get_json(url, payload, token):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
        'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}, method='POST')
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def reachable(url):
    if not url.startswith('https://'):
        return False
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 ReadingEdit/1.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200 and 'text/html' in r.headers.get('Content-Type','text/html')
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def main():
    # Workflow runs twice daily in UTC to account for UK daylight savings.
    if os.getenv('GITHUB_EVENT_NAME') == 'schedule' and TODAY.hour != 8:
        print('Not 08:00 London time; skipping')
        return
    existing = json.loads(FEED.read_text())
    if not isinstance(existing, list):
        raise ValueError('articles.json must contain an array')
    known = {a.get('url','').rstrip('/').lower() for a in existing}
    published_today = [a for a in existing if a.get('added_on') == TODAY.date().isoformat()]
    if published_today:
        print('Already published today; skipping')
        return
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        raise RuntimeError('OPENAI_API_KEY GitHub Actions secret is missing')
    prompt = f'''Today is {TODAY.date().isoformat()}. You are the exceptionally discerning editor of The Reading Edit, a private reading collection. Use web search to find 3–5 REAL, existing, directly linked outstanding LONG-FORM articles. Core subjects: Gianni Agnelli, Aristotle Onassis, Gunter Sachs, Porfirio Rubirosa, Aly Khan, European jet set, colourful aristocrats, extraordinary adventurers, vanished high society, great dynasties and scandals. Prioritise superb narrative and genuinely fascinating lives, especially outstanding Vanity Fair archives, The Oldie, The Spectator, Gentleman's Journal and other excellent magazines. Exclude modern hospitality founders, generic luxury, product reviews, fashion, routine politics, promotional pieces, or flimsy biographies. Better to return 1 truly superb article than 5 mediocre ones. NEVER fabricate article titles, URLs, dates or details. Open or verify each article using search before including. Exclude these already recommended URLs: {json.dumps(sorted(known))}. Return ONLY a JSON array, each item with title, publication, date, minutes (estimated integer), description (1–2 vivid accurate sentences), url (direct HTTPS article URL). No markdown. If none meet the bar return [].'''
    payload = {'model': os.getenv('OPENAI_MODEL','gpt-5-mini'), 'tools':[{'type':'web_search'}],
               'input': prompt, 'max_output_tokens': 2500}
    response = get_json('https://api.openai.com/v1/responses', payload, key)
    text = ''.join(x.get('text','') for item in response.get('output',[])
                   if item.get('type') == 'message' for x in item.get('content',[])
                   if x.get('type') == 'output_text').strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text).strip()
    candidates = json.loads(text)
    if not isinstance(candidates, list):
        raise ValueError('Expected JSON list')
    additions = []
    for a in candidates[:5]:
        if not isinstance(a,dict) or not all(a.get(k) for k in ('title','publication','date','description','url')):
            continue
        url = a['url'].strip()
        if url.rstrip('/').lower() in known or not reachable(url):
            print('Skipping duplicate/unreachable:', url)
            continue
        item = {k:a[k] for k in ('title','publication','date','description','url')}
        try: item['minutes'] = max(1,min(90,int(a.get('minutes',10))))
        except (ValueError,TypeError): item['minutes'] = 10
        item['id'] = 'daily-' + TODAY.strftime('%Y%m%d') + '-' + str(len(additions)+1)
        item['added_on'] = TODAY.date().isoformat()
        additions.append(item)
        known.add(url.rstrip('/').lower())
    if not additions:
        print('No verified reachable new articles today; retaining existing feed')
        return
    # Keep all older entries to protect users' saved/read/favourite links.
    FEED.write_text(json.dumps(existing+additions,ensure_ascii=False,indent=2)+'\n')
    print('Published',len(additions),'new articles')

if __name__ == '__main__':
    main()
