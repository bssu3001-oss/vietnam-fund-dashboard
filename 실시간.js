/* ──────────────────────────────────────────────────────────────
   실시간.js — 베트남 시장 대시보드
   페이지 열 때마다 차트 과거추이·기술지표·뉴스신호를 실시간 갱신.
   원칙: 어떤 호출이 실패해도 화면이 깨지거나 빈칸이 되지 않고
        직전 값/정적값을 그대로 유지한다.
   VN-Index = VNM ETF × 99.5744 로 추정 (Yahoo Finance에 ^VNINDEX 없음)
   ────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  var VNM_SCALE = 99.5744;

  // ── 여러 CORS 프록시를 순서대로 시도 (하나 막혀도 다음으로) ──
  var PROXIES = [
    function(u) { return 'https://corsproxy.io/?'+encodeURIComponent(u); },
    function(u) { return 'https://api.allorigins.win/raw?url='+encodeURIComponent(u); },
    function(u) { return 'https://api.codetabs.com/v1/proxy?quest='+encodeURIComponent(u); },
  ];

  async function proxyText(url, timeoutMs) {
    for (var i=0; i<PROXIES.length; i++) {
      var make = PROXIES[i];
      try {
        var ctrl = new AbortController();
        var t = setTimeout(function(){ ctrl.abort(); }, timeoutMs || 8000);
        var r = await fetch(make(url), { signal: ctrl.signal });
        clearTimeout(t);
        if (!r.ok) continue;
        var txt = await r.text();
        if (txt && txt.length > 0) return txt;
      } catch (e) { /* 다음 프록시 시도 */ }
    }
    return null;
  }

  async function proxyJSON(url, timeoutMs) {
    var txt = await proxyText(url, timeoutMs);
    if (!txt) return null;
    try { return JSON.parse(txt); } catch (e) { return null; }
  }

  // 영문 → 한국어 번역 (구글 번역)
  async function translateKo(text) {
    if (!text) return text;
    try {
      var r = await fetch('https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ko&dt=t&q='+encodeURIComponent(text));
      if (!r.ok) return text;
      var j = await r.json();
      var out = (j[0] || []).map(function(x){ return x[0]; }).join('');
      return out || text;
    } catch (e) { return text; }
  }

  var MARKET_DESC = '베트남 증시(VN-Index)';

  // ── 야후 차트 1구간 가져와서 {labels, prices} 로 변환 (VNM ETF → VN-Index 변환 포함) ──
  async function fetchRange(ticker, interval, range, labelMode, scale) {
    var url = 'https://query2.finance.yahoo.com/v8/finance/chart/'+ticker+'?interval='+interval+'&range='+range;
    var j = await proxyJSON(url, 9000);
    try {
      var res = j.chart.result[0];
      var ts = res.timestamp || [];
      var closes = res.indicators.quote[0].close || [];
      var labels = [], prices = [];
      for (var i = 0; i < ts.length; i++) {
        if (closes[i] == null) continue;
        var dt = new Date(ts[i] * 1000);
        var lab;
        if (labelMode === 'time') {
          lab = dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
        } else {
          lab = (dt.getMonth() + 1) + '/' + dt.getDate();
        }
        labels.push(lab);
        var p = closes[i];
        if (scale) p = p * scale;
        prices.push(+p.toFixed(scale ? 0 : 2));
      }
      if (prices.length < 2) return null;
      return { labels: labels, prices: prices, meta: res.meta };
    } catch (e) { return null; }
  }

  // 구간 정의 (대시보드 탭과 1:1)
  var RANGE_DEFS = [
    { key: 'd1',  interval: '1d',  range: '5d',  mode: 'date' },
    { key: 'd5',  interval: '1d',  range: '5d',  mode: 'date' },
    { key: 'd30', interval: '1d',  range: '1mo', mode: 'date' },
    { key: 'mo3', interval: '1d',  range: '3mo', mode: 'date' },
    { key: 'mo6', interval: '1wk', range: '6mo', mode: 'date' },
    { key: 'yr1', interval: '1wk', range: '1y',  mode: 'date' },
  ];

  // ── 차트 한 개를 실시간 데이터로 갱신 ──
  async function refreshChart(canvasId, ticker, scale) {
    var c = window._charts && window._charts[canvasId];
    if (!c) return null;
    var lastMeta = null;
    var tasks = RANGE_DEFS.map(async function(d) {
      var got = await fetchRange(ticker, d.interval, d.range, d.mode, scale);
      if (got) {
        c.data[d.key] = { labels: got.labels, prices: got.prices };
        if (d.key === 'yr1' && got.meta) lastMeta = got.meta;
      }
    });
    await Promise.allSettled(tasks);
    try {
      var key = 'd1';
      if (c.data[key] && typeof makeDatasets === 'function') {
        c.inst.data.labels = c.data[key].labels;
        c.inst.data.datasets = makeDatasets(c.data[key].prices, key);
        c.inst.update();
      }
    } catch (e) {}
    return lastMeta;
  }

  // ── 기술적 지표 계산 (주봉 yr1 기반) ──
  function setBadge(id, text, cls) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'badge ' + cls;
  }

  function calcRSI(prices, n) {
    if (prices.length < n + 1) return null;
    var gain = 0, loss = 0;
    for (var i = prices.length - n; i < prices.length; i++) {
      var diff = prices[i] - prices[i - 1];
      if (diff >= 0) gain += diff; else loss -= diff;
    }
    if (loss === 0) return 100;
    var rs = (gain / n) / (loss / n);
    return 100 - 100 / (1 + rs);
  }

  function sma(prices, n) {
    if (prices.length < n) return null;
    var s = prices.slice(prices.length - n);
    return s.reduce(function(a, b){ return a + b; }, 0) / n;
  }

  function updateTechnicals(meta, weeklyPrices) {
    if (!weeklyPrices || weeklyPrices.length < 6) return;
    var cur = weeklyPrices[weeklyPrices.length - 1];

    // RSI (14주)
    var rsi = calcRSI(weeklyPrices, 14);
    if (rsi != null) {
      var lbl, cls;
      if (rsi >= 75)      { lbl = '과열';            cls = 'badge-r'; }
      else if (rsi >= 55) { lbl = '중립';            cls = 'badge-b'; }
      else if (rsi >= 45) { lbl = '중립';            cls = 'badge-b'; }
      else if (rsi >= 30) { lbl = '약세';            cls = 'badge-y'; }
      else                { lbl = '과매도 — 반등 기대'; cls = 'badge-g'; }
      setBadge('badge-rsi', 'RSI ' + rsi.toFixed(1) + ' — ' + lbl, cls);
    }

    // 이평선 배열 (MA5 / MA13 / MA26 주봉)
    var ma5 = sma(weeklyPrices, 5), ma13 = sma(weeklyPrices, 13), ma26 = sma(weeklyPrices, 26);
    if (ma5 != null && ma13 != null && ma26 != null) {
      var maLbl, maCls;
      if (cur > ma5 && ma5 > ma13 && ma13 > ma26)      { maLbl = '정배열(상승)'; maCls = 'badge-g'; }
      else if (cur < ma5 && ma5 < ma13 && ma13 < ma26) { maLbl = '역배열(하락)'; maCls = 'badge-r'; }
      else                                               { maLbl = '혼조';        maCls = 'badge-y'; }
      setBadge('badge-ma', maLbl, maCls);
    }

    // 단기 모멘텀 (4주 변화)
    if (weeklyPrices.length >= 5) {
      var past = weeklyPrices[weeklyPrices.length - 5];
      var mom = (cur - past) / past * 100;
      var momArrow = mom >= 0 ? '▲' : '▼';
      var momCls;
      if (mom >= 2) momCls = 'badge-g'; else if (mom <= -2) momCls = 'badge-r'; else momCls = 'badge-y';
      setBadge('badge-mom', momArrow + ' ' + Math.abs(mom).toFixed(1) + '% (4주)', momCls);
    }

    // 변동성 (12주 주간수익률 표준편차)
    if (weeklyPrices.length >= 13) {
      var rets = [];
      for (var i = weeklyPrices.length - 12; i < weeklyPrices.length; i++) {
        rets.push((weeklyPrices[i] - weeklyPrices[i-1]) / weeklyPrices[i-1] * 100);
      }
      var mean = rets.reduce(function(a,b){return a+b;},0) / rets.length;
      var std = Math.sqrt(rets.reduce(function(a,b){return a+(b-mean)*(b-mean);},0) / rets.length);
      var volCls = std > 3 ? 'badge-r' : std > 1.5 ? 'badge-y' : 'badge-g';
      setBadge('badge-vol', '주간 ±' + std.toFixed(2) + '% — ' + (std>3?'고변동':std>1.5?'보통':'저변동'), volCls);
    }

    // 52주 가격 위치
    var hi = meta && meta.fiftyTwoWeekHigh, lo = meta && meta.fiftyTwoWeekLow;
    if (hi) hi *= VNM_SCALE;
    if (lo) lo *= VNM_SCALE;
    if (!hi || !lo) { hi = Math.max.apply(null, weeklyPrices); lo = Math.min.apply(null, weeklyPrices); }
    if (hi && lo && hi > lo) {
      var fromHi = (cur - hi) / hi * 100;
      var fromLo = (cur - lo) / lo * 100;
      var pos = (cur - lo) / (hi - lo);
      var posCls;
      if (pos < 0.5) posCls = 'badge-g'; else if (pos > 0.85) posCls = 'badge-y'; else posCls = 'badge-b';
      setBadge('badge-pos', '고점 대비 ' + fromHi.toFixed(1) + '% / 저점 대비 +' + fromLo.toFixed(1) + '%', posCls);
    }
  }

  // ── AI 키 헬퍼 ──
  function getAnthropicKey() { return localStorage.getItem('anthropic_api_key') || ''; }

  // ── AI 뉴스 신호 분류 (Anthropic 키 있을 때만) ──
  async function updateNewsSignals() {
    var key = getAnthropicKey();
    if (!key) {
      var note = document.getElementById('news-live-note');
      if (note) note.textContent = '🔑 AI 키 입력 시 뉴스 신호가 실시간 갱신됩니다';
      return;
    }
    var items = window.__majorNewsItems || [];
    var newsBlock = items.slice(0, 8).map(function(n){ return '- ' + (n.title || n.ko); }).join('\n');
    if (!newsBlock) return;

    var sys = '당신은 베트남 증시 뉴스 분석가입니다. 주어진 헤드라인을 보고 각 항목을 평가하세요. 반드시 JSON만 출력합니다.';
    var prompt = '아래는 오늘 베트남 증시 관련 실제 헤드라인입니다.\n'+newsBlock+'\n\n이 뉴스들을 근거로 각 항목(fii=외국인자금, sbv=SBV금리, trade=미국무역, cpi=물가, gdp=성장, fed=연준, geo=지정학)에 대해 한국어 12자 이내 label 과 베트남 증시 영향 sentiment(good=호재, bad=악재, neutral=중립)를 매기세요. 관련 뉴스가 없으면 neutral.\n다음 형식의 JSON만 출력:\n{"fii":{"label":"...","sentiment":"good|bad|neutral"}, "sbv":{...}, "trade":{...}, "cpi":{...}, "gdp":{...}, "fed":{...}, "geo":{...}}';

    try {
      var r = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
        body: JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 600, system: sys, messages: [{ role: 'user', content: prompt }] }),
      });
      var d = await r.json();
      var text = d.content && d.content[0] && d.content[0].text || '';
      var m = text.match(/\{[\s\S]*\}/);
      if (!m) return;
      var obj = JSON.parse(m[0]);
      var sentCls = { good: 'badge-g', bad: 'badge-r', neutral: 'badge-y' };
      Object.keys(obj).forEach(function(k) {
        var v = obj[k];
        if (!v || !v.label) return;
        setBadge('badge-' + k, v.label, sentCls[v.sentiment] || 'badge-y');
      });
      var note = document.getElementById('news-live-note');
      if (note) note.textContent = '✓ 뉴스 신호 방금 갱신됨';
    } catch (e) {}
  }

  // ── AI 차트 분석 카드 자동 작성 ──
  function buildAnalysis(name, weekly, d5, meta) {
    var el = document.getElementById('ai-chart-analysis');
    if (!el || !weekly || weekly.length < 14) return;
    var cur = weekly[weekly.length - 1];
    var pct = null;
    if (d5 && d5.length >= 2) pct = (d5[d5.length-1] - d5[d5.length-2]) / d5[d5.length-2] * 100;
    var rsi = calcRSI(weekly, 14);
    var ma5 = sma(weekly, 5), ma13 = sma(weekly, 13), ma26 = sma(weekly, 26);
    var maState = '혼조';
    if (cur > ma5 && ma5 > ma13 && ma13 > ma26) maState = '정배열(상승)';
    else if (cur < ma5 && ma5 < ma13 && ma13 < ma26) maState = '역배열(하락)';
    var mom = weekly.length >= 5 ? (cur - weekly[weekly.length-5]) / weekly[weekly.length-5] * 100 : 0;
    var std = 0;
    if (weekly.length >= 13) {
      var rets = [];
      for (var i = weekly.length-12; i < weekly.length; i++) rets.push((weekly[i]-weekly[i-1])/weekly[i-1]*100);
      var mean = rets.reduce(function(a,b){return a+b;},0) / rets.length;
      std = Math.sqrt(rets.reduce(function(a,b){return a+(b-mean)*(b-mean);},0) / rets.length);
    }
    var hi = meta && meta.fiftyTwoWeekHigh ? meta.fiftyTwoWeekHigh * VNM_SCALE : Math.max.apply(null,weekly);
    var lo = meta && meta.fiftyTwoWeekLow  ? meta.fiftyTwoWeekLow  * VNM_SCALE : Math.min.apply(null,weekly);
    var fromHi = (cur-hi)/hi*100, fromLo = (cur-lo)/lo*100;
    var posRatio = (cur-lo)/(hi-lo);
    var today = new Date().toLocaleDateString('ko-KR', { year:'numeric', month:'long', day:'numeric' });
    var rsiLvl = !rsi ? '계산 중' : rsi>=70?'과열권':rsi>=55?'중립대 상단':rsi>=45?'중립':rsi>=30?'약세':'과매도권';
    var momLvl = mom>=2?'견조한 상승 동력':mom>=0?'약한 상승 힘':mom>-2?'약한 하락 압력':'뚜렷한 하락 압력';
    var volLvl = std<1?'낮은':std<2?'보통':'높은';
    var posLvl = posRatio<0.4?'저점 부근':posRatio>0.8?'고점 부근':'중간값 근처';
    var concl;
    if (maState.indexOf('정배열') >= 0 && mom > 0) concl = '추세·모멘텀이 우호적이라 분할 매수를 고려할 만합니다.';
    else if (maState.indexOf('역배열') >= 0) concl = '추세가 약해 신규 진입보다 반등 확인 후 대응이 바람직합니다.';
    else concl = '방향성이 불명확해 의미 있는 신호 전까지 관망이 최선입니다.';
    var fmtN = function(n) { return Math.round(n).toLocaleString('ko-KR'); };
    var issueLine = (window.__majorNewsItems && window.__majorNewsItems.length)
      ? '• <strong>주요 이슈</strong>: '+window.__majorNewsItems.slice(0,2).map(function(n){return n.ko||n.title;}).join(' / ')+'<br><br>' : '';
    el.innerHTML =
      '# '+name+' 주간 차트 분석 ('+today+')<br><br>' +
      issueLine +
      '• <strong>현재 지수</strong>: '+fmtN(cur)+(pct!=null?' — 전일 대비 '+(pct>=0?'+':'')+pct.toFixed(2)+'%':'')+'<br><br>' +
      '• <strong>추세 (이평)</strong>: 5주·13주·26주 이평 기준 <strong>'+maState+'</strong>'+(maState==='혼조'?' — 방향성 불명확':'')+'<br><br>' +
      '• <strong>모멘텀</strong>: RSI '+(rsi?rsi.toFixed(1):'N/A')+' ('+rsiLvl+'), 4주 모멘텀 '+(mom>=0?'+':'')+mom.toFixed(1)+'% — '+momLvl+'<br><br>' +
      '• <strong>변동성</strong>: 주간 ±'+std.toFixed(2)+'%로 '+volLvl+' 수준<br><br>' +
      '• <strong>위치</strong>: 52주 고점('+fmtN(hi)+') 대비 '+fromHi.toFixed(1)+'%, 저점('+fmtN(lo)+') 대비 +'+fromLo.toFixed(1)+'% — '+posLvl+'<br><br>' +
      '• <strong>한 줄 결론</strong>: '+concl+'<br><br>' +
      '<span style="color:var(--text3);font-size:11px;">* 열 때마다 실시간 지표로 자동 작성됩니다</span>';
  }

  // ── 주요 뉴스 (제목+링크, 열 때마다 실시간) ──
  var NEWS_FEEDS = [
    { url: 'https://news.google.com/rss/search?q=%EB%B2%A0%ED%8A%B8%EB%82%A8+%EC%A6%9D%EC%8B%9C&hl=ko&gl=KR&ceid=KR:ko', source: '구글뉴스', isKo: true },
    { url: 'https://news.google.com/rss/search?q=VN-Index+%EB%B2%A0%ED%8A%B8%EB%82%A8&hl=ko&gl=KR&ceid=KR:ko', source: '구글뉴스', isKo: true },
  ];

  function relTime(ts) {
    if (!ts) return '';
    var diff = Date.now() / 1000 - ts;
    if (diff < 3600) return Math.max(1, Math.round(diff / 60)) + '분 전';
    if (diff < 86400) return Math.round(diff / 3600) + '시간 전';
    return Math.round(diff / 86400) + '일 전';
  }

  async function fetchNewsItems() {
    var sets = await Promise.all(NEWS_FEEDS.map(async function(f) {
      try {
        var r = await fetch('https://api.rss2json.com/v1/api.json?rss_url='+encodeURIComponent(f.url), {signal: AbortSignal.timeout(8000)});
        if (!r.ok) return [];
        var d = await r.json();
        return (d.items || []).slice(0, 12).map(function(it) {
          return {
            title: (it.title || '').trim(),
            link: (it.link || it.guid || '').trim(),
            source: f.source,
            isKo: !!f.isKo,
            ts: it.pubDate ? (new Date(it.pubDate).getTime() || 0) / 1000 : 0,
          };
        }).filter(function(x){ return x.title && x.link.startsWith('http'); });
      } catch (e) { return []; }
    }));

    var EXCLUDE = ['한국 증시', '코스피', '코스닥', '삼성전자', '한국 주식'];
    var all = [], seen = new Set();
    sets.forEach(function(s) {
      s.forEach(function(n) {
        var t = n.title;
        if (EXCLUDE.some(function(kw){ return t.includes(kw); })) return;
        var k = t.toLowerCase().slice(0, 60);
        if (seen.has(k)) return;
        seen.add(k); all.push(n);
      });
    });
    all.sort(function(a, b){ return (b.ts || 0) - (a.ts || 0); });
    return all.slice(0, 8);
  }

  function ensureNewsCard() {
    if (document.getElementById('major-news')) return;
    var anchor = document.querySelector('.section-label') || document.querySelector('.main-header');
    if (!anchor || !anchor.parentNode) return;
    var card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = '<div class="card-title">📰 주요 뉴스 <span style="font-size:11px;font-weight:400;color:var(--text3);">— 실시간 · 베트남 시장</span></div><div id="major-news"><div style="font-size:12px;color:var(--text3);">뉴스 불러오는 중…</div></div>';
    anchor.parentNode.insertBefore(card, anchor);
  }

  async function renderMajorNews() {
    ensureNewsCard();
    var box = document.getElementById('major-news');
    if (!box) return;
    var items = await fetchNewsItems();
    if (!items.length) {
      box.innerHTML = '<div style="font-size:12px;color:var(--text3);">뉴스를 불러오지 못했어요 (잠시 후 새로고침)</div>';
      return;
    }
    var kos = await Promise.all(items.map(function(n){ return n.isKo ? n.title : translateKo(n.title); }));
    items.forEach(function(n, i){ n.ko = (kos[i] || n.title).trim(); });
    window.__majorNewsItems = items;
    window.__majorNews = items.slice(0, 6).map(function(n){ return '• ' + n.ko; }).join('\n');
    box.innerHTML = items.map(function(n) {
      var ko = (n.ko || n.title).replace(/&/g, '&amp;').replace(/</g, '&lt;');
      var meta = [n.source, relTime(n.ts)].filter(Boolean).join(' · ');
      return '<a href="'+n.link+'" target="_blank" rel="noopener" style="display:block;padding:9px 0;border-bottom:0.5px solid var(--border);text-decoration:none;color:var(--text);"><div style="font-size:13px;line-height:1.45;">'+ko+'</div><div style="font-size:11px;color:var(--text3);margin-top:3px;">'+meta+' ↗</div></a>';
    }).join('');
  }

  // ── 한국어 뉴스 키워드로 뉴스 배지 자동 분류 (API 키 불필요) ──
  function updateNewsBadgesFromKorean() {
    var items = window.__majorNewsItems || [];
    if (!items.length) return;
    var all = items.map(function(n){ return n.ko || n.title || ''; }).join(' ');

    function ko(id, gKw, rKw, gT, rT, nT) {
      var isG = gKw.some(function(k){ return all.includes(k); });
      var isR = rKw.some(function(k){ return all.includes(k); });
      var cls  = isG && !isR ? 'badge-g' : isR && !isG ? 'badge-r' : 'badge-y';
      var text = isG && !isR ? gT : isR && !isG ? rT : nT;
      var el = document.getElementById(id);
      if (el) { el.textContent = text; el.className = 'badge ' + cls; }
    }

    // badge-fii는 VNM ETF 등락 기반으로 index.html에서 직접 설정

    ko('badge-sbv',
      ['금리 인하','완화','기준금리 내','SBV 인하','인하 기대'],
      ['금리 인상','긴축','기준금리 올','SBV 인상','인상 우려'],
      'SBV 완화(호재)', 'SBV 긴축(악재)', 'SBV 정책 관망');

    ko('badge-cpi',
      ['물가 안정','인플레 완화','물가 하락','물가 둔화','CPI 하락'],
      ['물가 상승','인플레 급등','물가 급등','CPI 상승','인플레 우려'],
      '물가 안정', '물가 상승 부담', '물가 혼조');

    ko('badge-gdp',
      ['GDP 성장','경제성장','성장률 상승','경기 호조','성장 가속'],
      ['GDP 둔화','성장 둔화','경기 침체','성장률 하락','경기 부진'],
      'GDP 성장 호조', 'GDP 성장 부진', 'GDP 혼조');

    ko('badge-fed',
      ['연준 인하','금리 인하','파월 완화','Fed 완화','연준 완화'],
      ['연준 인상','연준 긴축','파월 매파','Fed 긴축','금리 동결 우려'],
      '연준 완화(호재)', '연준 긴축(악재)', '연준 불확실');

    ko('badge-trade',
      ['무역 협상','관세 완화','무역 합의','미-베트남 협정','수출 증가'],
      ['관세 부과','무역 갈등','무역 제재','수출 감소','관세 위협'],
      '무역 호조', '무역 리스크', '무역 주시');

    ko('badge-geo',
      ['지정학 완화','평화','리스크 해소','긴장 완화','분쟁 해소'],
      ['지정학 리스크','긴장','전쟁','분쟁 확대','지정학 위기'],
      '지정학 안정', '지정학 리스크', '지정학 중립');

    var note = document.getElementById('news-live-note');
    if (note) note.textContent = '✓ 최신 뉴스 기반 자동 분류 (API 키 불필요)';

    try { if (typeof recalcScorecard === 'function') recalcScorecard(); } catch(e) {}
    try {
      if (typeof applyAnalysis === 'function' && typeof ruleBasedAnalysis === 'function' && typeof _liveData !== 'undefined') {
        if (!getAnthropicKey()) applyAnalysis(ruleBasedAnalysis(_liveData));
      }
    } catch(e) {}
  }

  // ── 매크로 신호 섹션에 뉴스 이슈 리스트 렌더링 ──
  function renderMacroNews() {
    var box = document.getElementById('macro-news-list');
    if (!box) return;
    var items = window.__majorNewsItems || [];
    if (!items.length) { box.innerHTML = '<div style="font-size:12px;color:var(--text3);">뉴스를 불러오지 못했어요</div>'; return; }
    function clean(t) {
      return (t||'').replace(/\[.*?\]\s*/g,'').replace(/\s*[-–—]\s*[\w가-힣]+\s*$/,'').trim().slice(0,60);
    }
    box.innerHTML = items.slice(0,5).map(function(n) {
      var title = clean(n.ko || n.title);
      var time = relTime(n.ts);
      return '<a href="'+n.link+'" target="_blank" rel="noopener" style="display:flex;align-items:flex-start;gap:6px;padding:7px 0;border-bottom:0.5px solid var(--border);text-decoration:none;color:var(--text);"><span style="font-size:14px;margin-top:1px;">•</span><span><span style="font-size:12.5px;line-height:1.5;">'+title.replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</span>'+(time?'<span style="display:block;font-size:10.5px;color:var(--text3);margin-top:2px;">'+time+' ↗</span>':'')+'</span></a>';
    }).join('');
  }

  window.fetchLatestNews = async function() {
    var items = window.__majorNewsItems || [];
    if (!items.length) return {};
    return { '주요 뉴스': items.slice(0, 6).map(function(n){ return n.ko || n.title; }) };
  };

  // ── 시장데이터.json 캐시 로드 → 배지·종합신호 즉시 표시 ──
  async function loadCachedMarketData() {
    try {
      var res = await fetch('시장데이터.json?t=' + Date.now());
      if (!res.ok) return;
      var d = await res.json();
      if (!d || !d.vnindex) return;

      var scEmoji = document.getElementById('sc-emoji');
      var scPct   = document.getElementById('sc-pct');
      if (scEmoji) scEmoji.textContent = (d.score_emoji || '') + ' ' + (d.score_label || '');
      if (scPct)   scPct.textContent   = (d.score_pct || 0) + '점';

      function setB(id, cls, txt) {
        var el = document.getElementById(id);
        if (!el) return;
        el.className = 'badge ' + cls;
        el.textContent = txt;
      }
      var ma = d.ma_signal || '';
      setB('badge-ma', ma.includes('정배열')?'badge-g':ma.includes('역배열')?'badge-r':'badge-y',
           ma.includes('정배열')?'정배열(상승)':ma.includes('역배열')?'역배열(하락)':'혼조');

      var rsi = d.rsi || 50;
      setB('badge-rsi', rsi<=40?'badge-g':rsi>=70?'badge-r':'badge-y',
           rsi<=40?'RSI '+rsi+' 과매도':rsi>=70?'RSI '+rsi+' 과매수':'RSI '+rsi+' 중립');

      var mom = d.mom4 || 0;
      setB('badge-mom', mom>=2?'badge-g':mom<=-2?'badge-r':'badge-y',
           mom>=2?'모멘텀 +'+mom+'%':mom<=-2?'모멘텀 '+mom+'%':'모멘텀 보합');

      var fhi = d.from_hi || 0;
      setB('badge-pos', fhi<=-20?'badge-g':fhi>=-3?'badge-r':'badge-y',
           fhi<=-20?'고점대비 '+fhi+'% 저점권':fhi>=-3?'고점 근접 '+fhi+'%':'고점대비 '+fhi+'%');

      var vix_u = d.us_vix || 0;
      if (vix_u) setB('badge-vix', vix_u<20?'badge-g':vix_u>28?'badge-r':'badge-y', 'US VIX '+vix_u);

      var crude = d.crude || 0;
      if (crude) setB('badge-crude', crude>85?'badge-g':crude<75?'badge-r':'badge-y', '유가 $'+crude);

      var vnd = d.vnd || 0;
      if (vnd) setB('badge-vnd', vnd<25000?'badge-g':vnd>26000?'badge-r':'badge-y', '₫'+vnd);

      try { if (typeof recalcScorecard === 'function') recalcScorecard(); } catch(e) {}
      console.log('[시장데이터] 캐시 로드 완료:', d.updated);
    } catch(e) {
      console.log('[시장데이터] 캐시 없음 (처음 실행이거나 아직 생성 전)');
    }
  }

  // ── 전체 실행 ──
  async function runRealtime() {
    await loadCachedMarketData();

    var vnmMeta = null;
    try {
      vnmMeta = await refreshChart('chartVNINDEX', 'VNM', VNM_SCALE);
    } catch (e) {}

    try { await renderMajorNews(); } catch (e) {}
    try { renderMacroNews(); } catch (e) {}
    try { updateNewsBadgesFromKorean(); } catch (e) {}

    try {
      var url1y = 'https://query2.finance.yahoo.com/v8/finance/chart/VNM?interval=1wk&range=1y';
      var j1y = await proxyJSON(url1y, 9000);
      if (j1y && j1y.chart && j1y.chart.result && j1y.chart.result[0]) {
        var res1y = j1y.chart.result[0];
        var rawWeekly = res1y.indicators.quote[0].close || [];
        var weekly = rawWeekly.filter(function(p){ return p != null; }).map(function(p){ return p * VNM_SCALE; });
        if (!vnmMeta) vnmMeta = res1y.meta;
        if (weekly.length >= 6) {
          updateTechnicals(vnmMeta, weekly);
          var url5d = 'https://query2.finance.yahoo.com/v8/finance/chart/VNM?interval=1d&range=5d';
          var j5d = await proxyJSON(url5d, 6000);
          var d5prices = null;
          if (j5d && j5d.chart && j5d.chart.result && j5d.chart.result[0]) {
            var raw5d = j5d.chart.result[0].indicators.quote[0].close || [];
            d5prices = raw5d.filter(function(p){ return p != null; }).map(function(p){ return p * VNM_SCALE; });
          }
          buildAnalysis('VN-Index', weekly, d5prices, vnmMeta);
        }
      }
    } catch (e) {}

    try { if (typeof recalcScorecard === 'function') recalcScorecard(); } catch (e) {}

    try {
      await new Promise(function(r){ setTimeout(r, 1000); });
      if (typeof applyAnalysis === 'function' && typeof ruleBasedAnalysis === 'function' && typeof _liveData !== 'undefined') {
        if (!getAnthropicKey()) applyAnalysis(ruleBasedAnalysis(_liveData));
      }
    } catch (e) {}

    try { if (typeof window.updateActionGuide === 'function' && getAnthropicKey()) window.updateActionGuide(); } catch (e) {}
  }

  // ── AI 질문 (현재 지표 + 뉴스 반영) ──
  window.askAI = async function() {
    var qEl = document.getElementById('ai-q');
    var box = document.getElementById('ai-resp');
    if (!qEl || !box) return;
    var q = (qEl.value || '').trim();
    if (!q) return;
    var key = getAnthropicKey();
    if (!key) {
      var ks = document.getElementById('key-setup');
      if (ks) ks.style.display = 'block';
      box.textContent = 'API 키를 먼저 입력해주세요.';
      return;
    }
    box.textContent = '분석 중...';
    var price = (document.querySelector('.idx-price') && document.querySelector('.idx-price').textContent || '').trim();
    var sc = ((document.getElementById('sc-emoji')&&document.getElementById('sc-emoji').textContent||'') + ' ' + (document.getElementById('sc-pct')&&document.getElementById('sc-pct').textContent||'')).trim();
    var signals = Array.from(document.querySelectorAll('.signal-row')).slice(0,20)
      .map(function(r){ return r.textContent.replace(/\s+/g,' ').trim(); }).filter(Boolean).join('\n');
    var news = window.__majorNews || '';
    var ctx = '당신은 '+MARKET_DESC+' 전문 애널리스트입니다. 아래 실시간 데이터와 오늘의 뉴스를 근거로 한국어로 간결하고 구체적으로 답하세요. 마지막에 "본 답변은 참고용입니다"를 덧붙이세요.\n\n[현재 지수] '+price+'\n[종합신호] '+sc+'\n[지표·신호]\n'+signals+(news?'\n\n[오늘의 주요 뉴스]\n'+news:'');
    try {
      var r = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
        body: JSON.stringify({ model: 'claude-sonnet-4-6', max_tokens: 700, system: ctx, messages: [{ role: 'user', content: q }] }),
      });
      var d = await r.json();
      if (d.content && d.content[0] && d.content[0].text) box.textContent = d.content[0].text;
      else box.textContent = '오류: ' + JSON.stringify(d.error || d);
    } catch (e) { box.textContent = '네트워크 오류: ' + e.message; }
  };

  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', function(){ setTimeout(runRealtime, 300); });
  } else {
    setTimeout(runRealtime, 300);
  }
  setInterval(runRealtime, 5 * 60 * 1000);
})();
