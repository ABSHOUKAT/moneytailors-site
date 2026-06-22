#!/usr/bin/env python3
"""
MoneyTailors Weekly Outlook Agent
===================================
This is NOT a separate automated system — it's a manually-triggered
companion to daily_brief_agent.py, run once a week (Sundays, your choice
of time) inside a Claude Cowork session that has file access to your
local reports folder.

Pipeline:
  1. Read every file (PDF, DOCX, TXT, MD) you've dropped into REPORTS_FOLDER
     during the week
  2. Pull that week's already-published Daily Briefs from posts.json for
     continuity (so the weekly doesn't just repeat what daily already said)
  3. Fetch a fresh market snapshot (reuses daily_brief_agent's function)
  4. Generate a long-form weekly analysis via Claude — deeper, cross-
     referenced across asset classes and geographies, with explicit
     recommendations, NOT just a headline digest
  5. PRINT THE FULL DRAFT FOR YOUR REVIEW — this script does NOT auto-publish.
     You read the draft, then explicitly call publish_weekly(...) yourself
     (or tell Cowork "publish this") to actually send/commit it.
  6. On publish: same GitHub commit + Brevo send pipeline as the daily
     brief, but branded "MoneyTailors Weekly Outlook" instead of
     "Daily Brief", sent to the SAME subscriber list (per your decision —
     one list, Sunday's edition is just branded differently)

Required environment variables (same ones daily_brief_agent.py uses —
if you're running this in the same Cowork/CI context, they're already set):
  ANTHROPIC_API_KEY, GITHUB_TOKEN, GITHUB_REPO, BREVO_API_KEY, BREVO_LIST_ID

Usage (inside a Cowork session):
  python3 weekly_outlook_agent.py --reports-folder /path/to/your/reports/folder

This prints the draft and STOPS. To publish after reviewing, run:
  python3 weekly_outlook_agent.py --reports-folder /path/to/folder --publish
"""

import os, sys, json, re, glob, argparse
from datetime import datetime, timedelta, timezone

# Load .env file BEFORE anything else. This MUST happen before importing
# daily_brief_agent below, because that module reads os.environ.get(...)
# at import time to set its own module-level constants (GITHUB_TOKEN,
# BREVO_KEY, etc). If .env is loaded after that import, those constants
# are permanently empty for the rest of the process, even though
# os.environ itself would technically have the values. Cowork sessions run
# on an ephemeral VM and do not persist environment variables between
# sessions (confirmed via Anthropic's own GitHub issue tracker,
# claude-code#39125), so a .env file you upload fresh each session is the
# practical way to supply these credentials.
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        print(f'Loaded environment from {_env_path}')
    elif os.path.exists('.env'):
        load_dotenv('.env')
        print('Loaded environment from ./.env')
    else:
        print('No .env file found — relying on environment variables already set in this session')
except ImportError:
    print('python-dotenv not installed (pip install python-dotenv) — relying on environment variables already set in this session')

# Reuse the proven daily-brief infrastructure directly — no reimplementation,
# no risk of the two pipelines drifting apart over time.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_brief_agent as daily

import anthropic
import requests

ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
GITHUB_REPO   = os.environ.get('GITHUB_REPO', '')
SITE_URL      = os.environ.get('SITE_URL', 'https://www.moneytailors.com')

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None


# ─── Step 1: Read dropped-in report files ────────────────────────────────────
def read_reports_folder(folder_path):
    """Read every supported file in the folder. Returns list of
    {filename, text, char_count}. Unsupported file types are skipped with
    a warning, not silently ignored, so you know if something didn't get read."""
    if not os.path.isdir(folder_path):
        print(f'ERROR: reports folder not found: {folder_path}')
        return []

    supported_ext = {'.txt', '.md'}
    pdf_ext = {'.pdf'}
    docx_ext = {'.docx'}

    reports = []
    all_files = sorted(glob.glob(os.path.join(folder_path, '*')))

    for filepath in all_files:
        filename = os.path.basename(filepath)
        if filename.startswith('.') or filename == 'README.txt':
            continue
        ext = os.path.splitext(filename)[1].lower()

        try:
            if ext in supported_ext:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
            elif ext in pdf_ext:
                text = _extract_pdf_text(filepath)
            elif ext in docx_ext:
                text = _extract_docx_text(filepath)
            else:
                print(f'SKIPPED (unsupported type): {filename}')
                continue

            if not text.strip():
                print(f'WARNING: {filename} produced no extractable text, skipping')
                continue

            reports.append({
                'filename': filename,
                'text': text.strip(),
                'char_count': len(text),
            })
            print(f'Read: {filename} ({len(text):,} chars)')
        except Exception as e:
            print(f'ERROR reading {filename}: {e}')

    return reports


def _extract_pdf_text(filepath):
    """Extract text from a PDF. Requires pypdf (pip install pypdf)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        print('pypdf not installed — run: pip install pypdf')
        return ''
    reader = PdfReader(filepath)
    return '\n\n'.join(page.extract_text() or '' for page in reader.pages)


def _extract_docx_text(filepath):
    """Extract text from a DOCX. Requires python-docx (pip install python-docx)."""
    try:
        from docx import Document
    except ImportError:
        print('python-docx not installed — run: pip install python-docx')
        return ''
    doc = Document(filepath)
    return '\n\n'.join(p.text for p in doc.paragraphs)


# ─── Step 2: Pull this week's daily briefs for continuity ───────────────────
def fetch_this_weeks_daily_briefs():
    """Reads posts.json from the live repo and returns daily briefs published
    in the last 7 days, so the weekly outlook can build on what daily already
    covered rather than repeating it from scratch."""
    posts_raw, _ = daily.gh_get('content/posts.json')
    if not posts_raw:
        print('No posts.json found or repo not configured — continuing without daily-brief continuity')
        return []

    try:
        posts = json.loads(posts_raw)
    except json.JSONDecodeError:
        print('posts.json could not be parsed — continuing without continuity')
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%d')
    week_daily = [
        p for p in posts
        if p.get('daily') and p.get('date', '') >= cutoff
    ]
    print(f'Found {len(week_daily)} daily briefs from the past 7 days for continuity context')
    return week_daily


# ─── Step 3: Generate the weekly analysis ────────────────────────────────────
def generate_weekly_outlook(reports, week_daily_briefs, snapshot):
    if not client:
        print('ERROR: ANTHROPIC_API_KEY not set')
        return None

    today_str = datetime.now(timezone.utc).strftime('%A, %d %B %Y')

    reports_block = ''
    if reports:
        reports_block = (
            '\nRESEARCH MATERIAL FOR THIS EDITION (internal source material only - '
            'these are numbered for your own organization while reading, NEVER refer '
            'to "Source 1" or any filename in your output, treat all of this as '
            'MoneyTailors\' own research input, not material to cite):\n'
        )
        for i, r in enumerate(reports, 1):
            # Cap each report's contribution to keep the prompt manageable;
            # for very long reports this takes the first ~8000 chars, which
            # is usually enough for the model to identify key themes without
            # blowing the context budget across multiple reports.
            excerpt = r['text'][:8000]
            truncated_note = ' [TRUNCATED]' if len(r['text']) > 8000 else ''
            reports_block += f'\n--- Internal research material {i}{truncated_note} ---\n{excerpt}\n'
    else:
        reports_block = '\n(No additional research material was provided this week - base the outlook on the daily brief continuity and market snapshot below only, and say so in MoneyTailors\' own voice rather than inventing claims.)\n'

    continuity_block = ''
    if week_daily_briefs:
        continuity_block = '\nTHIS WEEK\'S DAILY BRIEFS (for continuity, do not just repeat these):\n'
        for p in week_daily_briefs:
            continuity_block += f'  • {p["date"]}: {p["title"]}\n'

    snapshot_block = ''
    if snapshot.get('crypto'):
        snapshot_block = '\nLIVE MARKET SNAPSHOT:\n'
        for sym, d in snapshot['crypto'].items():
            usd = d.get('usd')
            chg = d.get('usd_24h_change')
            if usd:
                snapshot_block += f'  • {sym}: ${usd:,.2f}'
                if chg is not None:
                    snapshot_block += f' ({chg:+.2f}% 24h)'
                snapshot_block += '\n'

    prompt = f"""You are the editor of MoneyTailors Weekly Outlook, the Sunday long-form edition of the MoneyTailors Daily Market Brief. This is MoneyTailors' own deep, cross-asset, cross-geography analysis with explicit recommendations, written in-house using the research material below as input, not a summary of someone else's reports.

TODAY: {today_str}

{reports_block}
{continuity_block}
{snapshot_block}

VOICE AND OWNERSHIP (critical):
   - This is MoneyTailors' OWN house analysis, written in MoneyTailors' voice, not a summary or roundup of other people's reports
   - Absorb the facts and figures from the source material below, then present the analysis as MoneyTailors' own view, the way an in-house research desk writes after reading its inputs, not the way a literature review cites its sources
   - NEVER name, credit, or attribute a source report by name anywhere in the article body (no "according to [X]'s report", no "[X] notes that", no "per [X]'s data", no "the report explicitly flags"). If you need to refer to where information came from, use plain phrasing instead: "this week's data shows", "the latest figures indicate", "the picture this week is"
   - The reader should experience this as MoneyTailors speaking with its own authority, informed by deep research, not as MoneyTailors paraphrasing someone else's research

FACT DISCIPLINE (critical, same standard as the daily brief, but expressed in MoneyTailors' own voice per above):
   - Every specific claim (price, %, figure, event) must trace back to one of the source reports provided below, the daily brief continuity list, or the live snapshot, but the article text itself must never name which source it came from
   - Do NOT invent data points, forecasts, or events not present in the source material
   - If the provided material doesn't cover a geography or asset class well, say so in MoneyTailors' own voice rather than fabricating analysis, e.g. "Coverage on X was limited this week" rather than naming which source was thin
   - Ground each recommendation in the actual data (a real price level, a real % move, a real named catalyst) rather than in a citation, e.g. write "with the index now testing resistance at 11,200, a confirmed close above that level on stronger volume would open the path higher" instead of "given [report]'s note on the resistance level, consider X"

STRUCTURE — HTML body content (NO <html>/<head>/<body> wrapper tags):
   - Opening paragraph (80-120 words): the week's defining theme across markets, synthesized in MoneyTailors' own voice
   - 4-8 H2 sections, organized by asset class AND/OR geography depending on what the source material actually covers this week (don't force a fixed template if the sources don't support every category)
   - Each section: 3-5 sentences, genuinely analytical (what happened, why it matters, what it implies going forward), not just headline restating, and never naming a source report
   - One H2 "This Week's Recommendations" with 3-5 specific, data-grounded bullets across different asset classes/geographies where the material supports a view
   - One closing H2 "What to Watch Next Week" with upcoming catalysts drawn from the material, written in MoneyTailors' own voice
   - Total length: 1200-1800 words (this is the long-form weekly edition, meaningfully deeper than the 600-900 word daily brief)

STYLE:
   - Tone: analytical, professional, calm. This is the flagship weekly piece, write at the level of MoneyTailors' senior analyst's Sunday note, not a retail newsletter and not a summary of third-party research
   - Never use " — " (em-dash with spaces). Use comma or colon instead.
   - Active voice, present tense for current state, but comfortable making forward-looking statements when grounded in the data
   - Never write internal instruction labels as literal text anywhere in your output (no "Opening Paragraph:", no "Recommendations:" as a literal prefix beyond the actual H2 heading itself)
   - Never name, credit, or reference any source report by name anywhere in the output (re-stated here because this is the single most important style rule for this piece)

After the article body, output a JSON block in EXACTLY this format, no markdown fences:
---JSON---
{{"title":"A 60-100 character headline for the week's edition, naming the dominant theme, e.g. Fed Pause Meets Gulf IPO Wave: This Week's Cross-Market Outlook","excerpt":"160-char-max one-sentence summary of the week's outlook","category":"Weekly Outlook","image_prompt":"15-word concise visual description for AI image, gold and navy financial dashboard style, weekly/strategic feel"}}
---END---"""

    response = client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=6000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = response.content[0].text.strip()

    if '---JSON---' in raw and '---END---' in raw:
        html_part = raw.split('---JSON---')[0].strip()
        json_str  = raw.split('---JSON---')[1].split('---END---')[0].strip()
        try:
            meta = json.loads(json_str)
        except json.JSONDecodeError:
            print('WARNING: could not parse JSON metadata block, using fallback values')
            meta = {}
    else:
        print('WARNING: response did not contain expected ---JSON--- delimiters')
        html_part = raw
        meta = {}

    title    = meta.get('title', f'MoneyTailors Weekly Outlook, {today_str}')
    excerpt  = meta.get('excerpt', 'This week\'s cross-market analysis and recommendations from MoneyTailors.')
    category = meta.get('category', 'Weekly Outlook')
    img_hint = meta.get('image_prompt', 'financial markets dashboard, weekly strategic overview')

    return html_part, title, excerpt, category, img_hint


# ─── Step 4: Slug + publish (reuses daily's GitHub/Brevo plumbing) ──────────
def slugify_weekly(title):
    s = title.lower()
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'\s+', '-', s.strip())
    s = re.sub(r'-+', '-', s)
    date_prefix = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return f'{date_prefix}-weekly-outlook-{s[:40]}'.rstrip('-')


def publish_weekly(html_content, title, excerpt, category, slug, img_hint):
    """Publishes using the exact same GitHub commit + Brevo send functions
    as the daily brief, but with weekly-specific flags and email branding."""
    img_bytes = daily.generate_image(img_hint)

    # Reuse publish_to_site's GitHub-commit mechanics, but we can't call it
    # directly unmodified because it hardcodes 'daily': True. Replicate the
    # same logic here with the correct flags instead.
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    img_path = f'images/blog/{slug}.jpg'
    img_ok = False
    if img_bytes:
        img_ok = daily.gh_put(img_path, img_bytes, None, f'image: add {slug}.jpg')

    img_html = (
        f'<img src="/{img_path}" alt="{title}" '
        f'style="width:100%;border-radius:8px;margin-bottom:28px;display:block">'
    ) if img_ok else ''
    full_html = img_html + '\n' + html_content

    posts_raw, posts_sha = daily.gh_get('content/posts.json')
    posts = json.loads(posts_raw) if posts_raw else []

    existing = {p.get('slug', '') for p in posts}
    if slug in existing:
        print(f'Slug {slug} already exists — aborting publish')
        return False

    new_post = {
        'slug':     slug,
        'title':    title,
        'date':     today,
        'category': category,
        'excerpt':  excerpt,
        'image':    f'/{img_path}' if img_ok else '',
        'content':  full_html,
        'auto':     False,   # this one had a human review step, unlike daily
        'daily':    False,
        'weekly':   True,
    }

    posts.insert(0, new_post)
    posts_bytes = json.dumps(posts, indent=2, ensure_ascii=False).encode('utf-8')
    ok = daily.gh_put('content/posts.json', posts_bytes, posts_sha, f'weekly outlook: {title}')
    if not ok:
        print('GitHub publish failed')
        return False
    print('Published to site successfully.')

    # Email send — same Brevo mechanics, different branding
    email_ok = send_weekly_via_brevo(title, html_content, slug, excerpt)
    return ok and email_ok


def fetch_brevo_list_contacts(list_id, brevo_key):
    """Fetches all contacts on a Brevo list, handling pagination (max 500
    per page per Brevo's documented limit). Returns a list of {email, name}.
    This is required because the smtp/email transactional endpoint has no
    'send to entire list' parameter - listIds is not a valid field on this
    endpoint (confirmed via Brevo's own API docs and the exact error this
    script hit: 'messageVersions are missing' when listIds was used alone).
    The actual recipients must be fetched and passed explicitly."""
    contacts = []
    limit = 500
    offset = 0
    while True:
        try:
            resp = requests.get(
                f'https://api.brevo.com/v3/contacts/lists/{list_id}/contacts',
                headers={'accept': 'application/json', 'api-key': brevo_key},
                params={'limit': limit, 'offset': offset},
                timeout=30
            )
        except Exception as e:
            print(f'Error fetching contacts (offset {offset}): {e}')
            break

        if resp.status_code != 200:
            print(f'Failed to fetch contacts (offset {offset}): {resp.status_code} {resp.text[:200]}')
            break

        data = resp.json()
        batch = data.get('contacts', [])
        if not batch:
            break

        for c in batch:
            email = c.get('email')
            if not email:
                continue
            attrs = c.get('attributes', {})
            name = attrs.get('FIRSTNAME') or attrs.get('LASTNAME') or ''
            contacts.append({'email': email, 'name': name})

        offset += limit
        if len(batch) < limit:
            break  # last page

    return contacts


def send_weekly_via_brevo(title, html_content, slug, excerpt):
    if not daily.BREVO_KEY or not daily.BREVO_LIST_ID:
        print('Brevo not configured — skipping email send')
        return False

    post_url = f'{SITE_URL}/post.html?slug={slug}'
    today_str = datetime.now(timezone.utc).strftime('%A, %d %B %Y')

    # Plain string concatenation, not an f-string, so {{{unsubscribe}}}
    # is written exactly as Brevo needs to see it — no escaping, no ambiguity.
    UNSUBSCRIBE_TAG = '{{{unsubscribe}}}'

    email_html = (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>' + title + '</title></head>'
        '<body style="margin:0;padding:0;background:#f5f5f0;font-family:Inter,Arial,sans-serif;color:#1B3A5C">'
        '<div style="max-width:640px;margin:0 auto;background:#ffffff">'
        '  <div style="background:#070A0D;padding:24px;text-align:center">'
        '    <div style="color:#D4A85A;font-family:\'Space Grotesk\',Arial,sans-serif;font-weight:700;font-size:22px;letter-spacing:-0.3px">Money<span style="color:#E8DCC4">Tailors</span> Weekly Outlook</div>'
        '    <div style="color:#7A9BB5;font-size:11px;letter-spacing:1.5px;margin-top:6px">' + today_str + '</div>'
        '  </div>'
        '  <div style="padding:32px 28px">'
        '    <h1 style="font-family:\'Space Grotesk\',Arial,sans-serif;font-size:26px;font-weight:700;color:#1B3A5C;line-height:1.2;margin:0 0 14px">' + title + '</h1>'
        '    <p style="font-size:14px;color:#666;line-height:1.6;margin:0 0 24px">' + excerpt + '</p>'
        '    <div style="font-size:15px;line-height:1.75;color:#333">' + html_content + '</div>'
        '    <div style="margin-top:36px;padding-top:24px;border-top:1px solid #eee;text-align:center">'
        '      <a href="' + post_url + '" style="display:inline-block;background:#D4A85A;color:#070A0D;text-decoration:none;padding:12px 28px;border-radius:6px;font-weight:600;font-size:14px">Read on MoneyTailors &#8594;</a>'
        '    </div>'
        '  </div>'
        '  <div style="background:#f5f5f0;padding:20px;text-align:center;font-size:11px;color:#888">'
        '    You\'re receiving this because you subscribed to MoneyTailors briefs.<br>'
        '    <a href="' + UNSUBSCRIBE_TAG + '" style="color:#888">Unsubscribe</a> &nbsp;&middot;&nbsp; <a href="' + SITE_URL + '" style="color:#888">MoneyTailors.com</a><br><br>'
        '    Not financial advice. Markets are risky. Please do your own research.'
        '  </div>'
        '</div>'
        '</body></html>'
    )

    print(f'Fetching contacts from Brevo list {daily.BREVO_LIST_ID}...')
    contacts = fetch_brevo_list_contacts(daily.BREVO_LIST_ID, daily.BREVO_KEY)
    print(f'Found {len(contacts)} contacts on the list.')
    if not contacts:
        print('No contacts found on this list — nothing to send. Check that BREVO_LIST_ID is correct.')
        return False

    # Brevo's batch-send limit is 1000 message versions per call. Each
    # version gets its own 'to' array containing exactly one recipient,
    # so no subscriber's email address is visible to any other recipient
    # (unlike a single shared 'to' list, which would expose everyone).
    batch_size = 1000
    all_ok = True
    for i in range(0, len(contacts), batch_size):
        batch = contacts[i:i + batch_size]
        message_versions = [
            {'to': [{'email': c['email'], 'name': c['name'] or c['email']}]}
            for c in batch
        ]

        payload = {
            'sender': {'name': 'MoneyTailors Weekly Outlook', 'email': 'brief@moneytailors.com'},
            'subject': title,
            'htmlContent': email_html,
            'messageVersions': message_versions,
        }

        try:
            resp = requests.post(
                'https://api.brevo.com/v3/smtp/email',
                headers={'accept': 'application/json', 'api-key': daily.BREVO_KEY, 'content-type': 'application/json'},
                json=payload,
                timeout=60
            )
            if resp.status_code in (200, 201):
                result = resp.json()
                sent_count = len(result.get('messageIds', []))
                print(f'Brevo batch {i//batch_size + 1}: sent to {sent_count} recipients OK')
            else:
                print(f'Brevo batch {i//batch_size + 1} failed {resp.status_code}: {resp.text[:300]}')
                all_ok = False
        except Exception as e:
            print(f'Brevo batch {i//batch_size + 1} error: {e}')
            all_ok = False

    return all_ok


# ─── Main ─────────────────────────────────────────────────────────────────────
def resend_last_email():
    """Retrieves the most recently published weekly post from posts.json and
    sends just the email for it, without regenerating content or touching
    GitHub again. Use this when publish_weekly() succeeded on the site-commit
    step but failed on the email-send step (e.g. Brevo credentials were
    wrong at the time), so you don't end up with a duplicate article."""
    posts_raw, _ = daily.gh_get('content/posts.json')
    if not posts_raw:
        print('Could not read posts.json from the repo')
        return False
    posts = json.loads(posts_raw)
    weekly_posts = [p for p in posts if p.get('weekly')]
    if not weekly_posts:
        print('No weekly posts found in posts.json')
        return False

    # posts.json has newest first (publish_weekly does posts.insert(0, ...))
    latest = weekly_posts[0]
    print(f'Found most recent weekly post: "{latest["title"]}" ({latest["date"]})')

    # Strip the leading <img> tag that publish_weekly prepends to "content",
    # since the email template adds its own header, we just want the body.
    content = latest['content']
    content_without_img = re.sub(r'^<img[^>]*>\s*\n?', '', content, count=1)

    ok = send_weekly_via_brevo(latest['title'], content_without_img, latest['slug'], latest['excerpt'])
    return ok


def main():
    parser = argparse.ArgumentParser(description='MoneyTailors Weekly Outlook generator')
    parser.add_argument('--reports-folder', help='Path to the folder with this week\'s dropped-in reports (required unless using --resend-last-email)')
    parser.add_argument('--publish', action='store_true', help='Actually publish (commit to GitHub + send via Brevo). Without this flag, only prints the draft for review.')
    parser.add_argument('--resend-last-email', action='store_true', help='Re-send the email for the most recently published weekly post, without regenerating or re-publishing content. Use this if the site published successfully but the email send failed.')
    args = parser.parse_args()

    if args.resend_last_email:
        if not GITHUB_REPO:
            print('ERROR: GITHUB_REPO not set in .env')
            sys.exit(1)
        if not daily.BREVO_KEY or daily.BREVO_KEY.startswith('REPLACE_THIS'):
            print('ERROR: BREVO_API_KEY is not set correctly in .env')
            sys.exit(1)
        if not daily.BREVO_LIST_ID or daily.BREVO_LIST_ID.startswith('REPLACE_THIS'):
            print('ERROR: BREVO_LIST_ID is not set correctly in .env')
            sys.exit(1)
        ok = resend_last_email()
        print('Email resend ' + ('succeeded.' if ok else 'FAILED — check logs above.'))
        sys.exit(0 if ok else 1)

    if not args.reports_folder:
        print('ERROR: --reports-folder is required (unless using --resend-last-email)')
        sys.exit(1)

    # Friendly upfront check: catch un-filled-in .env placeholders before
    # they reach the Anthropic/GitHub/Brevo APIs and produce a confusing
    # stack trace. This is the single most common first-run mistake, so it
    # gets a clear, specific message rather than a generic auth error.
    required = {
        'ANTHROPIC_API_KEY': ANTHROPIC_KEY,
        'GITHUB_TOKEN':      daily.GITHUB_TOKEN,
        'GITHUB_REPO':       GITHUB_REPO,
    }
    missing_or_placeholder = [
        name for name, val in required.items()
        if not val or val.startswith('REPLACE_THIS')
    ]
    if missing_or_placeholder:
        print('=' * 70)
        print('SETUP NOT COMPLETE')
        print('=' * 70)
        print('The following values in your .env file still need to be filled in')
        print('with your real credentials (they currently say REPLACE_THIS... or')
        print('are missing entirely):')
        for name in missing_or_placeholder:
            print(f'  - {name}')
        print()
        print('Open the .env file (one level up from this scripts/ folder),')
        print('replace each REPLACE_THIS_... line with your real value, save,')
        print('and run this command again.')
        print('=' * 70)
        sys.exit(1)

    if not daily.BREVO_KEY or daily.BREVO_KEY.startswith('REPLACE_THIS'):
        print('NOTE: BREVO_API_KEY is not set or still a placeholder.')
        print('This is OK for generating a draft, but publishing will skip')
        print('sending the email until this is filled in.\n')

    print('=== MoneyTailors Weekly Outlook ===\n')

    print('Step 1: Reading reports folder...')
    reports = read_reports_folder(args.reports_folder)
    print(f'Total reports read: {len(reports)}\n')

    print('Step 2: Pulling this week\'s daily briefs for continuity...')
    week_daily_briefs = fetch_this_weeks_daily_briefs()
    print()

    print('Step 3: Fetching market snapshot...')
    snapshot = daily.fetch_market_snapshot()
    print()

    print('Step 4: Generating weekly outlook...')
    result = generate_weekly_outlook(reports, week_daily_briefs, snapshot)
    if not result:
        print('Generation failed')
        sys.exit(1)
    html_content, title, excerpt, category, img_hint = result
    slug = slugify_weekly(title)

    print('\n' + '=' * 70)
    print('DRAFT READY FOR REVIEW')
    print('=' * 70)
    print(f'Title:    {title}')
    print(f'Excerpt:  {excerpt}')
    print(f'Slug:     {slug}')
    print(f'Category: {category}')
    print(f'Image prompt: {img_hint}')
    print('-' * 70)
    print(html_content)
    print('=' * 70)

    if args.publish:
        print('\n--publish flag set, publishing now...')
        ok = publish_weekly(html_content, title, excerpt, category, slug, img_hint)
        print('Publish ' + ('succeeded.' if ok else 'FAILED — check logs above.'))
    else:
        print('\nThis was a DRAFT ONLY (no --publish flag). Review the content above.')
        print('If it looks good, re-run with --publish to actually send/commit it.')


if __name__ == '__main__':
    main()
