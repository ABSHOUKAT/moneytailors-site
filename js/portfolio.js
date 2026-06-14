/* portfolio.js — Supabase auth + portfolio management for MoneyTailors
 *
 * REQUIRED SETUP (do once after deployment):
 *   1. Create free account at https://supabase.com
 *   2. Create a new project
 *   3. In SQL Editor, run the schema below (provided in DEPLOYMENT_GUIDE.md)
 *   4. From Settings → API, copy:
 *      - Project URL  → SUPABASE_URL
 *      - anon public key → SUPABASE_ANON_KEY
 *   5. Replace the placeholders below and you are done
 *
 * The anon key is safe to publish — Row Level Security (RLS) policies in the
 * schema ensure users can only ever read/write their own data.
 */

const SUPABASE_URL      = 'https://jirhsjzbeclecmgeuyyo.supabase.co';     // e.g. https://abcdefgh.supabase.co
const SUPABASE_ANON_KEY = 'sb_publishable_ckA0lva_fFEg3JzZvtfZEw_KMesK9F9';        // long JWT-style string starting with eyJ...

let sb = null;

// Initialise Supabase client when CDN script is ready
function initSupabase() {
  if (typeof window.supabase === 'undefined') {
    console.error('Supabase JS library not loaded — check CDN script.');
    return false;
  }
  if (SUPABASE_URL.startsWith('YOUR_')) {
    console.warn('Supabase not configured yet. Update SUPABASE_URL and SUPABASE_ANON_KEY in js/portfolio.js');
    return false;
  }
  sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  return true;
}

// ────────────────────────────────────────────────────────────────
// AUTH HELPERS
// ────────────────────────────────────────────────────────────────
async function signUp(email, password, fullName) {
  if (!sb) return { error: { message: 'Supabase not configured' } };
  const { data, error } = await sb.auth.signUp({
    email, password,
    options: { data: { full_name: fullName } }
  });
  return { data, error };
}

async function signIn(email, password) {
  if (!sb) return { error: { message: 'Supabase not configured' } };
  return await sb.auth.signInWithPassword({ email, password });
}

async function signOut() {
  if (!sb) return;
  await sb.auth.signOut();
  window.location.href = 'login.html';
}

async function getUser() {
  if (!sb) return null;
  const { data } = await sb.auth.getUser();
  return data?.user || null;
}

async function requireAuth() {
  const user = await getUser();
  if (!user) {
    window.location.href = 'login.html';
    return null;
  }
  return user;
}

// ────────────────────────────────────────────────────────────────
// HOLDINGS CRUD
// ────────────────────────────────────────────────────────────────
async function fetchHoldings() {
  if (!sb) return [];
  const { data, error } = await sb
    .from('holdings')
    .select('*')
    .order('created_at', { ascending: false });
  if (error) { console.error(error); return []; }
  return data || [];
}

async function addHolding(holding) {
  if (!sb) return { error: 'Supabase not configured' };
  const user = await getUser();
  if (!user) return { error: 'Not signed in' };
  const payload = {
    user_id:        user.id,
    asset_class:    holding.asset_class,
    symbol:         holding.symbol,
    name:           holding.name || holding.symbol,
    quantity:       parseFloat(holding.quantity),
    avg_cost:       parseFloat(holding.avg_cost),
    currency:       holding.currency || 'USD',
    notes:          holding.notes || ''
  };
  return await sb.from('holdings').insert(payload).select();
}

async function updateHolding(id, updates) {
  if (!sb) return { error: 'Supabase not configured' };
  return await sb.from('holdings').update(updates).eq('id', id).select();
}

async function deleteHolding(id) {
  if (!sb) return { error: 'Supabase not configured' };
  return await sb.from('holdings').delete().eq('id', id);
}

// ────────────────────────────────────────────────────────────────
// PRICE LOOKUPS (free sources)
// ────────────────────────────────────────────────────────────────

// Twelve Data — free tier (800 requests/day, 8/min)
// Get a free key at https://twelvedata.com
const TWELVEDATA_API_KEY = '8e2f16c87c254fc9a7da5880efa8a42a';
const TD = 'https://api.twelvedata.com';

async function getCryptoPrice(symbol) {
  // CoinGecko simple price endpoint — free, no key
  try {
    // We need to map common symbols to CoinGecko IDs
    const idMap = {
      'BTC':'bitcoin','ETH':'ethereum','BNB':'binancecoin','SOL':'solana',
      'XRP':'ripple','ADA':'cardano','DOGE':'dogecoin','AVAX':'avalanche-2',
      'DOT':'polkadot','MATIC':'matic-network','LINK':'chainlink','UNI':'uniswap',
      'LTC':'litecoin','ATOM':'cosmos','TRX':'tron','SHIB':'shiba-inu'
    };
    const id = idMap[symbol.toUpperCase()] || symbol.toLowerCase();
    const res = await fetch(`https://api.coingecko.com/api/v3/simple/price?ids=${id}&vs_currencies=usd`);
    const data = await res.json();
    return data[id]?.usd || null;
  } catch { return null; }
}

// Map a portfolio "symbol" + asset_class into the symbol format Twelve Data expects.
const COMMODITY_MAP = {
  'GOLD':'XAU/USD', 'XAU':'XAU/USD', 'XAUUSD':'XAU/USD',
  'SILVER':'XAG/USD', 'XAG':'XAG/USD', 'XAGUSD':'XAG/USD',
  'OIL':'WTI/USD', 'WTI':'WTI/USD', 'CRUDE':'WTI/USD',
  'BRENT':'BRENT/USD',
  'NATGAS':'NATGAS/USD', 'GAS':'NATGAS/USD',
  'COPPER':'XCU/USD', 'XCU':'XCU/USD'
};

function toTwelveDataSymbol(h) {
  const sym = h.symbol.toUpperCase().replace(/\s+/g, '');
  if (h.asset_class === 'forex') {
    if (sym.includes('/')) return sym;
    if (sym.length === 6) return `${sym.slice(0,3)}/${sym.slice(3)}`;
    return sym;
  }
  if (h.asset_class === 'commodity') {
    return COMMODITY_MAP[sym] || sym;
  }
  // Stock: if it's a numeric code priced in SAR, it's a Tadawul ticker.
  // Twelve Data recognises Tadawul symbols but gates prices behind a paid plan,
  // so these will fall back to the user-entered price (○). We still format correctly
  // so that if the account is ever upgraded, it works without code changes.
  if ((h.currency || '').toUpperCase() === 'SAR' && /^\d+$/.test(sym)) {
    return `${sym}:Tadawul`;
  }
  return sym; // other stocks — pass through as-is
}

// Batch fetch — Twelve Data supports comma-separated symbols in one call
async function getTwelveDataBatchPrices(tdSymbols) {
  if (!tdSymbols.length) return {};
  if (!TWELVEDATA_API_KEY || TWELVEDATA_API_KEY.startsWith('YOUR_')) return {};
  try {
    const joined = tdSymbols.join(',');
    const url = `${TD}/price?symbol=${encodeURIComponent(joined)}&apikey=${TWELVEDATA_API_KEY}`;
    const res = await fetch(url);
    const data = await res.json();

    const out = {};
    if (tdSymbols.length === 1) {
      if (data && data.price) out[tdSymbols[0]] = parseFloat(data.price);
    } else {
      for (const sym of tdSymbols) {
        const entry = data[sym];
        if (entry && entry.price) out[sym] = parseFloat(entry.price);
        else if (entry && entry.status === 'error') {
          console.warn(`Twelve Data error for ${sym}:`, entry.message);
        }
      }
    }
    return out;
  } catch (e) {
    console.warn('Twelve Data batch fetch failed:', e);
    return {};
  }
}

// Fetch FX rates to convert any currency to USD. Returns a map like { SAR: 0.2667, PKR: 0.0036, ... }
// USD is always 1. Uses open.er-api.com — free, no key, CORS-friendly, unlimited.
// This keeps the Twelve Data quota reserved for actual asset prices only.
async function getUsdConversionRates(currencies) {
  const need = [...new Set(currencies)].filter(c => c && c !== 'USD');
  const rates = { USD: 1 };
  if (!need.length) return rates;
  try {
    const res = await fetch('https://open.er-api.com/v6/latest/USD');
    const data = await res.json();
    if (data && data.result === 'success' && data.rates) {
      need.forEach(c => {
        // data.rates[c] = how many units of `c` per 1 USD.
        // We want USD per 1 unit of `c` = 1 / that.
        const perUsd = data.rates[c];
        rates[c] = (perUsd && perUsd > 0) ? (1 / perUsd) : null;
      });
    } else {
      need.forEach(c => rates[c] = null);
    }
  } catch (e) {
    console.warn('FX rate fetch failed:', e);
    need.forEach(c => rates[c] = null);
  }
  return rates;
}

async function refreshAllPrices(holdings) {
  if (!holdings.length) return [];

  const cryptoHoldings = holdings.filter(h => h.asset_class === 'crypto');
  const tdHoldings     = holdings.filter(h => h.asset_class !== 'crypto');

  // Crypto via CoinGecko
  const cryptoPrices = {};
  await Promise.all(cryptoHoldings.map(async h => {
    cryptoPrices[h.id] = await getCryptoPrice(h.symbol);
  }));

  // Stocks/Forex/Commodities via Twelve Data (single batch request)
  const tdSymbolMap = {};
  tdHoldings.forEach(h => {
    const tdSym = toTwelveDataSymbol(h);
    if (!tdSymbolMap[tdSym]) tdSymbolMap[tdSym] = [];
    tdSymbolMap[tdSym].push(h);
  });
  const uniqueTdSymbols = Object.keys(tdSymbolMap);
  const tdPrices = await getTwelveDataBatchPrices(uniqueTdSymbols);

  // FX rates to convert each holding's native currency into USD for the portfolio total
  const fxRates = await getUsdConversionRates(holdings.map(h => h.currency || 'USD'));

  return holdings.map(h => {
    let current_price = null;
    if (h.asset_class === 'crypto') {
      current_price = cryptoPrices[h.id];
    } else {
      current_price = tdPrices[toTwelveDataSymbol(h)];
    }

    let live = true;
    if (current_price === null || current_price === undefined || isNaN(current_price)) {
      current_price = h.avg_cost;
      live = false;
    }

    const cur = h.currency || 'USD';
    const fx  = fxRates[cur];                  // USD per 1 unit of `cur` (null if unavailable)
    const fx_ok = (fx !== null && fx !== undefined && !isNaN(fx));
    const usd_rate = fx_ok ? fx : (cur === 'USD' ? 1 : null);

    const current_value = current_price * h.quantity;
    const cost_basis    = h.avg_cost * h.quantity;
    const pnl           = (current_price - h.avg_cost) * h.quantity;

    return {
      ...h,
      current_price,
      live_price: live,
      current_value,
      cost_basis,
      pnl,
      pnl_pct: h.avg_cost ? ((current_price - h.avg_cost) / h.avg_cost) * 100 : 0,
      // USD-converted figures for portfolio totals (null if no FX rate available)
      usd_rate,
      current_value_usd: usd_rate !== null ? current_value * usd_rate : null,
      cost_basis_usd:    usd_rate !== null ? cost_basis * usd_rate : null,
      pnl_usd:           usd_rate !== null ? pnl * usd_rate : null,
    };
  });
}
