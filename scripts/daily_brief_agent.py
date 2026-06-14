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
    'psx':         ['PSX','pakistan','KSE','karachi','rupee','SBP','IMF','islamabad'],
    'macro':       ['fed','federal reserve','inflation','recession','GDP','interest rate','central bank','jobs','employment','CPI','PMI'],
}

# ─── Step 1: Fetch news headlines via Marketaux ─────────────────────────────
MARKETAUX_KEY = 'HgY1A0J8SrEJEtsoneEtatoydKqQI7RR5gseJZHo'

def fetch_all_headlines():
    """Fetch financial headlines from Marketaux API (no IP restrictions, reliable)."""
    all_items = []
    try:
        params = {
            'language': 'en',
            'filter_entities': 'true',
            'limit': '50',
            'api_token': MARKETAUX_KEY
        }
        resp = requests.get('https://api.marketaux.com/v1/news/all', params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get('data', []):
                if not item.get('title') or not item.get('url'):
                    continue
                import re as _re
                src = _re.sub(r'\.(com|net|org|co|io).*$', '', item.get('source', 'News'), flags=_re.I)
                all_items.append({
                    'title':   item['title'].strip(),
                    'link':    item['url'],
                    'source':  src or 'News',
                    'pubdate': item.get('published_at', ''),
                    'snippet': (item.get('description') or item.get('snippet') or '')[:300],
                })
        else:
            print(f'Marketaux error {resp.status_code}: {resp.text[:200]}')
    except Exception as e:
        print(f'Marketaux fetch error: {e}')
    print(f'Total headlines fetched: {len(all_items)}')
    return all_items

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
def generate_digest(buckets, snapshot):
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

    # If we have very few bucketed headlines, pass ALL headlines as general market news
    total_bucketed = sum(len(v) for v in buckets.values())

    if total_bucketed < 3:
        general_block = '\n## GENERAL MARKET & FINANCIAL NEWS (write sections based on topics covered):\n'
        try:
            params = {'language': 'en', 'filter_entities': 'true', 'limit': '30', 'api_token': MARKETAUX_KEY}
            resp = requests.get('https://api.marketaux.com/v1/news/all', params=params, timeout=15)
            if resp.status_code == 200:
                for item in resp.json().get('data', [])[:20]:
                    if item.get('title') and item.get('url'):
                        general_block += f'  • {item["title"]} — {item["url"]}\n'
            if len(general_block) > 100:
                sources_block = general_block
        except Exception:
            pass

    prompt = f"""You are the editor of MoneyTailors Daily Market Brief — a finance newsletter covering markets globally.

TODAY: {today_str}

Write the daily market brief using the headlines and data provided below. Cover whatever topics are represented in the headlines. Use the crypto snapshot for exact crypto prices.

AVAILABLE NEWS HEADLINES:
{sources_block}
{snapshot_block}

INSTRUCTIONS:

1. HOOK HEADLINE: Write one SEO headline (60-90 chars) naming specific assets/events from the headlines above. Use actual prices from the snapshot where relevant.

2. ARTICLE BODY (HTML only, no html/head/body tags):
   - Opening paragraph: 50-80 words summarising today's market environment
   - 3-5 H2 sections covering the topics in the headlines (crypto, stocks, commodities, forex, macro — whatever is covered)
   - For crypto: use the exact prices from the snapshot above
   - Each section: 2-4 sentences. Link to at least one source per section using: <a href="URL">Source Name</a>
   - Total: 400-700 words

3. STRICT RULES:
   - Only use facts from the provided headlines and snapshot
   - Do not invent prices, events, or central bank decisions not mentioned above
   - If a topic has no headlines, skip it entirely
   - Never use em-dash with spaces. Use commas or colons instead.

After the article, output this JSON block exactly:
---JSON---
{{"title":"hook headline here","excerpt":"one sentence summary under 160 chars","category":"Market Brief","image_prompt":"15-word image description for gold navy financial dashboard"}}
---END---"""

    response = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=3000,
        messages=[
            {'role': 'user', 'content': prompt},
            {'role': 'assistant', 'content': '<h2>'}
        ]
    )

    raw = '<h2>' + response.content[0].text.strip()

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
        print('Brevo not configured — skipping email send')
        return False
    if DRY_RUN:
        print('DRY RUN — skipping Brevo send')
        return True

    post_url = f'{SITE_URL}/post.html?slug={slug}'
    today_str = datetime.now(timezone.utc).strftime('%A, %d %B %Y')

    email_html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:Arial,sans-serif">
<div style="max-width:640px;margin:0 auto;background:#fff">
  <div style="background:#070A0D;padding:24px;text-align:center">
    <div style="color:#D4A85A;font-weight:700;font-size:22px">MoneyTailors Daily Brief</div>
    <div style="color:#7A9BB5;font-size:11px;margin-top:6px">{today_str}</div>
  </div>
  <div style="padding:32px 28px">
    <h1 style="font-size:24px;color:#1B3A5C;margin:0 0 12px">{html.escape(title)}</h1>
    <div style="font-size:15px;line-height:1.75;color:#333">{html_content}</div>
    <div style="margin-top:32px;text-align:center">
      <a href="{post_url}" style="background:#D4A85A;color:#070A0D;text-decoration:none;padding:12px 28px;border-radius:6px;font-weight:600;font-size:14px">Read on MoneyTailors</a>
    </div>
  </div>
  <div style="background:#f5f5f0;padding:16px;text-align:center;font-size:11px;color:#888">
    <a href="{{unsubscribe}}" style="color:#888">Unsubscribe</a> · <a href="{SITE_URL}" style="color:#888">MoneyTailors.com</a>
    <br>Not financial advice.
  </div>
</div>
</body></html>"""

    headers = {'accept': 'application/json', 'api-key': BREVO_KEY, 'content-type': 'application/json'}

    try:
        # Create campaign
        r = requests.post('https://api.brevo.com/v3/emailCampaigns', headers=headers, json={
            'name': f'Daily Brief {today_str}',
            'subject': title,
            'sender': {'name': 'MoneyTailors Daily Brief', 'email': 'brief@moneytailors.com'},
            'htmlContent': email_html,
            'recipients': {'listIds': [int(BREVO_LIST_ID)]},
        }, timeout=30)

        if r.status_code not in (200, 201):
            print(f'Brevo campaign create failed {r.status_code}: {r.text[:200]}')
            return False

        campaign_id = r.json().get('id')
        print(f'Brevo campaign created: ID {campaign_id}')

        # Send immediately
        s = requests.post(f'https://api.brevo.com/v3/emailCampaigns/{campaign_id}/sendNow', headers=headers, timeout=30)
        if s.status_code in (200, 201, 204):
            print(f'Brevo campaign sent OK')
            return True
        else:
            print(f'Brevo sendNow failed {s.status_code}: {s.text[:200]}')
            return False
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

    # Step 4: Generate digest
    html_content, title, excerpt, category, img_hint = generate_digest(buckets, snapshot)
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
