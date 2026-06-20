/* ──────────────────────────────────────────────────────────────
   실시간.js — 베트남 시장 대시보드 (인도 대시보드 동일 구조)
   역할: RSI 계산, 뉴스 로드·분류, 시장데이터.json 캐시 초기화
   ────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  const MARKET_DESC = '베트남 증시(VN-Index)';
  let VNM_SCALE = 99.3;
  let _cachedVnindex = null;

  // ── CORS 프록시 ──
  const PROXIES = [
    u => 'https://corsproxy.io/?' + encodeURIComponent(u),
    u => 'https://api.allorigins.win/raw?url=' + encodeURIComponent(u),
    u => 'https://api.codetabs.com/v1/proxy?quest=' + encodeURIComponent(u),
  ];

  async function proxyText(url, ms = 8000) {
    for (const make of PROXIES) {
      try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), ms);
        const r = await fetch(make(url), { signal: ctrl.signal });
        clearTimeout(t);
        if (!r.ok) continue;
        const txt = await r.text();
        if (txt) return txt;
      } catch(e) {}
    }
    return null;
  }

  async function proxyJSON(url, ms = 8000) {
    const txt = await proxyText(url, ms);
    if (!txt) return null;
    try { return JSON.parse(txt); } catch(e) { return null; }
  }

  // ── 배지 헬퍼 ──
  function setBadge(id, text, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'badge ' + cls;
  }

  // ── RSI 계산 (인도 실시간.js 동일 구조) ──
  function calcRSI(prices, n) {
    if (prices.length < n + 1) return null;
    let gain = 0, loss = 0;
    for (let i = prices.length - n; i < prices.length; i++) {
      const diff = prices[i] - prices[i - 1];
      if (diff >= 0) gain += diff; else loss -= diff;
    }
    if (loss === 0) return 100;
    const rs = (gain / n) / (loss / n);
    return 100 - 100 / (1 + rs);
  }

  // ── 기술적 지표 — badge-rsi만 설정 (MA·mom·pos는 index.html 인라인에서 처리) ──
  function updateTechnicals(weeklyPrices) {
    if (!weeklyPrices || weeklyPrices.length < 15) return;
    const rsi = calcRSI(weeklyPrices, 14);
    if (rsi == null) return;
    let lbl, cls;
    if      (rsi >= 75) { lbl = 'RSI ' + rsi.toFixed(1) + ' — 과열';              cls = 'badge-r'; }
    else if (rsi >= 55) { lbl = 'RSI ' + rsi.toFixed(1) + ' — 중립';              cls = 'badge-b'; }
    else if (rsi >= 45) { lbl = 'RSI ' + rsi.toFixed(1) + ' — 중립';              cls = 'badge-b'; }
    else if (rsi >= 30) { lbl = 'RSI ' + rsi.toFixed(1) + ' — 약세';              cls = 'badge-y'; }
    else                { lbl = 'RSI ' + rsi.toFixed(1) + ' — 과매도(반등 기대)'; cls = 'badge-g'; }
    setBadge('badge-rsi', lbl, cls);
  }

  // ── 영문 → 한국어 번역 ──
  async function translateKo(text) {
    if (!text) return text;
    try {
      const r = await fetch('https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ko&dt=t&q=' + encodeURIComponent(text));
      if (!r.ok) return text;
      const j = await r.json();
      const out = (j[0] || []).map(x => x[0]).join('');
      return out || text;
    } catch(e) { return text; }
  }

  // ── 뉴스 피드 ──
  const NEWS_FEEDS = [
    { url: 'https://news.google.com/rss/search?q=베트남+증시+VN-Index&hl=ko&gl=KR&ceid=KR:ko', isKo: true },
    { url: 'https://news.google.com/rss/search?q=베트남+경제+투자&hl=ko&gl=KR&ceid=KR:ko', isKo: true },
  ];

  function relTime(ts) {
    if (!ts) return '';
    const diff = Date.now() / 1000 - ts;
    if (diff < 3600) return Math.max(1, Math.round(diff / 60)) + '분 전';
    if (diff < 86400) return Math.round(diff / 3600) + '시간 전';
    return Math.round(diff / 86400) + '일 전';
  }

  async function fetchNewsItems() {
    const sets = await Promise.all(NEWS_FEEDS.map(async f => {
      try {
        const xml = await proxyText(f.url, 10000);
        if (!xml) return [];
        const doc = new DOMParser().parseFromString(xml, 'text/xml');
        return [...doc.querySelectorAll('item')].slice(0, 12).map(item => {
          const g = tag => item.getElementsByTagName(tag)[0]?.textContent?.trim() || '';
          const pubDate = g('pubDate');
          return {
            title: g('title'),
            link: g('link') || g('guid'),
            isKo: !!f.isKo,
            ts: pubDate ? (new Date(pubDate).getTime() || 0) / 1000 : 0,
          };
        }).filter(x => x.title && x.link.startsWith('http'));
      } catch(e) { return []; }
    }));

    const EXCLUDE = ['한국 증시','코스피','코스닥','삼성전자'];
    const all = [], seen = new Set();
    sets.forEach(s => s.forEach(n => {
      if (EXCLUDE.some(kw => n.title.includes(kw))) return;
      const k = n.title.toLowerCase().slice(0, 60);
      if (seen.has(k)) return;
      seen.add(k); all.push(n);
    }));
    all.sort((a, b) => (b.ts || 0) - (a.ts || 0));
    return all.slice(0, 8);
  }

  function ensureNewsCard() {
    if (document.getElementById('major-news')) return;
    const anchor = document.querySelector('.section-label');
    if (!anchor || !anchor.parentNode) return;
    const card = document.createElement('div');
    card.className = 'card';
    card.style.marginBottom = '16px';
    card.innerHTML = '<div class="card-title">📰 주요 뉴스 <span style="font-size:11px;font-weight:400;color:var(--text3);">— 실시간 · 베트남 시장</span></div><div id="major-news"><div style="font-size:12px;color:var(--text3);">뉴스 불러오는 중…</div></div>';
    anchor.parentNode.insertBefore(card, anchor);
  }

  async function renderMajorNews() {
    ensureNewsCard();
    const box = document.getElementById('major-news');
    if (!box) return;
    const items = await fetchNewsItems();
    if (!items.length) {
      box.innerHTML = '<div style="font-size:12px;color:var(--text3);">뉴스를 불러오지 못했어요 (잠시 후 새로고침)</div>';
      return;
    }
    const kos = await Promise.all(items.map(n => n.isKo ? n.title : translateKo(n.title)));
    items.forEach((n, i) => { n.ko = (kos[i] || n.title).trim(); });
    window.__majorNewsItems = items;
    box.innerHTML = items.map(n => {
      const ko = (n.ko || n.title).replace(/&/g,'&amp;').replace(/</g,'&lt;');
      const meta = relTime(n.ts) || '';
      return `<a href="${n.link}" target="_blank" rel="noopener" style="display:block;padding:9px 0;border-bottom:0.5px solid var(--border);text-decoration:none;color:var(--text);"><div style="font-size:13px;line-height:1.45;">${ko}</div><div style="font-size:11px;color:var(--text3);margin-top:3px;">${meta} ↗</div></a>`;
    }).join('');
  }

  // ── 뉴스 배지 자동 분류 (API 키 없을 때 키워드 기반 / 있을 때 AI 위임) ──
  async function updateNewsBadgesFromKorean() {
    const items = window.__majorNewsItems || [];
    if (!items.length) return;

    const hasKey = !!localStorage.getItem('anthropic_api_key');

    // API 키 있으면 AI가 sbv/cpi/gdp/fed/trade/china 담당 → 여기서 덮어쓰지 않음
    // API 키 없으면 키워드 기반으로 모두 분류
    const all = items.map(n => n.ko || n.title || '').join(' ');

    function ko(id, gKw, rKw, gT, rT, nT) {
      // 키워드 기반으로 항상 먼저 세팅 (API 키 있어도) → AI 성공 시 덮어씀
      const isG = gKw.some(k => all.includes(k));
      const isR = rKw.some(k => all.includes(k));
      let cls, text;
      if      (isG && !isR) { cls = 'badge-g'; text = gT; }
      else if (isR && !isG) { cls = 'badge-r'; text = rT; }
      else if (isG && isR)  { cls = 'badge-y'; text = nT; }
      else                   { cls = 'badge-y'; text = nT; }
      setBadge(id, text, cls);
    }

    ko('badge-sbv',
      ['금리 인하','완화','SBV 인하','인하 기대','통화 완화','피벗'],
      ['금리 인상','긴축','SBV 인상','인상 우려','매파'],
      'SBV 완화(호재)', 'SBV 긴축(악재)', 'SBV 정책 관망');

    ko('badge-cpi',
      ['물가 안정','인플레 완화','물가 하락','CPI 하락','디스인플레'],
      ['물가 상승','인플레 급등','물가 급등','CPI 상승','인플레 우려'],
      '물가 안정(호재)', '물가 상승(악재)', '물가 혼조');

    ko('badge-gdp',
      ['GDP 성장','경제성장','성장률 상승','경기 호조','경기 반등','경제 회복'],
      ['GDP 둔화','성장 둔화','경기 침체','성장률 하락','경기 부진'],
      'GDP 성장(호재)', 'GDP 둔화(악재)', 'GDP 관망');

    ko('badge-fed',
      ['연준 인하','금리 인하','파월 완화','연준 완화','연준 피벗'],
      ['연준 인상','연준 긴축','파월 매파','Fed 긴축','금리 동결'],
      '연준 완화(호재)', '연준 긴축(악재)', '연준 불확실');

    ko('badge-trade',
      ['무역 협상','관세 완화','무역 합의','수출 증가','관세 면제','무역 타결'],
      ['관세 부과','무역 갈등','무역 제재','수출 감소','관세 위협','관세 인상'],
      '무역 호조(호재)', '무역 리스크(악재)', '무역 주시');

    ko('badge-china',
      ['중국 협력','중국 투자','중-베 협력','위안 안정','중국 완화'],
      ['중국 갈등','중국 리스크','위안 급락','중국 긴장','중-베 마찰'],
      '중국 협력(호재)', '중국 리스크(악재)', '중국 관계 관망');

    // fdi, semi는 AI가 안 다루므로 키워드로 항상 분류
    function koAlways(id, gKw, rKw, gT, rT, nT) {
      const isG = gKw.some(k => all.includes(k));
      const isR = rKw.some(k => all.includes(k));
      let cls, text;
      if      (isG && !isR) { cls = 'badge-g'; text = gT; }
      else if (isR && !isG) { cls = 'badge-r'; text = rT; }
      else if (isG && isR)  { cls = 'badge-y'; text = nT; }
      else                   { cls = 'badge-y'; text = nT; }
      setBadge(id, text, cls);
    }

    koAlways('badge-fdi',
      ['FDI 증가','외국인 투자 증가','외자 유입','투자 유치','투자 증가'],
      ['FDI 감소','외국인 투자 감소','투자 이탈','투자 감소'],
      'FDI 유입(호재)', 'FDI 감소(악재)', 'FDI 관망');

    koAlways('badge-semi',
      ['삼성 투자','반도체','제조업 호조','인텔 투자','공장 증설','제조업 성장'],
      ['공장 이전','제조업 감소','생산 감소','공장 철수'],
      '제조업 유입(호재)', '제조업 감소(악재)', '제조업 주시');

    const note = document.getElementById('news-live-note');
    if (note) note.textContent = hasKey ? '✓ AI 뉴스 분석 중...' : '✓ 최신 뉴스 기반 자동 분류';

    // API 키 있으면 AI 분석 실행 (index.html의 updateAI 재호출)
    if (hasKey) {
      try {
        if (typeof updateAI === 'function' && typeof _liveData !== 'undefined') {
          await updateAI(_liveData);
          const noteEl = document.getElementById('news-live-note');
          if (noteEl) noteEl.textContent = '✓ AI 뉴스 분석 완료';
        }
      } catch(e) {}
    }

    try { if (typeof recalcScorecard === 'function') recalcScorecard(); } catch(e) {}
  }

  // ── 시장데이터.json 초기값 설정 (인도와 동일 패턴) ──
  async function loadCachedMarketData() {
    try {
      const res = await fetch('시장데이터.json?t=' + Date.now());
      if (!res.ok) return;
      const d = await res.json();
      if (!d || !d.vnindex) return;
      _cachedVnindex = d.vnindex;

      // VNM 현재가 → 동적 스케일 계산
      try {
        const j = await proxyJSON('https://query2.finance.yahoo.com/v8/finance/chart/VNM?interval=1d&range=1d', 6000);
        if (j && j.chart && j.chart.result) {
          const vnmPrice = j.chart.result[0].meta.regularMarketPrice;
          if (vnmPrice && _cachedVnindex > 500) {
            VNM_SCALE = _cachedVnindex / vnmPrice;
            if (typeof window._vnmScale !== 'undefined') window._vnmScale = VNM_SCALE;
          }
        }
      } catch(e) {}

      // 배지 초기값 (실시간 데이터 전까지 보여줄 캐시값)
      const ma = d.ma_signal || '';
      setBadge('badge-ma',
        ma.includes('정배열') ? '정배열(상승)' : ma.includes('역배열') ? '역배열(하락)' : '혼조',
        ma.includes('정배열') ? 'badge-g' : ma.includes('역배열') ? 'badge-r' : 'badge-y');

      const rsi = d.rsi || 50;
      setBadge('badge-rsi',
        `RSI ${rsi} — ${rsi <= 40 ? '과매도(반등 기대)' : rsi >= 70 ? '과열' : '중립'}`,
        rsi <= 40 ? 'badge-g' : rsi >= 70 ? 'badge-r' : 'badge-y');

      const mom = d.mom4 || 0;
      setBadge('badge-mom',
        mom >= 0 ? `▲ ${Math.abs(mom).toFixed(1)}% (4주 변화)` : `▼ ${Math.abs(mom).toFixed(1)}% (4주 변화)`,
        mom >= 2 ? 'badge-g' : mom <= -2 ? 'badge-r' : 'badge-y');

      const fhi = d.from_hi || 0;
      setBadge('badge-pos',
        `고점 대비 ${fhi.toFixed(1)}%`,
        fhi <= -20 ? 'badge-g' : fhi >= -3 ? 'badge-r' : 'badge-y');

      const vix_u = d.us_vix || 0;
      if (vix_u) setBadge('badge-vix', `US VIX ${vix_u} — ${vix_u < 18 ? '안정' : vix_u > 25 ? '공포' : '불안'}`, vix_u < 18 ? 'badge-g' : vix_u > 25 ? 'badge-r' : 'badge-y');

      const crude = d.crude || 0;
      if (crude) setBadge('badge-crude', `$${crude} — ${crude > 90 ? '고유가(부담)' : crude > 80 ? '보통' : '저유가(호재)'}`, crude > 90 ? 'badge-r' : crude > 80 ? 'badge-y' : 'badge-g');

      const vnd = d.vnd || 0;
      if (vnd) setBadge('badge-usdvnd', `₫${vnd.toLocaleString()} — ${vnd > 26500 ? '동 급락' : vnd > 25500 ? '동 약세' : '안정'}`, vnd > 26500 ? 'badge-r' : vnd > 25500 ? 'badge-y' : 'badge-g');

      // 종합신호 초기값
      const scEmoji = document.getElementById('sc-emoji');
      const scPct   = document.getElementById('sc-pct');
      const scBar   = document.getElementById('sc-bar');
      if (scEmoji && d.score_emoji && d.score_label) scEmoji.textContent = `${d.score_emoji} ${d.score_label}`;
      if (scPct   && d.score_pct != null) scPct.textContent = `${d.score_pct}점`;
      if (scBar   && d.score_pct != null) { scBar.style.width = `${d.score_pct}%`; }

      try { if (typeof recalcScorecard === 'function') recalcScorecard(); } catch(e) {}
    } catch(e) {}
  }

  // ── 메인 실행 ──
  async function runRealtime() {
    await loadCachedMarketData().catch(() => {});

    // VNM 주봉 1년 데이터로 RSI 계산
    try {
      const j = await proxyJSON('https://query2.finance.yahoo.com/v8/finance/chart/VNM?interval=1wk&range=1y', 9000);
      if (j && j.chart && j.chart.result && j.chart.result[0]) {
        const raw = j.chart.result[0].indicators.quote[0].close || [];
        const weekly = raw.filter(p => p != null).map(p => p * VNM_SCALE);
        if (weekly.length >= 15) updateTechnicals(weekly);
      }
    } catch(e) {}

    // 뉴스
    try { await renderMajorNews(); } catch(e) {}
    try { updateNewsBadgesFromKorean(); } catch(e) {}

    // 점수 재계산
    try { if (typeof recalcScorecard === 'function') recalcScorecard(); } catch(e) {}

    // 룰 기반 분석 (AI 키 없을 때)
    await new Promise(r => setTimeout(r, 800));
    try {
      if (typeof applyAnalysis === 'function' && typeof ruleBasedAnalysis === 'function' && typeof _liveData !== 'undefined') {
        if (!localStorage.getItem('anthropic_api_key')) applyAnalysis(ruleBasedAnalysis(_liveData));
      }
    } catch(e) {}
  }

  // ── 초기화 ──
  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', () => setTimeout(runRealtime, 400));
  } else {
    setTimeout(runRealtime, 400);
  }
  setInterval(runRealtime, 5 * 60 * 1000);
})();
