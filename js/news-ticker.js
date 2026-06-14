/* news-ticker.js — MoneyTailors
   Live financial/business news in the scrolling ticker via Marketaux (free tier,
   100 requests/day), with a recurring "Daily Market Brief" subscribe CTA woven
   between the news items. News is cached in localStorage for 30 minutes so a
   visitor browsing multiple pages consumes only one API call per half hour.
*/

const MARKETAUX_KEY = 'HgY1A0J8SrEJEtsoneEtatoydKqQI7RR5gseJZHo';
const MARKETAUX_URL = 'https://api.marketaux.com/v1/news/all';
const NEWS_CACHE_KEY = 'mt_news_cache_v1';
const NEWS_CACHE_MS  = 30 * 60 * 1000; // 30 minutes
const CTA_EVERY = 4;

function readNewsCache() {
  try {
    const raw = localStorage.getItem(NEWS_CACHE_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (!obj.ts || (Date.now() - obj.ts) > NEWS_CACHE_MS) return null;
    return obj.items && obj.items.length ? obj.items : null;
  } catch { return null; }
}
function writeNewsCache(items) {
  try { localStorage.setItem(NEWS_CACHE_KEY, JSON.stringify({ ts: Date.now(), items })); } catch {}
}

async function fetchMarketaux() {
  const params = new URLSearchParams({
    language: 'en',
    filter_entities: 'true',
    limit: '12',
    api_token: MARKETAUX_KEY
  });
  try {
    const res = await fetch(`${MARKETAUX_URL}?${params.toString()}`);
    const data = await res.json();
    if (data && Array.isArray(data.data)) {
      return data.data
        .filter(a => a.title && a.url)
        .map(a => ({ title: a.title, link: a.url, source: (a.source || 'News').replace(/\.(com|net|org|co|io).*$/i, '') }));
    }
  } catch (e) {
    console.warn('Marketaux fetch failed:', e);
  }
  return [];
}

function ctaItem() {
  return `<a class="ticker-news-item ticker-cta" href="newsletter.html">
      <span class="ticker-cta-badge">&#9993; DAILY MARKET BRIEF</span>
      <span class="ticker-cta-text">Get tomorrow's market moves in your inbox — Subscribe free</span>
    </a>
    <span class="ticker-sep">&#9670;</span>`;
}

function newsItemHtml(item) {
  return `<a class="ticker-news-item" href="${item.link}" target="_blank" rel="noopener nofollow">
      <span class="ticker-source">${escHtml(item.source)}</span>
      <span class="ticker-headline">${escHtml(item.title)}</span>
    </a>
    <span class="ticker-sep">&#9670;</span>`;
}

async function loadNewsTicker() {
  const strip = document.getElementById('news-ticker-inner');
  if (!strip) return;

  let items = readNewsCache();
  if (!items) {
    items = await fetchMarketaux();
    if (items.length) writeNewsCache(items);
  }

  if (!items || !items.length) {
    strip.innerHTML = buildFallback();
    startTickerScroll();
    return;
  }

  let html = '';
  items.forEach((item, i) => {
    html += newsItemHtml(item);
    if ((i + 1) % CTA_EVERY === 0) html += ctaItem();
  });
  html += ctaItem();

  strip.innerHTML = html;
  strip.innerHTML += strip.innerHTML; // seamless loop
  startTickerScroll();
}

function buildFallback() {
  const f = [
    ctaItem(),
    `<span class="ticker-news-item"><span class="ticker-source">Markets</span><span class="ticker-headline">Live market data updating — see the Markets page for the full dashboard</span></span><span class="ticker-sep">&#9670;</span>`,
    `<span class="ticker-news-item"><span class="ticker-source">Tools</span><span class="ticker-headline">Free trading calculators: Pip Value, Position Size, Lot Size, Zakat, SIP, EMI and more</span></span><span class="ticker-sep">&#9670;</span>`,
    ctaItem(),
  ].join('');
  return f + f;
}

let tickerAnim = null;
let tickerPos  = 0;

function startTickerScroll() {
  const strip = document.getElementById('news-ticker-inner');
  if (!strip) return;
  if (tickerAnim) cancelAnimationFrame(tickerAnim);

  const speed = 0.5;
  const halfWidth = strip.scrollWidth / 2;

  function step() {
    tickerPos -= speed;
    if (halfWidth > 0 && Math.abs(tickerPos) >= halfWidth) tickerPos = 0;
    strip.style.transform = `translateX(${tickerPos}px)`;
    tickerAnim = requestAnimationFrame(step);
  }

  strip.parentElement.addEventListener('mouseenter', () => cancelAnimationFrame(tickerAnim));
  strip.parentElement.addEventListener('mouseleave', () => { tickerAnim = requestAnimationFrame(step); });

  tickerAnim = requestAnimationFrame(step);
}

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

document.addEventListener('DOMContentLoaded', () => {
  loadNewsTicker();
  setInterval(loadNewsTicker, NEWS_CACHE_MS); // re-check every 30 min
});
