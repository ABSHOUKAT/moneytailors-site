/* calculators.js — MoneyTailors (7 calculators) */

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.calc-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.calc;
      document.querySelectorAll('.calc-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.calc-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('calc-' + target)?.classList.add('active');
    });
  });
});

function fmt(n, d=2) { if (isNaN(n)||!isFinite(n)) return '—'; return Number(n).toLocaleString('en-US',{minimumFractionDigits:d, maximumFractionDigits:d}); }
function fmtCurrency(n, s='$') { return s + fmt(n,2); }

// ============================================================
// 1. FOREX PIP VALUE
// ============================================================
function calcForex() {
  const pair = document.getElementById('fx-pair').value;
  const lotType = document.getElementById('fx-lot-type').value;
  const lots = parseFloat(document.getElementById('fx-lots').value);
  const account = document.getElementById('fx-account').value;
  if (isNaN(lots) || lots <= 0) return;
  const contractSize = { standard:100000, mini:10000, micro:1000 }[lotType];
  const isJPY = pair.includes('JPY');
  const pipSize = isJPY ? 0.01 : 0.0001;
  const rates = { 'EUR/USD':1.085,'GBP/USD':1.265,'AUD/USD':0.655,'USD/CHF':0.906,'USD/JPY':154.5,'USD/CAD':1.365,'USD/SAR':3.75,'USD/PKR':278.0,'EUR/GBP':0.858 };
  const rate = rates[pair] || 1.0;
  let pipUSD;
  if (pair.startsWith('USD')) pipUSD = (pipSize/rate) * contractSize * lots;
  else if (pair.endsWith('USD') || pair.endsWith('SAR') || pair.endsWith('PKR')) {
    pipUSD = pipSize * contractSize * lots;
    if (!pair.endsWith('USD')) pipUSD = pipUSD / rate;
  } else pipUSD = pipSize * contractSize * lots;
  const acctRates = { USD:1, SAR:3.75, PKR:278 };
  const pipAcct = pipUSD * (acctRates[account]||1);
  document.getElementById('fx-result').style.display='block';
  document.getElementById('fx-pip-val').textContent = fmtCurrency(pipAcct, account==='SAR'?'SAR ':account==='PKR'?'PKR ':'$');
  document.getElementById('fx-lot-size').textContent = contractSize.toLocaleString() + ' units';
  document.getElementById('fx-total-tick').textContent = fmtCurrency(pipUSD*10,'$') + ' / 10 pips';
  document.getElementById('fx-note').textContent = 'Based on approx. rate ' + pair + ' ≈ ' + rate;
}

// ============================================================
// 2. POSITION SIZE
// ============================================================
function calcPosition() {
  const balance = parseFloat(document.getElementById('ps-balance').value);
  const riskPct = parseFloat(document.getElementById('ps-risk').value);
  const entry = parseFloat(document.getElementById('ps-entry').value);
  const stopLoss = parseFloat(document.getElementById('ps-stop').value);
  const pair = document.getElementById('ps-pair').value;
  if ([balance,riskPct,entry,stopLoss].some(v => isNaN(v)||v<=0)) return;
  if (entry === stopLoss) return;
  const riskAmount = balance * (riskPct/100);
  const pipRisk = Math.abs(entry-stopLoss);
  const isJPY = pair.includes('JPY');
  const pipSize = isJPY ? 0.01 : 0.0001;
  const pipsAtRisk = pipRisk / pipSize;
  const pipValuePerStdLot = pair.startsWith('USD') ? 10/entry : 10;
  const unitsRaw = riskAmount / (pipsAtRisk * pipValuePerStdLot/100000);
  const stdLots = unitsRaw/100000;
  const miniLots = unitsRaw/10000;
  const microLots = unitsRaw/1000;
  const target = entry + (entry-stopLoss)*2;
  document.getElementById('ps-result').style.display='block';
  document.getElementById('ps-risk-amount').textContent = '$' + fmt(riskAmount);
  document.getElementById('ps-std-lots').textContent = fmt(stdLots,2) + ' std lots';
  document.getElementById('ps-mini-lots').textContent = fmt(miniLots,2) + ' mini lots';
  document.getElementById('ps-micro-lots').textContent = fmt(microLots,2) + ' micro lots';
  document.getElementById('ps-pips').textContent = fmt(pipsAtRisk,1) + ' pips';
  document.getElementById('ps-target').textContent = fmt(target, isJPY?3:5) + ' (1:2 RR)';
}

// ============================================================
// 3. COMPOUND RETURN
// ============================================================
function calcCompound() {
  const principal = parseFloat(document.getElementById('cr-principal').value);
  const monthly = parseFloat(document.getElementById('cr-monthly').value) || 0;
  const rate = parseFloat(document.getElementById('cr-rate').value);
  const years = parseFloat(document.getElementById('cr-years').value);
  if ([principal,rate,years].some(v=>isNaN(v)||v<0)) return;
  if (years <= 0 || years > 50) return;
  const r = rate/100/12;
  const n = years*12;
  const fv = r===0 ? principal+monthly*n : principal*Math.pow(1+r,n) + monthly*((Math.pow(1+r,n)-1)/r);
  const invested = principal + monthly*n;
  const gain = fv - invested;
  const gainPct = (gain/invested)*100;
  document.getElementById('cr-result').style.display='block';
  document.getElementById('cr-final').textContent = '$' + fmt(fv);
  document.getElementById('cr-invested').textContent = '$' + fmt(invested);
  document.getElementById('cr-gain').textContent = '$' + fmt(gain);
  document.getElementById('cr-gain-pct').textContent = fmt(gainPct,1) + '%';
  const midN = Math.floor(n/2);
  const mid = r===0 ? principal+monthly*midN : principal*Math.pow(1+r,midN) + monthly*((Math.pow(1+r,midN)-1)/r);
  document.getElementById('cr-midpoint').textContent = '$' + fmt(mid) + ' at year ' + Math.floor(years/2);
}

// ============================================================
// 4. SIP
// ============================================================
function calcSIP() {
  const amt = parseFloat(document.getElementById('sip-amount').value);
  const rate = parseFloat(document.getElementById('sip-rate').value);
  const years = parseFloat(document.getElementById('sip-years').value);
  const cur = document.getElementById('sip-currency').value;
  if ([amt,rate,years].some(v=>isNaN(v)||v<=0)) return;
  const r = rate/100/12;
  const n = years*12;
  const fv = amt * ((Math.pow(1+r,n)-1)/r) * (1+r);
  const invested = amt*n;
  const gains = fv-invested;
  const sym = { USD:'$', PKR:'PKR ', SAR:'SAR ' }[cur] || '$';
  document.getElementById('sip-result').style.display='block';
  document.getElementById('sip-total').textContent = sym + fmt(fv);
  document.getElementById('sip-invested').textContent = sym + fmt(invested);
  document.getElementById('sip-returns').textContent = sym + fmt(gains);
  document.getElementById('sip-mult').textContent = fmt(fv/invested,2) + 'x growth';
}

// ============================================================
// 5. EMI / LOAN
// ============================================================
function calcEMI() {
  const principal = parseFloat(document.getElementById('emi-principal').value);
  const annual = parseFloat(document.getElementById('emi-rate').value);
  const tenureVal = parseFloat(document.getElementById('emi-tenure').value);
  const tenureType = document.getElementById('emi-tenure-type').value;
  const cur = document.getElementById('emi-currency').value;
  if ([principal,annual,tenureVal].some(v=>isNaN(v)||v<=0)) return;
  const months = tenureType==='years' ? tenureVal*12 : tenureVal;
  const r = annual/100/12;
  const emi = r===0 ? principal/months : principal*r*Math.pow(1+r,months)/(Math.pow(1+r,months)-1);
  const totalPay = emi*months;
  const totalInt = totalPay-principal;
  const intPct = (totalInt/principal)*100;
  const sym = { USD:'$', PKR:'PKR ', SAR:'SAR ', AED:'AED ' }[cur] || '$';
  document.getElementById('emi-result').style.display='block';
  document.getElementById('emi-monthly').textContent = sym + fmt(emi);
  document.getElementById('emi-total').textContent = sym + fmt(totalPay);
  document.getElementById('emi-interest').textContent = sym + fmt(totalInt);
  document.getElementById('emi-int-pct').textContent = fmt(intPct,1) + '% of principal';
}

// ============================================================
// 6. PSX ZAKAT
// ============================================================
function calcZakat() {
  const psx = parseFloat(document.getElementById('z-psx').value) || 0;
  const cash = parseFloat(document.getElementById('z-cash').value) || 0;
  const gold = parseFloat(document.getElementById('z-gold').value) || 0;
  const other = parseFloat(document.getElementById('z-other').value) || 0;
  const debts = parseFloat(document.getElementById('z-debts').value) || 0;
  const cur = document.getElementById('z-currency').value;
  const nisabRates = { PKR:153090, SAR:2204, USD:585 };
  const nisab = nisabRates[cur] || 153090;
  const total = psx+cash+gold+other;
  const net = Math.max(0, total-debts);
  const due = net >= nisab ? net*0.025 : 0;
  const below = net < nisab;
  const sym = { PKR:'PKR ', SAR:'SAR ', USD:'$' }[cur] || 'PKR ';
  document.getElementById('z-result').style.display='block';
  document.getElementById('z-total').textContent = sym + fmt(net);
  document.getElementById('z-nisab').textContent = sym + fmt(nisab) + ' (approx. silver nisab)';
  document.getElementById('z-due').textContent = below ? 'Below Nisab — no Zakat due' : sym + fmt(due);
  document.getElementById('z-due').style.color = below ? 'var(--body)' : 'var(--green)';
  document.getElementById('z-breakdown').textContent = `PSX: ${sym}${fmt(psx)} | Cash: ${sym}${fmt(cash)} | Gold: ${sym}${fmt(gold)}`;
}

// ============================================================
// 7. LOT SIZE CALCULATOR (Universal — Any Asset Class)
// Formula based on user's Excel template
// Quantity = (Equity × Risk%) / |Entry − Stop|
// Order Value = Quantity × Entry × Contract Size
// TP1 = Entry ± (Entry−Stop)        [1:1 RR]
// TP2 = Entry ± 2×(Entry−Stop)      [1:2 RR]
// TP3 = Entry ± 3×(Entry−Stop)      [1:3 RR]
// Sign follows trade direction (long: +, short: −)
// ============================================================
function calcLotSize() {
  const equity = parseFloat(document.getElementById('ls-equity').value);
  const riskPct = parseFloat(document.getElementById('ls-risk').value);
  const entry = parseFloat(document.getElementById('ls-entry').value);
  const stop = parseFloat(document.getElementById('ls-stop').value);
  const contractSize = parseFloat(document.getElementById('ls-contract').value) || 1;
  const direction = document.getElementById('ls-direction').value; // long | short | auto
  const assetClass = document.getElementById('ls-asset').value;
  const currency = document.getElementById('ls-currency').value;

  if ([equity,riskPct,entry,stop].some(v => isNaN(v) || v <= 0)) return;
  if (entry === stop) return;

  // Determine direction
  let dir = direction;
  if (dir === 'auto') dir = (entry > stop) ? 'long' : 'short';

  const distance = Math.abs(entry - stop);
  const riskFraction = riskPct / 100;
  const riskAmount = equity * riskFraction;
  const quantity = riskAmount / distance;
  const orderValue = quantity * entry * contractSize;

  // TPs in the direction of trade
  const sign = (dir === 'long') ? 1 : -1;
  const tp1 = entry + sign * distance * 1;
  const tp2 = entry + sign * distance * 2;
  const tp3 = entry + sign * distance * 3;

  // Reward at each TP (in account currency)
  const reward1 = riskAmount * 1;
  const reward2 = riskAmount * 2;
  const reward3 = riskAmount * 3;

  const sym = { USD:'$', PKR:'PKR ', SAR:'SAR ', AED:'AED ', EUR:'€' }[currency] || '$';
  const priceDecimals = entry < 5 ? 5 : entry < 100 ? 4 : entry < 1000 ? 2 : 2;

  // Smart quantity formatting based on asset class
  const qtyDecimals = quantity < 1 ? 6 : quantity < 100 ? 4 : 2;
  const qtyLabel = {
    forex: 'Lots',
    crypto: 'Units',
    stocks: 'Shares',
    commodities: 'Contracts',
    indices: 'Contracts',
    other: 'Units'
  }[assetClass] || 'Units';

  document.getElementById('ls-result').style.display = 'block';
  document.getElementById('ls-quantity').textContent = fmt(quantity, qtyDecimals) + ' ' + qtyLabel;
  document.getElementById('ls-order-value').textContent = sym + fmt(orderValue);
  document.getElementById('ls-risk-amount').textContent = sym + fmt(riskAmount);
  document.getElementById('ls-direction-display').textContent = dir.toUpperCase();
  document.getElementById('ls-direction-display').style.color = dir === 'long' ? 'var(--green)' : 'var(--red)';
  document.getElementById('ls-distance').textContent = fmt(distance, priceDecimals);

  // TP rows
  document.getElementById('ls-tp1').textContent = fmt(tp1, priceDecimals);
  document.getElementById('ls-tp1-reward').textContent = '+' + sym + fmt(reward1) + ' (1:1 RR)';
  document.getElementById('ls-tp2').textContent = fmt(tp2, priceDecimals);
  document.getElementById('ls-tp2-reward').textContent = '+' + sym + fmt(reward2) + ' (1:2 RR)';
  document.getElementById('ls-tp3').textContent = fmt(tp3, priceDecimals);
  document.getElementById('ls-tp3-reward').textContent = '+' + sym + fmt(reward3) + ' (1:3 RR)';
}
