/* main.js — MoneyTailors */

// ---- Navigation ----
document.addEventListener('DOMContentLoaded', () => {
  const hamburger = document.querySelector('.nav-hamburger');
  const navLinks  = document.querySelector('.nav-links');

  if (hamburger && navLinks) {
    hamburger.addEventListener('click', () => {
      navLinks.classList.toggle('open');
      hamburger.classList.toggle('open');
    });
    navLinks.querySelectorAll('a').forEach(a => {
      a.addEventListener('click', () => {
        navLinks.classList.remove('open');
        hamburger.classList.remove('open');
      });
    });
  }

  // Active nav link
  const path = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-links a').forEach(a => {
    const href = a.getAttribute('href');
    if (href === path || (path === '' && href === 'index.html')) {
      a.classList.add('active');
    }
  });

  // Scroll reveal
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.classList.add('visible');
        observer.unobserve(e.target);
      }
    });
  }, { threshold: 0.12 });

  document.querySelectorAll('.fade-up').forEach(el => observer.observe(el));

  // Animate market rows on homepage
  animateMarketData();
});

// ---- Live market data for hero snapshot panel ----
// Uses ONLY keyless, unlimited, CORS-friendly sources so the homepage never
// consumes the Twelve Data quota (reserved for the Portfolio page):
//   • gold-api.com     → metals (Gold, Silver), no key, CORS-friendly
//   • CoinGecko        → crypto (BTC, ETH), no key
//   • open.er-api.com  → FX rates (EUR/USD, USD/JPY), no key
// Stock indices (S&P/Nasdaq/Dow) and Oil have no keyless CORS API, so they live
// on the markets pages via TradingView widgets (unlimited) rather than here.

const SNAPSHOT_METALS = [
  { idx: 0, sym: 'XAU', label: 'XAU/USD', name: 'Gold' },
  { idx: 1, sym: 'XAG', label: 'XAG/USD', name: 'Silver' },
];
const SNAPSHOT_CRYPTO = [
  { idx: 2, id: 'bitcoin',  label: 'BTC/USD', name: 'Bitcoin'  },
  { idx: 3, id: 'ethereum', label: 'ETH/USD', name: 'Ethereum' },
];
const SNAPSHOT_FX = [
  { idx: 4, base: 'EUR', quote: 'USD', label: 'EUR/USD', name: 'Euro / Dollar' },
  { idx: 5, base: 'USD', quote: 'JPY', label: 'USD/JPY', name: 'Dollar / Yen' },
];

function fmtSnapPrice(n) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  if (n >= 1000) return Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 });
  if (n >= 1)    return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  return Number(n).toFixed(4);
}

function paintSnapshotRow(idx, label, name, price, pct) {
  const row = document.querySelector(`.market-row[data-idx="${idx}"]`);
  if (!row) return;
  const symEl    = row.querySelector('.market-symbol');
  const nameEl   = row.querySelector('.market-name');
  const priceEl  = row.querySelector('.market-price');
  const changeEl = row.querySelector('.market-change');
  if (symEl)  symEl.textContent  = label;
  if (nameEl) nameEl.textContent = name;
  if (priceEl) priceEl.textContent = fmtSnapPrice(price);
  if (changeEl) {
    if (pct === null || pct === undefined || isNaN(pct)) {
      changeEl.textContent = '';
      changeEl.className = 'market-change';
    } else {
      const dir = pct >= 0 ? 'up' : 'down';
      changeEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
      changeEl.className = 'market-change ' + dir;
    }
  }
}

async function loadSnapshotMetals() {
  await Promise.all(SNAPSHOT_METALS.map(async m => {
    try {
      const res = await fetch(`https://api.gold-api.com/price/${m.sym}`);
      const data = await res.json();
      if (data && data.price) paintSnapshotRow(m.idx, m.label, m.name, data.price, null);
      else paintSnapshotRow(m.idx, m.label, m.name, null, null);
    } catch (e) {
      console.warn('Snapshot metals fetch failed:', e);
      paintSnapshotRow(m.idx, m.label, m.name, null, null);
    }
  }));
}

async function loadSnapshotCrypto() {
  const ids = SNAPSHOT_CRYPTO.map(r => r.id).join(',');
  try {
    const res = await fetch(`https://api.coingecko.com/api/v3/simple/price?ids=${ids}&vs_currencies=usd&include_24hr_change=true`);
    const data = await res.json();
    SNAPSHOT_CRYPTO.forEach(r => {
      const d = data[r.id];
      if (d && d.usd) paintSnapshotRow(r.idx, r.label, r.name, d.usd, d.usd_24h_change);
      else paintSnapshotRow(r.idx, r.label, r.name, null, null);
    });
  } catch (e) {
    console.warn('Snapshot crypto fetch failed:', e);
    SNAPSHOT_CRYPTO.forEach(r => paintSnapshotRow(r.idx, r.label, r.name, null, null));
  }
}

async function loadSnapshotFx() {
  try {
    const res = await fetch('https://open.er-api.com/v6/latest/USD');
    const data = await res.json();
    if (!data || data.result !== 'success' || !data.rates) throw new Error('bad fx');
    const r = data.rates;
    SNAPSHOT_FX.forEach(row => {
      let price = null;
      if (row.base === 'USD') price = r[row.quote];
      else price = r[row.base] ? (1 / r[row.base]) : null;
      paintSnapshotRow(row.idx, row.label, row.name, price, null);
    });
  } catch (e) {
    console.warn('Snapshot FX fetch failed:', e);
    SNAPSHOT_FX.forEach(row => paintSnapshotRow(row.idx, row.label, row.name, null, null));
  }
}

function animateMarketData() {
  // Paint labels immediately so panel isn't blank while loading
  [...SNAPSHOT_METALS.map(m => ({idx:m.idx,label:m.label,name:m.name})),
   ...SNAPSHOT_CRYPTO, ...SNAPSHOT_FX].forEach(r => {
    const row = document.querySelector(`.market-row[data-idx="${r.idx}"]`);
    if (row) {
      const symEl = row.querySelector('.market-symbol');
      const nameEl = row.querySelector('.market-name');
      if (symEl) symEl.textContent = r.label;
      if (nameEl) nameEl.textContent = r.name;
    }
  });
  loadSnapshotMetals();
  loadSnapshotCrypto();
  loadSnapshotFx();
  // Refresh every 5 min (keyless sources, no quota concern)
  setInterval(() => { loadSnapshotMetals(); loadSnapshotCrypto(); loadSnapshotFx(); }, 300000);
}
