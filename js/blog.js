/* blog.js — MoneyTailors */

const POSTS_URL = 'https://raw.githubusercontent.com/ABSHOUKAT/moneytailors-site/main/content/posts.json';

// ---- Insight listing page ----
async function loadInsights(containerId, limit = 0, filterCat = '') {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = '<div class="spinner"></div>';

  try {
    const res   = await fetch(POSTS_URL + '?v=' + Date.now());
    const posts = await res.json();

    let filtered = posts;
    if (filterCat) filtered = posts.filter(p => p.category === filterCat);
    if (limit > 0) filtered = filtered.slice(0, limit);

    if (!filtered.length) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="icon">📊</div>
          <h3>Analysis incoming</h3>
          <p>Market insights and research will appear here soon.</p>
        </div>`;
      return;
    }

    container.innerHTML = filtered.map(post => buildInsightCard(post)).join('');

  } catch (e) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="icon">📡</div>
        <h3>Could not load posts</h3>
        <p>Please refresh the page to try again.</p>
      </div>`;
  }
}

function buildInsightCard(post) {
  const tagClass = 'tag-' + (post.category || 'analysis').toLowerCase();
  const url      = 'post.html?slug=' + post.slug;
  const dateStr  = formatDate(post.date);
  return `
    <a class="insight-card" href="${url}">
      <div class="insight-meta">
        <span class="tag ${tagClass}">${post.category || 'Analysis'}</span>
        <span class="insight-date mono">${dateStr}</span>
      </div>
      <div class="insight-body">
        <div class="insight-title">${escHtml(post.title)}</div>
        <div class="insight-excerpt">${escHtml(post.excerpt || '')}</div>
      </div>
    </a>`;
}

// ---- Single post page ----
async function loadPost() {
  const params  = new URLSearchParams(window.location.search);
  const slug    = params.get('slug');
  const wrapper = document.getElementById('post-wrapper');
  if (!wrapper || !slug) return;

  wrapper.innerHTML = '<div class="spinner"></div>';

  try {
    const res   = await fetch(POSTS_URL + '?v=' + Date.now());
    const posts = await res.json();
    const post  = posts.find(p => p.slug === slug);

    if (!post) {
      wrapper.innerHTML = '<div class="empty-state"><h3>Post not found</h3><p><a href="insights.html" style="color:var(--cyan)">Back to Insights</a></p></div>';
      return;
    }

    // Update page meta
    document.title = post.title + ' | MoneyTailors';

    const tagClass = 'tag-' + (post.category || 'analysis').toLowerCase();
    wrapper.innerHTML = `
      <div class="post-header" style="margin-bottom:40px">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:18px">
          <span class="tag ${tagClass}">${post.category || 'Analysis'}</span>
          <span class="mono" style="font-size:12px;color:var(--body)">${formatDate(post.date)}</span>
        </div>
        <h1 style="font-family:var(--font-h);font-size:clamp(26px,4vw,40px);font-weight:700;color:var(--primary);line-height:1.15;letter-spacing:-0.5px;margin-bottom:16px">${escHtml(post.title)}</h1>
        <p style="font-size:16px;color:var(--body);line-height:1.7;max-width:680px">${escHtml(post.excerpt || '')}</p>
        <hr style="border:none;border-top:1px solid var(--rim);margin-top:28px">
      </div>
      <div class="post-content" style="max-width:720px">${post.content || '<p>Full article content coming soon.</p>'}</div>
      <div style="margin-top:48px;padding-top:24px;border-top:1px solid var(--rim)">
        <a href="insights.html" class="btn btn-outline">← Back to Insights</a>
      </div>`;

  } catch (e) {
    wrapper.innerHTML = '<div class="empty-state"><h3>Failed to load post</h3></div>';
  }
}

// ---- Category filter ----
function initCategoryFilter() {
  document.querySelectorAll('[data-filter]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const cat = btn.dataset.filter;
      loadInsights('insights-grid', 0, cat === 'all' ? '' : cat);
    });
  });
}

// ---- Helpers ----
function formatDate(dateStr) {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  } catch { return dateStr; }
}

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
