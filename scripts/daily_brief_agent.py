#!/usr/bin/env python3
"""
MoneyTailors Daily Market Brief Agent (v2)
==========================================
Pipeline:
  1. Fetch news headlines from BBC Business, Reuters, Arabian Business RSS
  2. Fetch live snapshot data: CoinGecko (crypto), TradingView-comparable feeds
  3. Group news into asset class buckets (Forex, Crypto, Stocks, Commodities, GCC/Tadawul, PSX)
  4. Generate a "Market Today" digest with Claude Haiku — every section CITES a real source
  5. Generate hero image via Pollinations AI (gold/navy brand style)
  6. Commit article + image to GitHub repo → Cloudflare Pages auto-deploys
  7. Send the same article to Brevo newsletter subscribers

Runs daily at 12:00 UTC via GitHub Actions cron.

Required GitHub Actions secrets:
  ANTHROPIC_API_KEY  — Anthropic API key
  BREVO_API_KEY      — Brevo (Sendinblue) API key  [optional — skip email if absent]
  BREVO_LIST_ID      — Brevo subscriber list ID    [optional]
  GITHUB_TOKEN       — auto-provided
"""

import os, json, re, base64, sys, html
from datetime import datetime, timezone
import requests

# ─── Environment ────────────────────────────────────────────────────────────
GITHUB_TOKEN  = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO   = os.environ.get('GITHUB_REPO', '')
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
BREVO_KEY     = os.environ.get('BREVO_API_KEY', '')
BREVO_LIST_ID = os.environ.get('BREVO_LIST_ID', '')
SITE_URL      = os.environ.get('SITE_URL', 'https://www.moneytailors.com')
DRY_RUN       = os.environ.get('DRY_RUN', '').lower() == 'true'

GITHUB_API = 'https://api.github.com'
GH_HEADERS = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json',
}

# ─── Asset class keyword buckets ─────────────────────────────────────────────
BUCKETS = {
    'forex':       ['forex','currency','dollar','euro','pound','yen','exchange rate','FX','rupee','riyal','dirham','peso','yuan'],
    'crypto':      ['bitcoin','ethereum','crypto','blockchain','BTC','ETH','altcoin','defi','token','coinbase','binance'],
    'stocks':      ['stock','equity','nasdaq','S&P','NYSE','shares','apple','microsoft','tesla','nvidia','wall street','earnings'],
    'commodities': ['gold','silver','oil','crude','brent','WTI','copper','natural gas','commodity','OPEC','barrel'],
    'tadawul':     ['tadawul','saudi','TASI','aramco','SABIC','GCC','riyadh','vision 2030','UAE','dubai','abu dhabi'],
    'psx':         ['pakistan stock exchange','PSX:','KSE-100','KSE 100','pakistan','karachi','SBP','islamabad stock'],
    'macro':       ['fed','federal reserve','inflation','recession','GDP','interest rate','central bank','jobs','employment','CPI','PMI'],
}

# ─── Step 1: Fetch news headlines ────────────────────────────────────────────
# Source list verified working 2026-06-21 by testing each feed live through
# the exact rss2json call this script makes. Reuters and Arabian Business
# (the previous list) were both dead and have been removed. The `count`
# parameter that was previously appended to every request errors out on
# rss2json's free tier without a paid API key — every single fetch was
# silently failing because of it. Removed below; default item count is used
# instead (rss2json's free default, no parameter needed).
RSS_FEEDS = [
    # General / macro
    ('BBC Business',              'https://feeds.bbci.co.uk/news/business/rss.xml'),
    ('BBC World',                 'https://feeds.bbci.co.uk/news/world/rss.xml'),
    ('Yahoo Finance',             'https://finance.yahoo.com/news/rssindex'),
    # US markets / stocks
    ('MarketWatch Top Stories',   'https://feeds.content.dowjones.io/public/rss/mw_topstories'),
    ('MarketWatch Market Pulse',  'https://feeds.content.dowjones.io/public/rss/mw_marketpulse'),
    ('CNBC Business',             'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147'),
    ('CNBC Markets',              'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258'),
    ('Seeking Alpha',             'https://seekingalpha.com/market_currents.xml'),
    ('Insider Monkey',            'http://feeds.feedburner.com/insidermonkey'),
    # Commodities
    ('OilPrice.com',              'https://oilprice.com/rss/main'),
    # GCC / Tadawul-specific
    ('AGBI',                      'https://www.agbi.com/feed/'),
    # Crypto/breaking-news flavored — included for breadth, but the prompt
    # below explicitly instructs the model NOT to over-weight this source
    # for tone, since its content style leans retail/explainer rather than
    # analytical (e.g. "How much would $1,000 in X be worth today").
    ('Watcher Guru',              'https://watcher.guru/feed/'),
]

# Separate: not a news feed, a forward-looking economic calendar. Used only
# to populate the "What to Watch" / upcoming-events section, never bucketed
# alongside headlines.
ECONOMIC_CALENDAR_FEED = ('MyFXBook Economic Calendar', 'https://www.myfxbook.com/rss/forex-economic-calendar-events')

def fetch_all_headlines():
    """Fetch all headlines from RSS feeds. Returns list of {title, link, source, pubdate}."""
    all_items = []
    for source, feed_url in RSS_FEEDS:
        try:
            api_url = f'https://api.rss2json.com/v1/api.json?rss_url={requests.utils.quote(feed_url)}'
            resp = requests.get(api_url, timeout=15)
            if resp.status_code != 200:
                print(f'RSS HTTP error ({source}): {resp.status_code}')
                continue
            data = resp.json()
            if data.get('status') != 'ok':
                print(f'RSS API error ({source}): {data.get("message", "unknown")}')
                continue
            for item in data.get('items', [])[:20]:
                all_items.append({
                    'title':   (item.get('title') or '').strip(),
                    'link':    item.get('link', ''),
                    'source':  source,
                    'pubdate': item.get('pubDate', ''),
                    'snippet': (item.get('description') or '')[:300],
                })
        except Exception as e:
            print(f'RSS error ({source}): {e}')
    print(f'Total headlines fetched: {len(all_items)}')
    return all_items

def fetch_economic_calendar():
    """Fetch upcoming economic calendar events for the 'What to Watch' section.
    Separate from fetch_all_headlines() since this is calendar data, not news."""
    source, feed_url = ECONOMIC_CALENDAR_FEED
    try:
        api_url = f'https://api.rss2json.com/v1/api.json?rss_url={requests.utils.quote(feed_url)}'
        resp = requests.get(api_url, timeout=15)
        if resp.status_code != 200:
            print(f'Calendar fetch HTTP error: {resp.status_code}')
            return []
        data = resp.json()
        if data.get('status') != 'ok':
            print(f'Calendar fetch API error: {data.get("message", "unknown")}')
            return []
        return [{
            'title':   (item.get('title') or '').strip(),
            'pubdate': item.get('pubDate', ''),
        } for item in data.get('items', [])[:10]]
    except Exception as e:
        print(f'Calendar fetch error: {e}')
        return []

# ─── Step 2: Bucket headlines by asset class ─────────────────────────────────
def bucket_headlines(headlines):
    """Group headlines by asset class bucket. Each headline can go in multiple buckets."""
    buckets = {k: [] for k in BUCKETS}
    for h in headlines:
        text = (h['title'] + ' ' + h['snippet']).lower()
        for bucket_name, keywords in BUCKETS.items():
            if any(kw.lower() in text for kw in keywords):
                if h not in buckets[bucket_name]:
                    buckets[bucket_name].append(h)
    # Limit to top 3 per bucket
    return {k: v[:3] for k, v in buckets.items() if v}

# ─── Step 3: Fetch live market snapshot ─────────────────────────────────────
def fetch_market_snapshot():
    """Fetch quick price snapshot for the brief. Crypto via CoinGecko (free)."""
    snapshot = {}
    try:
        ids = 'bitcoin,ethereum,solana,binancecoin'
        url = f'https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true'
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            snapshot['crypto'] = {
                'BTC':  data.get('bitcoin',    {}),
                'ETH':  data.get('ethereum',   {}),
                'SOL':  data.get('solana',     {}),
                'BNB':  data.get('binancecoin',{}),
            }
    except Exception as e:
        print(f'CoinGecko snapshot error: {e}')
    return snapshot

# ─── Step 4: Generate digest article via Claude ─────────────────────────────
def generate_digest(buckets, snapshot, calendar_events=None):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    # Build a clean source list for the prompt
    sections_text = []
    for bucket_name in ['forex','crypto','stocks','commodities','tadawul','psx','macro']:
        if bucket_name not in buckets:
            continue
        section_lines = [f'\n## {bucket_name.upper()} HEADLINES (verified sources):']
        for h in buckets[bucket_name]:
            section_lines.append(f'  • [{h["source"]}] {h["title"]} — {h["link"]}')
        sections_text.append('\n'.join(section_lines))

    sources_block = '\n'.join(sections_text)

    snapshot_block = ''
    if snapshot.get('crypto'):
        snapshot_block = '\n\nLIVE CRYPTO SNAPSHOT (from CoinGecko, use these exact figures):\n'
        for sym, d in snapshot['crypto'].items():
            if d.get('usd'):
                chg = d.get('usd_24h_change')
                snapshot_block += f'  • {sym}: ${d["usd"]:,.2f}'
                if chg is not None:
                    snapshot_block += f' ({chg:+.2f}% 24h)'
                snapshot_block += '\n'

    today_str = datetime.now(timezone.utc).strftime('%A, %d %B %Y')
    calendar_block = ''
    if calendar_events:
        calendar_block = '\nUPCOMING ECONOMIC CALENDAR EVENTS (verified, use these for "What to Watch"):\n'
        for ev in calendar_events[:6]:
            calendar_block += f'  • {ev["title"]} ({ev["pubdate"]})\n'

    prompt = f"""You are the editor of MoneyTailors Daily Market Brief, a finance newsletter covering Forex, Crypto, Stocks, Commodities, GCC/Tadawul, and PSX.

TODAY: {today_str}

You will write the daily market brief based ONLY on these verified headlines from authoritative news sources. You MUST NOT invent any facts, prices, or events not present in these sources. If you don't have a verified source for a claim, omit that claim.

VERIFIED HEADLINES BY ASSET CLASS:
{sources_block}
{snapshot_block}
{calendar_block}

SOURCE BALANCE: the headlines above come from multiple outlets covering different asset classes. Distribute coverage across however many asset-class buckets actually have verified data today, rather than over-weighting whichever bucket happens to have the most headlines. One outlet (Watcher Guru) tends to run retail-explainer style crypto content; if you draw from it, keep the SAME analytical, professional tone as the rest of the brief, don't let its style bleed in.

OUTPUT FORMAT (read carefully, this controls what gets published):

Your response has exactly two parts, in this order:

PART 1: An HTML article body. Plain HTML only, no markdown, no <html>/<head>/<body> wrapper tags, no section labels, no meta-commentary about what you're about to write. The article must START with its actual opening paragraph, not with a label like "Headline:" or "Hook Headline:" or any other caption-like prefix. Output ONLY the words a reader would actually see in the published article.

The article body itself must contain:
   - One opening paragraph (50-80 words) summarising the day. This paragraph itself doubles as your "hook" — make it specific (name 1-2 assets that moved most, include a price level or % move if available, hint at the macro driver) but write it as a normal opening paragraph, never as a labeled headline line.
   - Then 4-6 H2 sections, ONE per asset class that has verified headlines (skip any bucket with no source data)
   - Each H2 section: 2-3 sentences, with the source cited as a hyperlink: <a href="URL" target="_blank" rel="noopener noreferrer">source name</a>
   - One closing H2 "What to Watch" with 2-3 bullets for upcoming events, drawn from the economic calendar data above if present, otherwise only from events explicitly mentioned in source headlines
   - Total length: 600-900 words

PART 2: A JSON block, in EXACTLY this format, with NO markdown fences around it:
---JSON---
{{"title":"A 60-90 character SEO headline naming 1-2 specific assets and a price/% move if available, e.g. Gold Tests $2,420 as Fed Pivot Bets Build; Tadawul Closes Higher on Aramco","excerpt":"160-char-max one-sentence summary of the brief","category":"Market Brief","image_prompt":"15-word concise visual description for AI image, gold and navy financial dashboard style"}}
---END---

The "title" field in this JSON is the ONLY place the headline text belongs. Do not also write it, or any variant of it, as a line inside the article body.

FACT DISCIPLINE (critical):
   - Every numerical claim (price, %, levels) must come from the provided headlines, calendar, or live snapshot
   - Do NOT invent earnings figures, central bank decisions, or geopolitical events
   - If a section's headlines are vague, write a shorter, qualitative section rather than fabricating specifics
   - When in doubt, omit

STYLE:
   - Tone: analytical, professional, calm, no hype words ("explodes", "skyrockets", "moons")
   - Never use " — " (em-dash with spaces). Use comma or colon instead.
   - Active voice, present tense for current state
   - Each asset section linked to at least one source
   - Never write internal instruction labels (like "Hook Headline", "Structure", "Part 1") as literal text anywhere in your output"""

    response = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=3000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = response.content[0].text.strip()

    # Parse
    if '---JSON---' in raw and '---END---' in raw:
        html_part = raw.split('---JSON---')[0].strip()
        json_str  = raw.split('---JSON---')[1].split('---END---')[0].strip()
        try:
            meta = json.loads(json_str)
        except json.JSONDecodeError:
            meta = {}
    else:
        html_part = raw
        meta = {}

    title    = meta.get('title', f'Daily Market Brief — {today_str}').strip('"\'')
    excerpt  = meta.get('excerpt', f'Daily market analysis covering Forex, Crypto, Stocks, Commodities, Tadawul, and PSX for {today_str}.')[:200]
    category = 'Market Brief'
    img_hint = meta.get('image_prompt', 'gold navy financial dashboard ticker, dark professional')

    print(f'Brief generated: "{title}" ({len(html_part)} chars)')
    return html_part, title, excerpt, category, img_hint

# ─── Step 5: Image generation ───────────────────────────────────────────────
def generate_image(img_hint):
    style = 'dark financial Bloomberg terminal aesthetic, gold and navy accents, professional widescreen banner, no text, no letters, no logos'
    full_prompt = f'{img_hint}, {style}'
    encoded = requests.utils.quote(full_prompt)
    url = f'https://image.pollinations.ai/prompt/{encoded}?width=1200&height=630&model=flux&nologo=true&seed={abs(hash(img_hint)) % 9999}'
    print('Generating image from Pollinations AI...')
    try:
        resp = requests.get(url, timeout=90)
        if resp.status_code == 200 and 'image' in resp.headers.get('Content-Type',''):
            print(f'Image OK: {len(resp.content)} bytes')
            return resp.content
    except Exception as e:
        print(f'Image generation error: {e}')
    return None

# ─── Step 6: GitHub publish ─────────────────────────────────────────────────
def gh_get(path):
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    resp = requests.get(url, headers=GH_HEADERS)
    if resp.status_code == 200:
        data = resp.json()
        content = base64.b64decode(data['content'].replace('\n','')).decode('utf-8')
        return content, data['sha']
    return None, None

def gh_put(path, content_bytes, sha, commit_msg):
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}'
    payload = {
        'message': commit_msg,
        'content': base64.b64encode(content_bytes).decode('utf-8'),
    }
    if sha: payload['sha'] = sha
    resp = requests.put(url, headers=GH_HEADERS, json=payload)
    if resp.status_code not in (200, 201):
        print(f'gh_put error {resp.status_code}: {resp.text[:300]}')
        return False
    return True

def publish_to_site(html_content, title, excerpt, category, img_bytes, slug):
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # Upload image
    img_path = f'images/blog/{slug}.jpg'
    img_ok = False
    if img_bytes and not DRY_RUN:
        img_ok = gh_put(img_path, img_bytes, None, f'image: add {slug}.jpg')

    img_html = (
        f'<img src="/{img_path}" alt="{html.escape(title)}" '
        f'style="width:100%;border-radius:8px;margin-bottom:28px;display:block">'
    ) if img_ok else ''

    full_html = img_html + '\n' + html_content

    # Append to posts.json
    posts_raw, posts_sha = gh_get('content/posts.json')
    posts = json.loads(posts_raw) if posts_raw else []

    existing = {p.get('slug','') for p in posts}
    if slug in existing:
        print(f'Slug {slug} already exists — aborting')
        return False

    new_post = {
        'slug':     slug,
        'title':    title,
        'date':     today,
        'category': category,
        'excerpt':  excerpt,
        'image':    f'/{img_path}' if img_ok else '',
        'content':  full_html,
        'auto':     True,
        'daily':    True,
    }

    if DRY_RUN:
        print('DRY RUN — would publish:')
        preview = new_post.copy()
        preview['content'] = preview['content'][:240] + '...'
        print(json.dumps(preview, indent=2))
        return True

    posts.insert(0, new_post)
    posts_bytes = json.dumps(posts, indent=2, ensure_ascii=False).encode('utf-8')
    ok = gh_put('content/posts.json', posts_bytes, posts_sha, f'brief: {title}')
    return ok

# ─── Step 7: Send via Brevo ─────────────────────────────────────────────────
def send_newsletter_via_brevo(title, html_content, slug, excerpt):
    if not BREVO_KEY or not BREVO_LIST_ID:
        print('Brevo not configured (BREVO_API_KEY or BREVO_LIST_ID missing) — skipping email send')
        return False
    if DRY_RUN:
        print('DRY RUN — skipping Brevo send')
        return True

    post_url = f'{SITE_URL}/post.html?slug={slug}'

    # Wrap the content in a basic responsive email template
    email_html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{html.escape(title)}</title></head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:Inter,Arial,sans-serif;color:#1B3A5C">
<div style="max-width:640px;margin:0 auto;background:#ffffff">
  <div style="background:#070A0D;padding:24px;text-align:center">
    <div style="color:#D4A85A;font-family:'Space Grotesk',Arial,sans-serif;font-weight:700;font-size:22px;letter-spacing:-0.3px">Money<span style="color:#E8DCC4">Tailors</span> Daily Brief</div>
    <div style="color:#7A9BB5;font-size:11px;letter-spacing:1.5px;margin-top:6px">{datetime.now(timezone.utc).strftime('%A, %d %B %Y')}</div>
  </div>
  <div style="padding:32px 28px">
    <h1 style="font-family:'Space Grotesk',Arial,sans-serif;font-size:26px;font-weight:700;color:#1B3A5C;line-height:1.2;margin:0 0 14px">{html.escape(title)}</h1>
    <p style="font-size:14px;color:#666;line-height:1.6;margin:0 0 24px">{html.escape(excerpt)}</p>
    <div style="font-size:15px;line-height:1.75;color:#333">
      {html_content}
    </div>
    <div style="margin-top:36px;padding-top:24px;border-top:1px solid #eee;text-align:center">
      <a href="{post_url}" style="display:inline-block;background:#D4A85A;color:#070A0D;text-decoration:none;padding:12px 28px;border-radius:6px;font-weight:600;font-size:14px">Read on MoneyTailors →</a>
    </div>
  </div>
  <div style="background:#f5f5f0;padding:20px;text-align:center;font-size:11px;color:#888">
    You're receiving this because you subscribed to the MoneyTailors Daily Brief.<br>
    <a href="{{{{ unsubscribe }}}}" style="color:#888">Unsubscribe</a> &nbsp;·&nbsp; <a href="{SITE_URL}" style="color:#888">MoneyTailors.com</a><br><br>
    Not financial advice. Markets are risky. Please do your own research.
  </div>
</div>
</body></html>"""

    payload = {
        'sender': {'name': 'MoneyTailors Daily Brief', 'email': 'brief@moneytailors.com'},
        'subject': title,
        'htmlContent': email_html,
        'messageVersions': [],
        'listIds': [int(BREVO_LIST_ID)],
    }

    try:
        resp = requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={'accept': 'application/json', 'api-key': BREVO_KEY, 'content-type': 'application/json'},
            json=payload,
            timeout=30
        )
        if resp.status_code in (200, 201):
            print(f'Brevo send OK: {resp.json()}')
            return True
        else:
            print(f'Brevo send failed {resp.status_code}: {resp.text[:300]}')
    except Exception as e:
        print(f'Brevo error: {e}')
    return False

# ─── Helpers ─────────────────────────────────────────────────────────────────
def slugify(title):
    s = title.lower()
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'\s+', '-', s.strip())
    s = re.sub(r'-+', '-', s)
    date_prefix = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return f'{date_prefix}-daily-brief-{s[:40]}'.rstrip('-')

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print('=' * 60)
    print('MoneyTailors Daily Market Brief Agent')
    print(f'Repo : {GITHUB_REPO}')
    print(f'UTC  : {datetime.now(timezone.utc).isoformat()}')
    print(f'DRY  : {DRY_RUN}')
    print('=' * 60)

    if not ANTHROPIC_KEY:
        print('ERROR: ANTHROPIC_API_KEY not set')
        sys.exit(1)
    if not GITHUB_TOKEN:
        print('ERROR: GITHUB_TOKEN not set')
        sys.exit(1)

    # Step 1: Fetch all headlines
    headlines = fetch_all_headlines()
    if not headlines:
        print('No headlines fetched — aborting')
        sys.exit(1)

    # Step 2: Bucket
    buckets = bucket_headlines(headlines)
    print(f'Buckets with data: {list(buckets.keys())}')

    if len(buckets) < 2:
        print('Not enough asset coverage today — running anyway with what we have')

    # Step 3: Market snapshot
    snapshot = fetch_market_snapshot()

    # Step 3b: Economic calendar (for "What to Watch" section)
    calendar_events = fetch_economic_calendar()
    print(f'Calendar events fetched: {len(calendar_events)}')

    # Step 4: Generate digest
    html_content, title, excerpt, category, img_hint = generate_digest(buckets, snapshot, calendar_events)
    slug = slugify(title)

    # Step 5: Image
    img_bytes = generate_image(img_hint)

    # Step 6: Publish to site
    published = publish_to_site(html_content, title, excerpt, category, img_bytes, slug)
    print(f'Site publish: {"OK" if published else "FAILED"}')

    # Step 7: Newsletter
    if published:
        emailed = send_newsletter_via_brevo(title, html_content, slug, excerpt)
        print(f'Newsletter send: {"OK" if emailed else "SKIPPED/FAILED"}')

    print('=' * 60)
    print(f'Run complete. Article: {title}')
    sys.exit(0 if published else 1)

if __name__ == '__main__':
    main()
