#!/usr/bin/env python3
"""
베트남 펀드 대시보드 업데이터
- VN-Index 데이터를 Yahoo Finance에서 자동으로 가져옴
- 매수 전 타이밍 분석 모드
"""

import json
import re
import os
import sys
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime

def install(pkg):
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

try:
    import yfinance as yf
except ImportError:
    print("yfinance 설치 중...")
    install('yfinance')
    import yfinance as yf

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '설정.json')

def load_config():
    default = {
        "anthropic_api_key": "",
        "newsapi_key": "",
        "투자예정금_만원": 2000,
        "추가투자_만원": 2000,
        "손절기준_퍼센트": 10,
        "VNINDEX_관심구간_하단": 0,
        "VNINDEX_관심구간_상단": 0,
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        default.update(saved)
    else:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
    return default

# ── VN-Index 데이터 가져오기 ─────────────────────────────────────
# ^VNINDEX.VN: 당일 실시간만 가능 (역사 데이터 없음)
# VNM ETF: 미국 상장 베트남 ETF, 역사 데이터 완전함 → 비율 환산해서 VN-Index 근사치로 사용

def fetch_period_scaled(ticker, period, interval, fmt, scale):
    h = ticker.history(period=period, interval=interval)
    labels, prices = [], []
    for date, row in h.iterrows():
        labels.append(date.strftime(fmt))
        prices.append(round(float(row['Close']) * scale, 2))
    return labels, prices

def fetch_vnindex():
    print("VN-Index 데이터 가져오는 중...")

    # 1. ^VNINDEX.VN 으로 현재가 + 당일 분봉 가져오기
    vn_ticker = yf.Ticker("^VNINDEX.VN")
    d1_h = vn_ticker.history(period="1d", interval="5m")
    d1_labels = [d.strftime("%H:%M") for d in d1_h.index]
    d1_prices = [round(float(r['Close']), 2) for _, r in d1_h.iterrows()]

    today_h = vn_ticker.history(period="1d", interval="1d")
    if not today_h.empty:
        row = today_h.iloc[-1]
        open_p     = round(float(row['Open']), 2)
        high_p     = round(float(row['High']), 2)
        low_p      = round(float(row['Low']),  2)
        today_close = round(float(row['Close']), 2)
        today_label = today_h.index[-1].strftime("%-m/%-d")
    else:
        open_p = high_p = low_p = today_close = 0
        today_label = ""

    try:
        current = round(float(vn_ticker.fast_info.last_price), 2)
    except Exception:
        current = today_close if today_close else (d1_prices[-1] if d1_prices else 1800)

    print(f"  VN-Index 현재가: {current:,}")

    # 2. VNM ETF로 역사 데이터 가져오기 후 VN-Index 스케일로 환산
    vnm = yf.Ticker("VNM")
    vnm_today = vnm.history(period="1d", interval="1d")
    vnm_price = round(float(vnm_today['Close'].iloc[-1]), 4) if not vnm_today.empty else 17.0
    scale = current / vnm_price  # VN-Index/VNM 비율 (약 100배)
    print(f"  VNM ETF 스케일 환산 비율: {round(scale, 2)}x")

    d5_labels,  d5_prices  = fetch_period_scaled(vnm, "5d",  "1d",  "%-m/%-d", scale)
    d30_labels, d30_prices = fetch_period_scaled(vnm, "1mo", "1d",  "%-m/%-d", scale)
    mo3_labels, mo3_prices = fetch_period_scaled(vnm, "3mo", "1wk", "%-m/%-d", scale)
    mo6_labels, mo6_prices = fetch_period_scaled(vnm, "6mo", "1wk", "%-m/%-d", scale)
    yr1_labels, yr1_prices = fetch_period_scaled(vnm, "1y",  "1wk", "%-m/%-d", scale)

    # 전일 대비 등락
    prev_close = d5_prices[-2] if len(d5_prices) >= 2 else current
    change_val = round(current - prev_close, 2)
    change_pct = round(change_val / prev_close * 100, 2) if prev_close else 0

    # 오늘 데이터 최신 데이터에 추가
    for lbl_list, prc_list in [(mo6_labels, mo6_prices), (yr1_labels, yr1_prices)]:
        if today_label and lbl_list and today_label != lbl_list[-1]:
            lbl_list.append(today_label)
            prc_list.append(current)

    return {
        "current": current, "change_val": change_val, "change_pct": change_pct,
        "open": open_p, "high": high_p, "low": low_p,
        "d1":  {"labels": d1_labels,  "prices": d1_prices},
        "d5":  {"labels": d5_labels,  "prices": d5_prices},
        "d30": {"labels": d30_labels, "prices": d30_prices},
        "mo3": {"labels": mo3_labels, "prices": mo3_prices},
        "mo6": {"labels": mo6_labels, "prices": mo6_prices},
        "yr1": {"labels": yr1_labels, "prices": yr1_prices},
        "labels": yr1_labels,
        "prices": yr1_prices,
    }

# ── 매크로 지표 ──────────────────────────────────────────────────
def fetch_macro_signals():
    result = {"usdvnd": None, "vix": None, "crude": None, "dxy": None, "eem": None,
              "vn30": None, "usdcny": None, "gold": None}
    try:
        val = yf.Ticker("USDVND=X").fast_info.last_price
        result["usdvnd"] = round(float(val))
        print(f"  USD/VND: {result['usdvnd']:,}")
    except Exception as e:
        print(f"  USD/VND 가져오기 실패: {e}")
    try:
        vnm_h = yf.Ticker("VNM").history(period="5d", interval="1d")
        if not vnm_h.empty:
            result["vn30"] = round(float(vnm_h['Close'].iloc[-1]), 2)
            result["vn30_prev"] = round(float(vnm_h['Close'].iloc[-2]), 2) if len(vnm_h) >= 2 else result["vn30"]
            print(f"  VNM ETF: ${result['vn30']}")
    except Exception as e:
        print(f"  VNM ETF 가져오기 실패: {e}")
    try:
        cny_h = yf.Ticker("USDCNY=X").history(period="5d", interval="1d")
        if not cny_h.empty:
            result["usdcny"] = round(float(cny_h['Close'].iloc[-1]), 2)
            print(f"  USD/CNY(위안화): {result['usdcny']}")
    except Exception as e:
        print(f"  USD/CNY 가져오기 실패: {e}")
    try:
        result["vix"] = round(yf.Ticker("^VIX").fast_info.last_price, 2)
        print(f"  VIX(미국): {result['vix']}")
    except Exception as e:
        print(f"  VIX 가져오기 실패: {e}")
    try:
        result["crude"] = round(yf.Ticker("BZ=F").fast_info.last_price, 1)
        print(f"  브렌트유: ${result['crude']}")
    except Exception as e:
        print(f"  브렌트유 가져오기 실패: {e}")
    try:
        gold_h = yf.Ticker("GC=F").history(period="5d", interval="1d")
        if not gold_h.empty:
            result["gold"] = round(float(gold_h['Close'].iloc[-1]), 0)
            result["gold_prev"] = round(float(gold_h['Close'].iloc[-2]), 0) if len(gold_h) >= 2 else result["gold"]
            print(f"  금: ${result['gold']}")
    except Exception as e:
        print(f"  금 가져오기 실패: {e}")
    try:
        dxy_h = yf.Ticker("DX-Y.NYB").history(period="5d", interval="1d")
        if not dxy_h.empty:
            result["dxy"] = round(float(dxy_h['Close'].iloc[-1]), 2)
            result["dxy_prev"] = round(float(dxy_h['Close'].iloc[-2]), 2) if len(dxy_h) >= 2 else result["dxy"]
            print(f"  달러 인덱스(DXY): {result['dxy']}")
    except Exception as e:
        print(f"  DXY 가져오기 실패: {e}")
    try:
        eem_h = yf.Ticker("EEM").history(period="5d", interval="1d")
        if not eem_h.empty:
            result["eem"] = round(float(eem_h['Close'].iloc[-1]), 2)
            result["eem_prev"] = round(float(eem_h['Close'].iloc[-2]), 2) if len(eem_h) >= 2 else result["eem"]
            print(f"  신흥국 ETF(EEM): ${result['eem']}")
    except Exception as e:
        print(f"  EEM 가져오기 실패: {e}")
    return result

def _fetch_fed_rate():
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            lines = r.read().decode().strip().split('\n')
        last = lines[-1].split(',')
        return float(last[1]), last[0]
    except:
        return None, None

def _fetch_google_rss(query, n=5):
    import urllib.parse, xml.etree.ElementTree as ET
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            tree = ET.parse(r)
        items = tree.getroot().findall('.//item')[:n]
        out = []
        for item in items:
            title = item.findtext('title', '').split(' - ')[0].strip()
            date  = item.findtext('pubDate', '')[:16]
            out.append(f"[{date}] {title}")
        return out
    except:
        return []

def _fetch_newsapi(query, key, n=5):
    import urllib.parse
    params = urllib.parse.urlencode({
        "q": query, "apiKey": key,
        "language": "en", "sortBy": "publishedAt", "pageSize": n,
    })
    url = f"https://newsapi.org/v2/everything?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        out = []
        for a in data.get("articles", []):
            date  = a.get("publishedAt", "")[:10]
            title = a.get("title", "")
            out.append(f"[{date}] {title}")
        return out
    except:
        return []

# ── 베트남 전용 뉴스 토픽 ────────────────────────────────────────
TOPICS = [
    {"key": "fdi",     "label": "베트남 FDI",       "rss": "Vietnam FDI foreign direct investment inflow",   "api": "Vietnam FDI investment"},
    {"key": "fii",     "label": "외국인 자금",        "rss": "Vietnam stock market foreign investor buy sell", "api": "Vietnam stock foreign investor flow"},
    {"key": "sbv",     "label": "SBV 금리",           "rss": "Vietnam central bank SBV interest rate policy",  "api": "Vietnam SBV rate hike cut"},
    {"key": "trade",   "label": "미-베트남 무역",      "rss": "Vietnam US trade tariff agreement",              "api": "Vietnam United States trade tariff"},
    {"key": "china",   "label": "중국-베트남",         "rss": "Vietnam China trade supply chain",               "api": "Vietnam China economic trade"},
    {"key": "cpi",     "label": "베트남 CPI",          "rss": "Vietnam CPI inflation consumer price",           "api": "Vietnam inflation CPI data"},
    {"key": "semi",    "label": "반도체·제조",          "rss": "Vietnam semiconductor manufacturing Samsung Intel", "api": "Vietnam chip factory manufacturing"},
    {"key": "fed",     "label": "미국 연준",            "rss": "Federal Reserve interest rate FOMC decision",    "api": "Federal Reserve rate policy FOMC"},
    {"key": "gdp",     "label": "베트남 GDP",           "rss": "Vietnam GDP economic growth rate quarterly",     "api": "Vietnam GDP growth economy"},
]

def fetch_news_signals(claude_api_key, newsapi_key=None):
    print("뉴스 헤드라인 수집 중...")
    fed_rate, fed_date = _fetch_fed_rate()
    if fed_rate:
        print(f"  연준 기준금리: {fed_rate}% ({fed_date})")

    all_headlines = {}
    for t in TOPICS:
        lines = _fetch_google_rss(t["rss"], n=4)
        if newsapi_key:
            lines += _fetch_newsapi(t["api"], newsapi_key, n=4)
        seen, uniq = set(), []
        for l in lines:
            key = l[18:].lower()[:40]
            if key not in seen:
                seen.add(key)
                uniq.append(l)
        all_headlines[t["key"]] = {"label": t["label"], "headlines": uniq[:6]}
        print(f"  {t['label']}: {len(uniq[:6])}개 헤드라인")

    if not claude_api_key:
        return {k: {"badge": "badge-b", "text": "뉴스 수집됨 (AI 분석 없음)", "headlines": v["headlines"]}
                for k, v in all_headlines.items()}

    print("Claude AI 뉴스 분석 중...")
    fed_note = f"\n* 연준 기준금리 실제값(FRED): {fed_rate}% ({fed_date})" if fed_rate else ""

    news_block = ""
    for t in TOPICS:
        k = t["key"]
        label = t["label"]
        headlines = all_headlines[k]["headlines"]
        news_block += f"[{label}]\n"
        if headlines:
            news_block += "\n".join(f"• {h}" for h in headlines)
        else:
            news_block += "• (헤드라인 없음)"
        news_block += "\n\n"

    prompt = f"""오늘은 {datetime.now().strftime('%Y년 %m월 %d일')}입니다.{fed_note}

아래는 각 주제별 최신 뉴스 헤드라인입니다. 베트남 주식 펀드 투자자 관점에서 각 항목을 판단해주세요.

{news_block}
각 항목마다 다음 JSON으로만 답하세요 (다른 텍스트 없이):
{{
  "fdi":   {{"badge": "g/y/r/b", "text": "한국어 12자 이내 핵심 요약"}},
  "fii":   {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "sbv":   {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "trade": {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "china": {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "cpi":   {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "semi":  {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "fed":   {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "gdp":   {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}}
}}

badge 기준: g=호재(초록), y=중립/주의(노랑), r=악재(빨강), b=정보(파랑)"""

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={"Content-Type": "application/json",
                 "x-api-key": claude_api_key,
                 "anthropic-version": "2023-06-01"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
        raw = resp["content"][0]["text"].strip()
        m = re.search(r'\{[\s\S]+\}', raw)
        judgments = json.loads(m.group()) if m else {}
    except Exception as e:
        print(f"  Claude 분석 실패: {e}")
        judgments = {}

    result = {}
    badge_map = {"g": "badge-g", "y": "badge-y", "r": "badge-r", "b": "badge-b"}
    for t in TOPICS:
        k = t["key"]
        j = judgments.get(k, {})
        badge_raw = j.get("badge", "b")
        result[k] = {
            "badge": badge_map.get(badge_raw, "badge-b"),
            "text":  j.get("text", "분석 중"),
            "headlines": all_headlines[k]["headlines"],
        }
    if fed_rate and "fed" in result:
        result["fed"]["rate"] = fed_rate

    return result

# ── 기술적 지표 계산 ─────────────────────────────────────────────
def calc_indicators(prices):
    n = len(prices)
    current = prices[-1]
    prev = prices[-2] if n >= 2 else current

    week_chg = round((current - prev) / prev * 100, 2)
    ma5  = round(sum(prices[-5:])  / min(5,  n), 2) if n >= 5  else None
    ma13 = round(sum(prices[-13:]) / min(13, n), 2) if n >= 13 else None
    ma26 = round(sum(prices[-26:]) / min(26, n), 2) if n >= 26 else None
    high52 = max(prices)
    low52  = min(prices)
    from_high = round((current - high52) / high52 * 100, 1)
    from_low  = round((current - low52)  / low52  * 100, 1)

    gains, losses = [], []
    for i in range(max(1, n-14), n):
        diff = prices[i] - prices[i-1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_gain = sum(gains) / 14 if gains else 0
    avg_loss = sum(losses) / 14 if losses else 0.0001
    rsi = round(100 - 100 / (1 + avg_gain / avg_loss), 1)

    returns = [(prices[i]-prices[i-1])/prices[i-1]*100 for i in range(max(1,n-8), n)]
    avg_r = sum(returns) / len(returns) if returns else 0
    vol = round((sum((r-avg_r)**2 for r in returns)/len(returns))**0.5, 2) if returns else 0
    momentum = round((prices[-1] - prices[-5]) / prices[-5] * 100, 1) if n >= 5 else 0

    if ma5 and ma13:
        if current > ma5 > ma13:
            ma_signal = "정배열(상승)"
        elif current < ma5 < ma13:
            ma_signal = "역배열(하락)"
        else:
            ma_signal = "혼조"
    else:
        ma_signal = "데이터 부족"

    return {
        "current": current, "week_chg": week_chg,
        "ma5": ma5, "ma13": ma13, "ma26": ma26, "ma_signal": ma_signal,
        "high52": high52, "low52": low52, "from_high": from_high, "from_low": from_low,
        "rsi": rsi, "vol": vol, "momentum": momentum,
    }

# ── AI 차트 분석 ──────────────────────────────────────────────────
def generate_chart_analysis(vn, api_key, scorecard_label=None):
    if not api_key:
        return "AI 분석을 보려면 설정.json에 anthropic_api_key를 입력해주세요."

    ind = calc_indicators(vn["prices"])
    actual_chg = vn["change_pct"]
    actual_chg_str = f"{'+' if actual_chg >= 0 else ''}{actual_chg}%"

    ma5_str  = f"{ind['ma5']:,}"  if ind['ma5']  else "데이터 부족"
    ma13_str = f"{ind['ma13']:,}" if ind['ma13'] else "데이터 부족"
    ma26_str = f"{ind['ma26']:,}" if ind['ma26'] else "데이터 부족"
    sc_note = f"\n참고: 종합매수신호 계산 결과는 '{scorecard_label}'입니다. 이 결론과 일치하는 방향으로 분석해주세요." if scorecard_label else ""

    prompt = f"""오늘은 {datetime.now().strftime('%Y년 %m월 %d일')}입니다.{sc_note}
VN-Index 주간 차트 지표를 바탕으로 매수 타이밍 분석을 해줘.

[지표]
현재: {ind['current']:,} (전일 대비 {actual_chg_str})
5주 이평: {ma5_str} / 13주 이평: {ma13_str} / 26주 이평: {ma26_str}
이평 배열: {ind['ma_signal']}
52주 고점: {ind['high52']:,} (현재 {ind['from_high']}%) / 52주 저점: {ind['low52']:,} (현재 +{ind['from_low']}%)
RSI(14): {ind['rsi']} (30이하=과매도, 70이상=과매수)
단기 모멘텀(4주): {'+' if ind['momentum']>=0 else ''}{ind['momentum']}%
주간 변동성: ±{ind['vol']}%

아래 항목을 불릿(•)으로 각각 한 줄씩 정리해줘. 마크다운 **볼드** 사용 가능:
• **현재 지수**: 오늘 수치와 전주 등락 요약
• **추세 (이평)**: MA 배열로 본 매수세/매도세 판단
• **모멘텀**: RSI와 4주 모멘텀으로 본 단기 힘
• **변동성**: 최근 시장이 얼마나 출렁이는지
• **위치**: 52주 고점 대비 얼마나 내려왔는지, 저점 대비 얼마나 회복했는지
• **매수 타이밍**: 지금 진입이 좋은지, 기다려야 하는지
• **한 줄 결론**: 지금 상황을 한 문장으로

한국어, 숫자 콤마 포함, 간결하게."""

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={"Content-Type": "application/json",
                 "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            return data["content"][0]["text"]
    except Exception as e:
        return f"분석 생성 실패: {e}"

# ── 매수 타이밍 가이드 AI 생성 ───────────────────────────────────
def generate_action_guide(vn, indicators, macro, news, cfg, api_key, events=None, scorecard_label=None):
    if not api_key:
        return None

    ind = indicators or {}
    mac = macro or {}
    nws = news or {}
    invest = cfg.get("투자예정금_만원", 2000)
    add    = cfg.get("추가투자_만원", 2000)
    sl_pct = cfg.get("손절기준_퍼센트", 10)
    current = vn["current"]
    sl_price = round(current * (1 - sl_pct / 100), 2)

    news_summary = ""
    label_map = {"fdi":"FDI","fii":"외국인 자금","sbv":"SBV 금리","trade":"미-베트남 무역","cpi":"CPI","fed":"미국 연준"}
    for k, lbl in label_map.items():
        n = nws.get(k, {})
        news_summary += f"- {lbl}: {n.get('text','정보없음')} (판단: {n.get('badge','').replace('badge-','')})\n"

    sc_note = f"\n[종합신호 참고]\n종합매수신호 계산 결과: '{scorecard_label}' — ACTION과 NOW_TITLE은 이 결과와 반드시 일치해야 합니다.\n" if scorecard_label else ""

    events_note = ""
    if events:
        from datetime import date as _date
        today = _date.today()
        upcoming = []
        for ev in sorted(events, key=lambda x: x["날짜"]):
            try:
                diff = (_date.fromisoformat(ev["날짜"]) - today).days
                if 0 <= diff <= 30:
                    upcoming.append(f"D-{diff}: {ev['내용']}")
            except Exception:
                pass
        if upcoming:
            events_note = "\n[30일 내 주요 이벤트]\n" + "\n".join(f"- {e}" for e in upcoming)

    prompt = f"""오늘은 {datetime.now().strftime('%Y년 %m월 %d일')}입니다.{sc_note}
당신은 베트남 주식 펀드 전문 매니저입니다. 아래 현재 지표를 보고 매수 타이밍 가이드를 작성해주세요.

[투자 계획 (아직 미매수)]
- 투자 예정금: {invest:,}만원 (1차) / 추가 {add:,}만원 (2차 분할)
- 손절 기준: 매수가 대비 -{sl_pct}%
- 현재 VN-Index 기준 손절선 추정: {sl_price:,}pt

[기술적 지표]
- VN-Index: {vn['current']:,} ({vn['change_pct']:+}%)
- RSI(14주): {ind.get('rsi','?')} / 이평 배열: {ind.get('ma_signal','?')}
- 4주 모멘텀: {ind.get('momentum',0):+}% / 변동성: ±{ind.get('vol',0)}%
- 52주 고점 대비: {ind.get('from_high',0)}% / 저점 대비: +{ind.get('from_low',0)}%

[매크로]
- USD/VND: {mac.get('usdvnd','?'):,}동 / VIX: {mac.get('vix','?')} / 브렌트유: ${mac.get('crude','?')}

[뉴스 신호]
{news_summary}{events_note}
JSON으로만 답하세요. 각 desc는 1문장씩:
{{"now":{{"action":"관망","type":"hold","title":"📌 지금 — [한 마디]","desc":"[현황 요약]"}},"buy1":{{"title":"🟢 1차 매수 조건","desc":"[조건+금액]"}},"buy2":{{"title":"🟢 2차 매수 조건","desc":"[조건+금액]"}},"sell":{{"title":"🔴 손절 조건","desc":"[트리거]"}}}}"""

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 900,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={"Content-Type": "application/json",
                 "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"}
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            resp = json.loads(r.read())
        raw = resp["content"][0]["text"].strip()
        raw = re.sub(r'```json\s*', '', raw)
        raw = re.sub(r'```\s*', '', raw)
        raw = re.sub(r',\s*([}\]])', r'\1', raw)
        m = re.search(r'\{[\s\S]+\}', raw)
        return json.loads(m.group()) if m else None
    except Exception as e:
        print(f"  액션 가이드 생성 실패: {e}")
        return None

def md2html(text):
    h = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    return h.replace('\n', '<br>')

def make_periods_js(data, name):
    return json.dumps({
        "name": name,
        "sl":   None,
        "d1":  data["d1"], "d5":  data["d5"], "d30": data["d30"],
        "mo3": data["mo3"],"mo6": data["mo6"],"yr1": data["yr1"],
    }, ensure_ascii=False)

def index_section_html(data, chart_analysis, name, chart_id, period_prefix):
    chg = data["change_pct"]
    chg_class = "up" if chg >= 0 else "down"
    chg_sign = "▲" if chg >= 0 else "▼"
    chg_val = f"{'+' if data['change_val']>=0 else ''}{data['change_val']:,.2f}"
    analysis_card = ""
    if chart_analysis:
        analysis_html = md2html(chart_analysis)
        analysis_card = f"""
  <div class="card" style="margin-top:-4px;">
    <div class="card-title" style="font-size:12px;color:var(--text2);font-weight:500;margin-bottom:10px;">📊 AI 차트 분석 — {name}</div>
    <div style="font-size:13px;line-height:2;color:var(--text);">{analysis_html}</div>
  </div>"""

    return f"""
  <div class="nifty-header">
    <div class="nifty-name">{name}</div>
    <div class="nifty-price {chg_class}">{data["current"]:,.2f}</div>
    <div class="nifty-change {chg_class}">{chg_sign} {chg_val} &nbsp;({'+' if chg>=0 else ''}{chg}%)</div>
    <div class="ohlc-row">
      <div class="ohlc-item"><div class="ohlc-label">시가</div><div class="ohlc-val">{data["open"]:,.2f}</div></div>
      <div class="ohlc-item"><div class="ohlc-label">고가</div><div class="ohlc-val up">{data["high"]:,.2f}</div></div>
      <div class="ohlc-item"><div class="ohlc-label">저가</div><div class="ohlc-val down">{data["low"]:,.2f}</div></div>
    </div>
  </div>
  <div class="period-tabs" id="{period_prefix}-tabs">
    <div class="period-tab active" onclick="switchChart('{chart_id}','{period_prefix}','d1',this)">일</div>
    <div class="period-tab" onclick="switchChart('{chart_id}','{period_prefix}','d5',this)">5일</div>
    <div class="period-tab" onclick="switchChart('{chart_id}','{period_prefix}','d30',this)">1개월</div>
    <div class="period-tab" onclick="switchChart('{chart_id}','{period_prefix}','mo3',this)">3개월</div>
    <div class="period-tab" onclick="switchChart('{chart_id}','{period_prefix}','mo6',this)">6개월</div>
    <div class="period-tab" onclick="switchChart('{chart_id}','{period_prefix}','yr1',this)">1년</div>
  </div>
  <div class="card" style="padding:12px 12px 10px;">
    <div class="chart-wrap"><canvas id="{chart_id}"></canvas></div>
    <div style="display:flex;gap:16px;font-size:11px;color:var(--text2);margin-top:4px;">
      <span style="display:flex;align-items:center;gap:4px;"><span style="width:12px;height:2px;background:#378ADD;display:inline-block;border-radius:1px;"></span>{name}</span>
    </div>
  </div>{analysis_card}"""

# ── HTML 빌드 ─────────────────────────────────────────────────────
def build_html(vn, cfg, api_key, updated_at, vn_analysis, indicators=None, macro=None, news=None, action_guide=None, events=None):
    ind   = indicators or {}
    mac   = macro or {}
    nws   = news or {}
    invest = cfg.get("투자예정금_만원", 2000)
    add    = cfg.get("추가투자_만원", 2000)
    sl_pct = cfg.get("손절기준_퍼센트", 10)
    current = vn["current"]
    sl_price = round(current * (1 - sl_pct / 100), 2)

    vn_section = index_section_html(vn, vn_analysis, "VN-Index", "chartVN", "vn")
    vn_periods_js = make_periods_js(vn, "VN-Index")

    # ── 기술적 신호 ──────────────────────────────────────────────
    def sig_row(name, badge_cls, text, badge_id=""):
        id_attr = f' id="{badge_id}"' if badge_id else ''
        return f'<div class="signal-row"><span class="signal-name">{name}</span><span class="badge {badge_cls}"{id_attr} data-sg="tech">{text}</span></div>'

    rsi = ind.get("rsi", 50)
    if rsi <= 30:   rsi_cls, rsi_txt = "badge-g", f"RSI {rsi} — 과매도 (매수 기회)"
    elif rsi >= 70: rsi_cls, rsi_txt = "badge-r", f"RSI {rsi} — 과매수 (주의)"
    else:           rsi_cls, rsi_txt = "badge-b", f"RSI {rsi} — 중립"

    ma_sig = ind.get("ma_signal", "데이터 부족")
    if "정배열" in ma_sig: ma_cls = "badge-g"
    elif "역배열" in ma_sig: ma_cls = "badge-r"
    else: ma_cls = "badge-y"

    mom = ind.get("momentum", 0)
    mom_cls = "badge-g" if mom > 1 else ("badge-r" if mom < -1 else "badge-y")
    mom_txt = f"{'▲' if mom>=0 else '▼'} {abs(mom)}% (4주 변화)"

    vol = ind.get("vol", 0)
    vol_cls = "badge-r" if vol > 2 else ("badge-y" if vol > 1 else "badge-g")
    vol_txt = f"주간 ±{vol}% — {'고변동' if vol > 2 else ('보통' if vol > 1 else '안정')}"

    fh = ind.get("from_high", 0)
    fl = ind.get("from_low", 0)
    pos_cls = "badge-g" if fh > -10 else ("badge-y" if fh > -20 else "badge-r")
    pos_txt = f"52주 고점 대비 {fh}% / 저점 대비 +{fl}%"

    tech_signals_html = (
        sig_row("RSI (14주)", rsi_cls, rsi_txt) +
        sig_row("이평선 배열", ma_cls, ma_sig) +
        sig_row("단기 모멘텀", mom_cls, mom_txt) +
        sig_row("변동성", vol_cls, vol_txt) +
        sig_row("52주 가격 위치", pos_cls, pos_txt)
    )

    # ── 매크로 신호 ──────────────────────────────────────────────
    vn30 = mac.get("vn30")
    vn30_prev = mac.get("vn30_prev", vn30)
    if vn30:
        vn30_chg = round(vn30 - vn30_prev, 2) if vn30_prev else 0
        vn30_pct = round(vn30_chg / vn30_prev * 100, 2) if vn30_prev else 0
        vn30_sign = "▲" if vn30_chg >= 0 else "▼"
        vn30_cls = "badge-g" if vn30_chg >= 0 else "badge-r"
        vn30_txt = f"${vn30} {vn30_sign}{abs(vn30_pct)}% — {'상승' if vn30_chg>=0 else '하락'}"
    else:
        vn30_cls, vn30_txt = "badge-b", "데이터 없음"

    usdcny = mac.get("usdcny")
    if usdcny:
        if usdcny > 7.3:   usdcny_cls, usdcny_txt = "badge-r", f"¥{usdcny} — 위안 급약세, 경쟁 압박"
        elif usdcny > 7.0: usdcny_cls, usdcny_txt = "badge-y", f"¥{usdcny} — 위안 약세, 수출 경쟁"
        else:              usdcny_cls, usdcny_txt = "badge-g", f"¥{usdcny} — 위안 안정"
    else:
        usdcny_cls, usdcny_txt = "badge-b", "데이터 없음"

    gold = mac.get("gold")
    gold_prev = mac.get("gold_prev", gold)
    if gold:
        gold_chg_pct = round((gold - gold_prev) / gold_prev * 100, 1) if gold_prev else 0
        gold_sign = "▲" if gold_chg_pct >= 0 else "▼"
        if gold > 3200:   gold_cls, gold_lbl = "badge-y", "위험회피 심리 강함"
        elif gold > 2500: gold_cls, gold_lbl = "badge-b", "안정"
        else:             gold_cls, gold_lbl = "badge-g", "안정"
        gold_txt = f"${int(gold):,} {gold_sign}{abs(gold_chg_pct)}% — {gold_lbl}"
    else:
        gold_cls, gold_txt = "badge-b", "데이터 없음"

    usdvnd = mac.get("usdvnd")
    if usdvnd:
        if usdvnd < 24000:
            usdvnd_cls, usdvnd_txt = "badge-g", f"₫{usdvnd:,} — 동 강세"
        elif usdvnd < 25500:
            usdvnd_cls, usdvnd_txt = "badge-b", f"₫{usdvnd:,} — 안정"
        elif usdvnd < 26500:
            usdvnd_cls, usdvnd_txt = "badge-y", f"₫{usdvnd:,} — 동 약세"
        else:
            usdvnd_cls, usdvnd_txt = "badge-r", f"₫{usdvnd:,} — 동 급락"
    else:
        usdvnd_cls, usdvnd_txt = "badge-b", "데이터 없음"

    vix = mac.get("vix")
    if vix:
        if vix < 15:   vix_cls, vix_txt = "badge-g", f"US VIX {vix} — 매우 안정"
        elif vix < 20: vix_cls, vix_txt = "badge-g", f"US VIX {vix} — 안정"
        elif vix < 25: vix_cls, vix_txt = "badge-y", f"US VIX {vix} — 보통"
        elif vix < 30: vix_cls, vix_txt = "badge-y", f"US VIX {vix} — 불안 주의"
        else:          vix_cls, vix_txt = "badge-r", f"US VIX {vix} — 공포 구간"
    else:
        vix_cls, vix_txt = "badge-b", "데이터 없음"

    crude = mac.get("crude")
    if crude:
        if crude < 70:   crude_cls, crude_txt = "badge-g", f"${crude} 저유가 (호재)"
        elif crude < 80: crude_cls, crude_txt = "badge-g", f"${crude} 안정"
        elif crude < 90: crude_cls, crude_txt = "badge-y", f"${crude} 보통"
        else:            crude_cls, crude_txt = "badge-r", f"${crude} 고유가 (악재)"
    else:
        crude_cls, crude_txt = "badge-b", "데이터 없음"

    dxy = mac.get("dxy")
    dxy_prev = mac.get("dxy_prev", dxy)
    if dxy:
        dxy_chg = round(dxy - dxy_prev, 2) if dxy_prev else 0
        dxy_sign = "▲" if dxy_chg >= 0 else "▼"
        if dxy < 99:     dxy_cls, dxy_txt = "badge-g", f"DXY {dxy} {dxy_sign}{abs(dxy_chg)} — 달러 약세(호재)"
        elif dxy < 103:  dxy_cls, dxy_txt = "badge-b", f"DXY {dxy} {dxy_sign}{abs(dxy_chg)} — 안정"
        elif dxy < 106:  dxy_cls, dxy_txt = "badge-y", f"DXY {dxy} {dxy_sign}{abs(dxy_chg)} — 달러 강세 주의"
        else:            dxy_cls, dxy_txt = "badge-r", f"DXY {dxy} {dxy_sign}{abs(dxy_chg)} — 달러 급강세(악재)"
    else:
        dxy_cls, dxy_txt = "badge-b", "데이터 없음"

    eem = mac.get("eem")
    eem_prev = mac.get("eem_prev", eem)
    if eem:
        eem_chg = round((eem - eem_prev) / eem_prev * 100, 2) if eem_prev else 0
        eem_sign = "▲" if eem_chg >= 0 else "▼"
        if eem_chg > 1:    eem_cls, eem_txt = "badge-g", f"${eem} {eem_sign}{abs(eem_chg)}% — 신흥국 상승(호재)"
        elif eem_chg > -1: eem_cls, eem_txt = "badge-b", f"${eem} {eem_sign}{abs(eem_chg)}% — 보합"
        else:              eem_cls, eem_txt = "badge-r", f"${eem} {eem_sign}{abs(eem_chg)}% — 신흥국 하락(악재)"
    else:
        eem_cls, eem_txt = "badge-b", "데이터 없음"

    # ── 뉴스 신호 카드 ───────────────────────────────────────────
    auto_tag = '<span style="font-size:10px;color:var(--text3);margin-left:4px;">자동</span>'

    def news_row(label, key, auto=True):
        n = nws.get(key, {})
        badge_cls = n.get("badge", "badge-b")
        text = n.get("text", "수집 중...")
        tag = auto_tag if auto else ""
        headlines = n.get("headlines", [])
        tooltip = " | ".join(h[18:] for h in headlines[:3]) if headlines else ""
        tooltip_attr = f'title="{tooltip}"' if tooltip else ""
        return (f'<div class="signal-row" {tooltip_attr}>'
                f'<span class="signal-name">{label}{tag}</span>'
                f'<span class="badge {badge_cls}">{text}</span>'
                f'</div>')

    fed_n = nws.get("fed", {})
    fed_rate_val = fed_n.get("rate")
    fed_badge = fed_n.get("badge", "badge-b")
    fed_text = f"{fed_rate_val}% — {fed_n.get('text','')}" if fed_rate_val else fed_n.get("text","수집 중...")

    # ── 관심 구간 표시 ──────────────────────────────────────────────
    zone_lo = cfg.get("VNINDEX_관심구간_하단", 0)
    zone_hi = cfg.get("VNINDEX_관심구간_상단", 0)
    if zone_lo and zone_hi:
        if current < zone_lo:
            zone_cls, zone_txt = "badge-g", f"관심구간 {zone_lo:,}~{zone_hi:,}pt — 구간 하회 (매수 적극 검토)"
        elif current <= zone_hi:
            zone_cls, zone_txt = "badge-y", f"관심구간 {zone_lo:,}~{zone_hi:,}pt — 구간 진입 중"
        else:
            zone_cls, zone_txt = "badge-b", f"관심구간 {zone_lo:,}~{zone_hi:,}pt — 구간 상회 (대기)"
        zone_row = f'<div class="signal-row"><span class="signal-name">📍 관심 구간</span><span class="badge {zone_cls}">{zone_txt}</span></div>'
    else:
        zone_row = ""

    news_card_html = f"""  <div class="card" style="margin-top:-4px;">
    <div class="card-title" style="margin-bottom:8px;">🌏 매크로 신호 <span style="font-size:11px;font-weight:400;color:var(--text3);">— 업데이트 실행 시 갱신</span></div>
    {zone_row}
    <div class="signal-row">
      <span class="signal-name">VNM ETF{auto_tag} <span style="font-size:10px;color:var(--text3);">(뉴욕상장 베트남 대표)</span></span>
      <span class="badge {vn30_cls}" id="badge-vnm">{vn30_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">동/달러{auto_tag} <span style="font-size:10px;color:var(--text3);">(USD/VND)</span></span>
      <span class="badge {usdvnd_cls}" id="badge-usdvnd">{usdvnd_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">위안화{auto_tag} <span style="font-size:10px;color:var(--text3);">(USD/CNY)</span></span>
      <span class="badge {usdcny_cls}" id="badge-usdcny">{usdcny_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">달러 인덱스{auto_tag} <span style="font-size:10px;color:var(--text3);">(DXY)</span></span>
      <span class="badge {dxy_cls}" id="badge-dxy">{dxy_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">신흥국 ETF{auto_tag} <span style="font-size:10px;color:var(--text3);">(EEM)</span></span>
      <span class="badge {eem_cls}" id="badge-eem">{eem_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">공포지수 VIX{auto_tag} <span style="font-size:10px;color:var(--text3);">(미국)</span></span>
      <span class="badge {vix_cls}" id="badge-vix">{vix_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">브렌트유{auto_tag} <span style="font-size:10px;color:var(--text3);">(PetroVN 수혜)</span></span>
      <span class="badge {crude_cls}" id="badge-crude">{crude_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">금 가격{auto_tag} <span style="font-size:10px;color:var(--text3);">(소비심리·헷지)</span></span>
      <span class="badge {gold_cls}" id="badge-gold">{gold_txt}</span>
    </div>
    {news_row("베트남 FDI 유입", "fdi")}
    {news_row("외국인 자금 흐름", "fii")}
    {news_row("SBV 금리", "sbv")}
    <div class="signal-row">
      <span class="signal-name">베트남 10년 국채 <span style="font-size:10px;color:var(--text3);margin-left:4px;">수동</span> <span style="font-size:10px;color:var(--text3);">(외국인 자금)</span></span>
      <span class="badge badge-g">3.85% — 안정</span>
    </div>
    {news_row("미-베트남 무역", "trade")}
    {news_row("중국-베트남 관계", "china")}
    {news_row("베트남 CPI", "cpi")}
    {news_row("반도체·제조업", "semi")}
    {news_row("베트남 GDP", "gdp")}
    <div class="signal-row">
      <span class="signal-name">미국 연준 금리{auto_tag}</span>
      <span class="badge {fed_badge}">{fed_text}</span>
    </div>
    <div style="margin-top:10px;font-size:11px;color:var(--text3);">* 뉴스 항목은 마우스를 올리면 원문 헤드라인을 볼 수 있어요</div>
  </div>"""

    # ── 종합 스코어카드 ──────────────────────────────────────────
    _bmap = {"badge-g": 1, "badge-y": 0, "badge-r": -1, "badge-b": 0}
    _tech_badges  = [rsi_cls, ma_cls, mom_cls, vol_cls, pos_cls]
    _macro_badges = [vn30_cls, usdvnd_cls, usdcny_cls, dxy_cls, eem_cls, vix_cls, crude_cls, gold_cls]
    _news_badges  = [nws.get(k, {}).get("badge", "badge-b")
                     for k in ["fdi","fii","sbv","trade","china","cpi","semi","fed","gdp"]]

    tech_score  = sum(_bmap.get(b, 0) * 1.5 for b in _tech_badges)
    macro_score = sum(_bmap.get(b, 0) * 1.0 for b in _macro_badges)
    news_score  = sum(_bmap.get(b, 0) * 0.8 for b in _news_badges)
    total_score = tech_score + macro_score + news_score
    max_score   = len(_tech_badges)*1.5 + len(_macro_badges)*1.0 + len(_news_badges)*0.8

    score_pct = int((total_score + max_score) / (2 * max_score) * 100)
    score_pct = max(0, min(100, score_pct))

    if total_score >= max_score * 0.5:
        sc_label, sc_color, sc_bg, sc_emoji = "강매수", "#2d6a0a", "#e8fde8", "🔥"
    elif total_score >= max_score * 0.15:
        sc_label, sc_color, sc_bg, sc_emoji = "매수 검토", "#2d8a4e", "#f0faf0", "🟢"
    elif total_score >= -max_score * 0.15:
        sc_label, sc_color, sc_bg, sc_emoji = "관망", "#BA7517", "#fff8e1", "📌"
    elif total_score >= -max_score * 0.5:
        sc_label, sc_color, sc_bg, sc_emoji = "조심", "#c0392b", "#fff0f0", "⚠️"
    else:
        sc_label, sc_color, sc_bg, sc_emoji = "진입 자제", "#9b2020", "#fde8e8", "🔴"

    # 실제 수치 기반 구체적 설명 생성
    _usdvnd     = mac.get("usdvnd")
    _dxy        = mac.get("dxy")
    _vix        = mac.get("vix")
    _crude      = mac.get("crude")
    _fdi_badge  = nws.get("fdi",  {}).get("badge", "badge-b")
    _fii_badge  = nws.get("fii",  {}).get("badge", "badge-b")
    _cpi_badge  = nws.get("cpi",  {}).get("badge", "badge-b")
    _semi_badge = nws.get("semi", {}).get("badge", "badge-b")
    _gdp_badge  = nws.get("gdp",  {}).get("badge", "badge-b")
    _trade_badge= nws.get("trade",{}).get("badge", "badge-b")
    _fii_txt    = nws.get("fii",  {}).get("text", "")
    _fdi_txt    = nws.get("fdi",  {}).get("text", "")

    # 긍정/부정 요인 수집
    good_parts = []
    bad_parts  = []
    if rsi_cls == "badge-g":  good_parts.append(f"RSI {rsi}(중립~강세)")
    elif rsi_cls == "badge-r": bad_parts.append(f"RSI {rsi}(과매도 또는 약세)")
    if ma_cls == "badge-g":   good_parts.append(f"이평선 {ma_sig}")
    elif ma_cls == "badge-r": bad_parts.append(f"이평선 {ma_sig}")
    elif ma_cls == "badge-y": bad_parts.append(f"이평선 혼조")
    if mom_cls == "badge-g":  good_parts.append(f"모멘텀 {mom:+}%")
    elif mom_cls == "badge-r": bad_parts.append(f"모멘텀 {mom:+}%")
    if _fii_badge == "badge-g": good_parts.append(f"외국인 순매수({_fii_txt})")
    elif _fii_badge == "badge-r": bad_parts.append(f"외국인 순매도({_fii_txt})")
    if _fdi_badge == "badge-g": good_parts.append(f"FDI 유입({_fdi_txt})")
    elif _fdi_badge == "badge-r": bad_parts.append(f"FDI 감소")
    if _usdvnd and _usdvnd < 25500: good_parts.append(f"동화 안정(₫{_usdvnd:,})")
    elif _usdvnd and _usdvnd >= 26500: bad_parts.append(f"동화 급락(₫{_usdvnd:,})")
    if _cpi_badge == "badge-g":  good_parts.append("물가 안정")
    elif _cpi_badge == "badge-r": bad_parts.append("물가 상승 압력")
    if _gdp_badge == "badge-g":  good_parts.append("GDP 호조")
    if _semi_badge == "badge-g": good_parts.append("반도체·제조업 수혜")
    elif _semi_badge == "badge-r": bad_parts.append("제조업 수주 둔화")
    if _trade_badge == "badge-g": good_parts.append("미-베트남 무역 호조")
    elif _trade_badge == "badge-r": bad_parts.append("무역 리스크")
    if _vix and _vix >= 25: bad_parts.append(f"글로벌 공포지수 VIX {_vix}")
    if _crude and _crude >= 90: bad_parts.append(f"고유가(${_crude})")

    if sc_label == "강매수":
        sc_desc = (
            f"기술·매크로·뉴스 신호가 전반적으로 긍정적입니다. "
            + (f"✅ {', '.join(good_parts[:4])} 신호가 동시에 켜진 강한 매수 구간입니다. " if good_parts else "")
            + "지금은 분할 매수를 적극 고려할 수 있는 시점입니다."
        )
    elif sc_label == "매수 검토":
        sc_desc = (
            f"기술적 흐름이 개선 중입니다. "
            + (f"✅ {', '.join(good_parts[:3])}. " if good_parts else "")
            + (f"⚠️ {', '.join(bad_parts[:2])} 리스크 잔존. " if bad_parts else "")
            + "소규모 선진입 후 신호 강화 시 추가 매수로 대응하세요."
        )
    elif sc_label == "관망":
        sc_desc = (
            (f"✅ {', '.join(good_parts[:2])} 긍정적이나, " if good_parts else "신호가 혼재합니다. ")
            + (f"⚠️ {', '.join(bad_parts[:3])} 부담이 남아 있습니다. " if bad_parts else "")
            + "이평선 정배열 전환 또는 외국인 순매수 전환을 확인한 뒤 진입을 고려하세요."
        )
    elif sc_label == "조심":
        sc_desc = (
            f"부정 신호가 우세합니다. "
            + (f"⚠️ {', '.join(bad_parts[:4])} 상태입니다. " if bad_parts else "")
            + (f"(긍정 요인: {', '.join(good_parts[:2])}) " if good_parts else "")
            + "신규 진입은 자제하고 보유 중이라면 손절선을 재점검하세요."
        )
    else:
        sc_desc = (
            f"복수의 위험 신호가 동시에 켜져 있습니다. "
            + (f"⚠️ {', '.join(bad_parts)} 모두 부정적입니다. " if bad_parts else "")
            + "비중 축소 또는 현금 보유를 우선 고려하고 추세 반전 확인 후 재진입하세요."
        )

    scorecard_html = f"""<div style="background:{sc_bg};border:1px solid {sc_color}33;border-radius:18px;padding:18px 20px;margin-bottom:20px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <div>
        <div style="font-size:11px;font-weight:600;color:{sc_color};letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px;">종합 매수 신호</div>
        <div id="sc-emoji" style="font-size:28px;font-weight:700;color:{sc_color};">{sc_emoji} {sc_label}</div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:11px;color:var(--text3);margin-bottom:4px;">신호 강도</div>
        <div id="sc-pct" style="font-size:24px;font-weight:700;color:{sc_color};">{score_pct}점</div>
        <div style="font-size:10px;color:var(--text3);">/ 100점</div>
      </div>
    </div>
    <div style="background:rgba(0,0,0,0.08);border-radius:6px;height:8px;overflow:hidden;margin-bottom:10px;">
      <div id="sc-bar" style="width:{score_pct}%;height:100%;border-radius:6px;background:{sc_color};transition:width 0.6s;"></div>
    </div>
    <div style="display:flex;gap:16px;font-size:11px;color:var(--text2);">
      <span>기술적 <strong id="sc-tech" style="color:{sc_color};">{'+' if tech_score>=0 else ''}{tech_score:.1f}</strong></span>
      <span>매크로 <strong id="sc-macro" style="color:{sc_color};">{'+' if macro_score>=0 else ''}{macro_score:.1f}</strong></span>
      <span>뉴스 <strong id="sc-news" style="color:{sc_color};">{'+' if news_score>=0 else ''}{news_score:.1f}</strong></span>
    </div>
    <div id="sc-desc" style="margin-top:10px;font-size:12px;color:var(--text2);line-height:1.6;padding:10px 12px;background:rgba(0,0,0,0.04);border-radius:10px;">{sc_desc}</div>
  </div>"""

    # ── 매수 계획 카드 ──────────────────────────────────────────
    add1 = add // 2
    add2 = add // 2
    total_plan = invest + add

    plan_rows = ""
    for label, amt in [("1차 매수", invest), ("2차 분할매수", add1), ("3차 분할매수", add2)]:
        plan_rows += f"""<tr>
          <td style="color:var(--text2);">{label}</td>
          <td style="text-align:right;font-weight:600;">{amt:,}만원</td>
          <td style="text-align:right;color:var(--text3);">현재가 {current:,.2f}pt 기준</td>
        </tr>"""

    plan_card = f"""  <div class="card">
    <div class="card-title" style="margin-bottom:10px;">💰 투자 계획</div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="color:var(--text2);font-size:11px;border-bottom:1px solid var(--border);">
          <th style="text-align:left;padding:5px 0;font-weight:500;">단계</th>
          <th style="text-align:right;padding:5px 0;font-weight:500;">금액</th>
          <th style="text-align:right;padding:5px 0;font-weight:500;">비고</th>
        </tr>
      </thead>
      <tbody style="line-height:2.2;">{plan_rows}
        <tr style="border-top:1px solid var(--border);font-weight:600;">
          <td>합계</td>
          <td style="text-align:right;">{total_plan:,}만원</td>
          <td></td>
        </tr>
      </tbody>
    </table>
    <div style="margin-top:12px;padding:10px;background:var(--bg);border-radius:8px;font-size:12px;">
      <div style="color:var(--text2);margin-bottom:4px;">현재 VN-Index {current:,.2f}pt 기준 손절선</div>
      <div style="font-size:16px;font-weight:700;color:var(--down);">{sl_price:,.2f}pt <span style="font-size:12px;font-weight:400;color:var(--text3);">(-{sl_pct}%)</span></div>
    </div>
  </div>"""

    # ── 목표 수익률 계산기 ───────────────────────────────────────
    exit_rows = ""
    for tgt in [10, 20, 30, 50]:
        t_vn = round(current * (1 + tgt / 100), 2)
        t_profit = round(invest * tgt / 100, 1)
        exit_rows += f"""<tr>
          <td>+{tgt}%</td>
          <td style="text-align:right;font-weight:600;">{t_vn:,.2f}</td>
          <td style="text-align:right;color:var(--up);">+{t_profit}만원</td>
        </tr>"""

    exit_card = f"""  <div class="card">
    <div class="card-title" style="margin-bottom:10px;">🎯 목표수익 시뮬레이션</div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="color:var(--text2);font-size:11px;border-bottom:1px solid var(--border);">
          <th style="text-align:left;padding:5px 0;font-weight:500;">목표 수익률</th>
          <th style="text-align:right;padding:5px 0;font-weight:500;">필요 VN-Index</th>
          <th style="text-align:right;padding:5px 0;font-weight:500;">수익금</th>
        </tr>
      </thead>
      <tbody style="line-height:2.2;">{exit_rows}</tbody>
    </table>
    <div style="margin-top:8px;font-size:11px;color:var(--text3);">* 현재 VN-Index {current:,.2f}pt 기준 / {invest:,}만원 1차 매수 가정</div>
  </div>"""

    # ── 액션 가이드 HTML ─────────────────────────────────────────
    ag = action_guide
    if ag:
        now_type = ag.get("now", {}).get("type", "hold")
        now_cls  = {"hold": "action-hold", "buy": "action-buy", "sell": "action-sell"}.get(now_type, "action-hold")
        action_guide_html = f"""
  <div class="action {now_cls}" id="ag-now">
    <div class="action-title" id="ag-now-title">{ag['now']['title']}</div>
    <div class="action-desc" id="ag-now-desc">{ag['now']['desc']}</div>
  </div>
  <div class="action action-buy" id="ag-buy1">
    <div class="action-title" id="ag-buy1-title">{ag['buy1']['title']}</div>
    <div class="action-desc" id="ag-buy1-desc">{ag['buy1']['desc']}</div>
  </div>
  <div class="action action-buy" id="ag-buy2">
    <div class="action-title" id="ag-buy2-title">{ag['buy2']['title']}</div>
    <div class="action-desc" id="ag-buy2-desc">{ag['buy2']['desc']}</div>
  </div>
  <div class="action action-sell" id="ag-sell">
    <div class="action-title" id="ag-sell-title">{ag['sell']['title']}</div>
    <div class="action-desc" id="ag-sell-desc">{ag['sell']['desc']}</div>
  </div>"""
    else:
        action_guide_html = f"""
  <div class="action action-hold" id="ag-now">
    <div class="action-title" id="ag-now-title">📌 지금 — 관망 중</div>
    <div class="action-desc" id="ag-now-desc">데이터 수집 중입니다. 다시 열어주세요.</div>
  </div>
  <div class="action action-buy" id="ag-buy1">
    <div class="action-title" id="ag-buy1-title">🟢 1차 매수 조건</div>
    <div class="action-desc" id="ag-buy1-desc">RSI 과매도 + 이평 정배열 전환 시 → {invest:,}만원 투입</div>
  </div>
  <div class="action action-buy" id="ag-buy2">
    <div class="action-title" id="ag-buy2-title">🟢 2차 분할 매수 조건</div>
    <div class="action-desc" id="ag-buy2-desc">1차 매수 후 추가 하락 시 분할로 → {add1:,}만원 씩</div>
  </div>
  <div class="action action-sell" id="ag-sell">
    <div class="action-title" id="ag-sell-title">🔴 손절 조건</div>
    <div class="action-desc" id="ag-sell-desc">매수가 대비 -{sl_pct}% 이탈 시 → 전량 손절 검토</div>
  </div>"""

    # ── 이벤트 일정 ──────────────────────────────────────────────
    events_html = ""
    if events:
        today = datetime.now().date()
        rows = ""
        for ev in sorted(events, key=lambda x: x["날짜"]):
            try:
                from datetime import date as date_cls
                ev_date = date_cls.fromisoformat(ev["날짜"])
                diff = (ev_date - today).days
                if diff < 0:
                    continue
                if diff == 0:
                    d_txt, d_cls = "오늘", "color:var(--down);font-weight:700;"
                elif diff <= 7:
                    d_txt, d_cls = f"D-{diff}", "color:var(--down);font-weight:600;"
                elif diff <= 30:
                    d_txt, d_cls = f"D-{diff}", "color:var(--warn-text);font-weight:500;"
                else:
                    d_txt, d_cls = f"D-{diff}", "color:var(--text3);"
                rows += f'<tr><td style="color:var(--text2);">{ev["날짜"][5:]}</td><td>{ev["내용"]}</td><td style="text-align:right;{d_cls}">{d_txt}</td></tr>'
            except Exception:
                pass
        if rows:
            events_html = f"""<div class="section-label">주요 이벤트 일정</div>
  <div class="card" style="margin-bottom:16px;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <tbody style="line-height:2.2;">{rows}</tbody>
    </table>
  </div>
  <hr class="divider" style="margin-top:0;">"""

    # AI Q&A 컨텍스트에 들어갈 뉴스 텍스트 미리 계산
    _n_fdi   = nws.get('fdi',   {}).get('text', '정보없음')
    _n_fii   = nws.get('fii',   {}).get('text', '정보없음')
    _n_sbv   = nws.get('sbv',   {}).get('text', '정보없음')
    _n_fed   = nws.get('fed',   {}).get('text', '정보없음')
    _n_trade = nws.get('trade', {}).get('text', '정보없음')
    _n_cpi   = nws.get('cpi',   {}).get('text', '정보없음')
    _vn_chg_sign = '+' if vn['change_pct'] >= 0 else ''

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>베트남 펀드 대시보드</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --bg: #f5f5f7;
  --card-bg: #ffffff;
  --text: #1d1d1f;
  --text2: #6e6e73;
  --text3: #aeaeb2;
  --border: rgba(0,0,0,0.1);
  --up: #2d8a4e;
  --down: #c0392b;
  --warn-bg: #fff8e1;
  --warn-text: #BA7517;
  --buy-bg: #f0faf0;
  --buy-text: #2d6a0a;
  --sell-bg: #fff0f0;
  --sell-text: #9b2020;
  --badge-r-bg: #fde8e8; --badge-r: #c0392b;
  --badge-g-bg: #e8fde8; --badge-g: #2d6a0a;
  --badge-y-bg: #fdf6e8; --badge-y: #BA7517;
  --badge-b-bg: #e8f0fe; --badge-b: #1565c0;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #1c1c1e; --card-bg: #2c2c2e; --text: #f2f2f7; --text2: #aeaeb2; --text3: #636366;
    --border: rgba(255,255,255,0.1); --up: #4cd964; --down: #ff453a;
    --warn-bg: #2a2200; --warn-text: #ffd60a;
    --buy-bg: #0d2200; --buy-text: #4cd964;
    --sell-bg: #2a0000; --sell-text: #ff453a;
    --badge-r-bg: #2a0a0a; --badge-r: #ff6b6b;
    --badge-g-bg: #0a1a0a; --badge-g: #6fcf97;
    --badge-y-bg: #1a1200; --badge-y: #f2c94c;
    --badge-b-bg: #001a2a; --badge-b: #56ccf2;
  }}
}}
body {{ font-family: -apple-system, 'Apple SD Gothic Neo', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}
.container {{ max-width: 480px; margin: 0 auto; padding: 20px 16px 40px; }}
.header {{ margin-bottom: 24px; }}
.header h1 {{ font-size: 22px; font-weight: 700; }}
.header p {{ font-size: 13px; color: var(--text2); margin-top: 4px; }}
.section-label {{ font-size: 11px; font-weight: 600; color: var(--text3); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; }}
.card {{ background: var(--card-bg); border-radius: 16px; padding: 16px; margin-bottom: 16px; border: 0.5px solid var(--border); }}
.card-title {{ font-size: 14px; font-weight: 600; margin-bottom: 14px; }}
.nifty-header {{ background: var(--card-bg); border-radius: 16px; padding: 16px; margin-bottom: 12px; border: 0.5px solid var(--border); }}
.nifty-name {{ font-size: 13px; color: var(--text2); margin-bottom: 6px; }}
.nifty-price {{ font-size: 36px; font-weight: 700; letter-spacing: -1px; }}
.nifty-change {{ font-size: 15px; font-weight: 500; margin-top: 4px; }}
.ohlc-row {{ display: flex; gap: 0; margin-top: 12px; border-top: 0.5px solid var(--border); padding-top: 12px; }}
.ohlc-item {{ flex: 1; text-align: center; }}
.ohlc-label {{ font-size: 11px; color: var(--text3); margin-bottom: 3px; }}
.ohlc-val {{ font-size: 13px; font-weight: 600; }}
.period-tabs {{ display: flex; gap: 4px; margin-bottom: 10px; }}
.period-tab {{ flex: 1; text-align: center; font-size: 12px; font-weight: 500; padding: 7px 0; border-radius: 8px; border: 0.5px solid var(--border); background: var(--bg); color: var(--text2); cursor: pointer; }}
.period-tab.active {{ background: var(--text); color: var(--bg); border-color: var(--text); }}
.chart-wrap {{ height: 230px; margin-bottom: 8px; }}
.signal-row {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 0.5px solid var(--border); }}
.signal-row:last-child {{ border-bottom: none; }}
.signal-name {{ font-size: 13px; color: var(--text2); }}
.badge {{ font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 8px; }}
.badge-r {{ background: var(--badge-r-bg); color: var(--badge-r); }}
.badge-g {{ background: var(--badge-g-bg); color: var(--badge-g); }}
.badge-y {{ background: var(--badge-y-bg); color: var(--badge-y); }}
.badge-b {{ background: var(--badge-b-bg); color: var(--badge-b); }}
.action {{ border-radius: 12px; padding: 13px 15px; margin-bottom: 10px; }}
.action-hold {{ background: var(--warn-bg); border-left: 3px solid var(--warn-text); }}
.action-buy  {{ background: var(--buy-bg);  border-left: 3px solid var(--buy-text); }}
.action-sell {{ background: var(--sell-bg); border-left: 3px solid var(--sell-text); }}
.action-title {{ font-size: 13px; font-weight: 600; margin-bottom: 5px; }}
.action-hold .action-title {{ color: var(--warn-text); }}
.action-buy  .action-title {{ color: var(--buy-text); }}
.action-sell .action-title {{ color: var(--sell-text); }}
.action-desc {{ font-size: 12px; color: var(--text2); line-height: 1.6; }}
.divider {{ border: none; border-top: 0.5px solid var(--border); margin: 20px 0; }}
table td {{ padding: 5px 0; border-bottom: 1px solid var(--border); }}
.up {{ color: var(--up); }}
.down {{ color: var(--down); }}
.input-row {{ display: flex; gap: 8px; margin-bottom: 10px; }}
.input-row input {{ flex: 1; font-size: 13px; padding: 10px 12px; border: 0.5px solid var(--border); border-radius: 10px; background: var(--bg); color: var(--text); outline: none; }}
.input-row input:focus {{ border-color: #0071e3; }}
.btn {{ font-size: 13px; padding: 10px 16px; border: 0.5px solid var(--border); border-radius: 10px; background: var(--card-bg); color: var(--text); cursor: pointer; white-space: nowrap; font-weight: 500; }}
.quick-btns {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }}
.quick-btn {{ font-size: 11px; padding: 6px 11px; }}
.ai-response {{ font-size: 13px; color: var(--text); line-height: 1.8; padding: 14px; background: var(--bg); border-radius: 10px; min-height: 60px; white-space: pre-wrap; }}
.footer {{ font-size: 11px; color: var(--text3); text-align: center; margin-top: 20px; }}
</style>
</head>
<body>
<div class="container">

  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div class="header" style="margin-bottom:0;">
      <h1>🇻🇳 베트남 펀드 대시보드</h1>
      <p>VN-Index 기반 매수 타이밍 분석 · 매수 전 관찰 중</p>
    </div>
    <button onclick="location.reload(true)" style="margin-top:4px;padding:7px 18px;border-radius:20px;border:0.5px solid var(--border);background:var(--card-bg);color:var(--text);font-size:13px;font-weight:500;cursor:pointer;flex-shrink:0;">🔄 새로고침</button>
  </div>

  {scorecard_html}

  <div class="section-label">VN-Index (호치민 지수)</div>
  {vn_section}

  <hr class="divider">

  {events_html}

  <div class="section-label">매수 계획</div>
  {plan_card}
  {exit_card}

  <hr class="divider">

  <div class="section-label">매매 신호</div>
  <div class="card">
    <div class="card-title" style="margin-bottom:8px;">📡 기술적 지표 (자동)</div>
    {tech_signals_html}
  </div>
  {news_card_html}

  <hr class="divider">

  <div class="section-label">매수 타이밍 가이드</div>
  {action_guide_html}

  <hr class="divider">

  <div class="section-label">AI 매수 판단 질문</div>
  <div class="card">
    <div class="card-title">지금 상황 물어보기</div>
    <div id="td-key-setup" style="margin-bottom:10px;background:#f8f9fa;border-radius:10px;padding:12px;">
      <div id="td-key-connected" style="display:none;font-size:12px;color:var(--text2);">✅ TwelveData 실시간 연동 중 &nbsp;<button class="btn" style="font-size:11px;padding:4px 10px;" onclick="document.getElementById('td-key-connected').style.display='none';document.getElementById('td-key-input-row').style.display='flex';">🔑 키 변경</button></div>
      <div id="td-key-input-row" style="display:none;flex-direction:column;gap:6px;">
        <div style="font-size:12px;color:var(--text2);">📡 실시간 시세 연동을 위해 <b>TwelveData API 키</b>가 필요해요 (<a href="https://twelvedata.com" target="_blank">twelvedata.com</a> 무료 가입)</div>
        <div class="input-row">
          <input type="password" id="td-key-input" placeholder="TwelveData API 키 입력" style="flex:1;padding:8px 10px;border:1px solid var(--border);border-radius:8px;font-size:13px;background:var(--card-bg);color:var(--text);">
          <button class="btn" onclick="saveTDKey()">저장</button>
        </div>
      </div>
    </div>
    <div id="key-setup" style="margin-bottom:10px;display:none;">
      <div style="font-size:12px;color:var(--text3);margin-bottom:6px;">Anthropic API 키를 입력하면 저장됩니다 (이 기기에만)</div>
      <div class="input-row">
        <input type="password" id="api-key-input" placeholder="sk-ant-...">
        <button class="btn" onclick="saveKey()">저장</button>
      </div>
    </div>
    <div class="input-row">
      <input type="text" id="ai-q" placeholder="예: 지금 매수 타이밍인가요?">
      <button class="btn" onclick="askAI()">분석 ↗</button>
    </div>
    <div class="quick-btns">
      <button class="btn quick-btn" onclick="setQ('지금 1차 매수 타이밍인가요?')">1차 매수?</button>
      <button class="btn quick-btn" onclick="setQ('VN-Index 하락 원인이 뭔가요?')">하락 이유</button>
      <button class="btn quick-btn" onclick="setQ('이번 주 베트남 시장 핵심 이슈가 뭔가요?')">이번 주 이슈</button>
      <button class="btn quick-btn" onclick="toggleKeySetup()">🔑 키 변경</button>
    </div>
    <div class="ai-response" id="ai-resp">질문을 입력하거나 위 버튼을 눌러보세요.</div>
  </div>

  <div class="footer">
    마지막 업데이트: {updated_at}
    <br><br>
    <button onclick="location.reload(true)" style="margin-top:4px;padding:8px 24px;border-radius:20px;border:0.5px solid var(--border);background:var(--card-bg);color:var(--text);font-size:13px;font-weight:500;cursor:pointer;">🔄 새로고침</button>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const isDark = matchMedia('(prefers-color-scheme: dark)').matches;
const tC = isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.4)';
const gC = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)';

function calcMA(prices, n) {{
  return prices.map((_, i) => {{
    if (i < n - 1) return null;
    const slice = prices.slice(i - n + 1, i + 1);
    return +(slice.reduce((a, b) => a + b, 0) / n).toFixed(2);
  }});
}}

const MA_CONFIG = {{
  d1:  [{{n:5, color:'#FF6B6B',label:'MA5'}}, {{n:20,color:'#FFA500',label:'MA20'}}],
  d5:  [{{n:3, color:'#FF6B6B',label:'MA3'}}, {{n:5, color:'#FFA500',label:'MA5'}}],
  d30: [{{n:5, color:'#FF6B6B',label:'MA5'}}, {{n:10,color:'#FFA500',label:'MA10'}}],
  mo3: [{{n:4, color:'#FF6B6B',label:'MA4주'}},{{n:8, color:'#FFA500',label:'MA8주'}}],
  mo6: [{{n:5, color:'#FF6B6B',label:'MA5주'}},{{n:13,color:'#FFA500',label:'MA13주'}}],
  yr1: [{{n:5, color:'#FF6B6B',label:'MA5주'}},{{n:13,color:'#FFA500',label:'MA13주'}},{{n:26,color:'#9B59B6',label:'MA26주'}}],
}};

function makeDatasets(prices, periodKey, name, sl) {{
  const n = prices.length;
  const maCfg = MA_CONFIG[periodKey] || MA_CONFIG.yr1;
  const maDatasets = maCfg.filter(p => p.n < n).map(p => ({{
    label: p.label, data: calcMA(prices, p.n),
    borderColor: p.color, borderWidth: 1.2,
    pointRadius: 0, fill: false, tension: 0.3, spanGaps: false
  }}));
  return [
    {{ label: name || 'VN-Index', data: prices, borderColor: '#EA1F26',
       backgroundColor: 'rgba(234,31,38,0.06)', borderWidth: 2,
       pointRadius: 0, pointHoverRadius: 4, fill: true, tension: 0.3 }},
    ...maDatasets
  ];
}}

function initChart(canvasId, pdata, initKey) {{
  return new Chart(document.getElementById(canvasId), {{
    type: 'line',
    data: {{ labels: pdata[initKey].labels, datasets: makeDatasets(pdata[initKey].prices, initKey, pdata.name, pdata.sl) }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: true, position: 'top', labels: {{ color: tC, font: {{ size: 10 }}, boxWidth: 20, padding: 8 }} }},
        tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + (ctx.parsed.y ? ctx.parsed.y.toLocaleString() : '-') }} }}
      }},
      scales: {{
        x: {{ ticks: {{ color: tC, font: {{ size: 10 }}, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }}, grid: {{ color: gC }} }},
        y: {{ ticks: {{ color: tC, font: {{ size: 10 }}, callback: v => v.toLocaleString() }}, grid: {{ color: gC }} }}
      }}
    }}
  }});
}}

function switchChart(canvasId, prefix, key, el) {{
  document.querySelectorAll(`#${{prefix}}-tabs .period-tab`).forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  const c = window._charts[canvasId];
  c.inst.data.labels = c.data[key].labels;
  c.inst.data.datasets = makeDatasets(c.data[key].prices, key, c.data.name, c.data.sl);
  c.inst.update();
}}

function getKey() {{ return localStorage.getItem('anthropic_api_key') || ''; }}
function saveKey() {{
  const k = document.getElementById('api-key-input').value.trim();
  if (!k) return;
  localStorage.setItem('anthropic_api_key', k);
  document.getElementById('api-key-input').value = '';
  document.getElementById('key-setup').style.display = 'none';
  document.getElementById('ai-resp').textContent = 'API 키가 저장됐어요. 질문을 입력해보세요.';
}}
function toggleKeySetup() {{
  const el = document.getElementById('key-setup');
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}}
function getTDKey() {{ return localStorage.getItem('twelvedata_api_key') || ''; }}
function saveTDKey() {{
  const k = document.getElementById('td-key-input').value.trim();
  if (!k) return;
  localStorage.setItem('twelvedata_api_key', k);
  document.getElementById('td-key-input').value = '';
  document.getElementById('td-key-connected').style.display = 'block';
  document.getElementById('td-key-input-row').style.display = 'none';
}}
function initTDKeyUI() {{
  const connected = document.getElementById('td-key-connected');
  const inputRow = document.getElementById('td-key-input-row');
  if (!connected || !inputRow) return;
  connected.style.display = 'block';
  inputRow.style.display = 'none';
}}
async function fetchYahooProxy(ticker) {{
  try {{
    const target = encodeURIComponent(`https://query2.finance.yahoo.com/v8/finance/chart/${{ticker}}?interval=1d&range=1d`);
    const r = await fetch(`https://corsproxy.io/?${{target}}`);
    if (!r.ok) return null;
    const j = await r.json();
    const meta = j.chart.result[0].meta;
    const price = meta.regularMarketPrice;
    const prev = meta.chartPreviousClose || meta.previousClose || price;
    return {{ price, prev, pct: prev ? (price - prev) / prev * 100 : 0 }};
  }} catch(e) {{ return null; }}
}}
async function fetchTDData(symbols) {{
  const tickers = {{
    'VNM':     'VNM',
    'USD/VND': 'USDVND%3DX',
    'USD/CNY': 'USDCNY%3DX',
    'DXY':     'DX-Y.NYB',
    'EEM':     'EEM',
    'VIX':     '%5EVIX',
    'BCO/USD': 'BZ%3DF',
    'XAU/USD': 'GC%3DF',
  }};
  const result = {{}};
  await Promise.all(symbols.map(async sym => {{
    const yf = tickers[sym];
    if (!yf) return;
    const d = await fetchYahooProxy(yf);
    if (d) result[sym] = d;
  }}));
  return result;
}}
function setBadge(id, text, cls) {{
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = 'badge ' + cls;
}}
async function fetchLiveData() {{
  const td = await fetchTDData(['VNM','USD/VND','USD/CNY','DXY','EEM','VIX','BCO/USD','XAU/USD']).catch(() => ({{}}));
  const fmt = (v, d=2) => v != null ? v.toLocaleString('ko-KR', {{maximumFractionDigits: d}}) : '-';
  const arrow = pct => pct >= 0 ? '▲' : '▼';
  if (td['VNM']) {{ const v=td['VNM']; const c=v.pct>=0?'badge-g':'badge-r'; setBadge('badge-vnm',`$${{fmt(v.price)}} ${{arrow(v.pct)}}${{Math.abs(v.pct).toFixed(2)}}% — ${{v.pct>=0?'상승':'하락'}}`,c); }}
  if (td['USD/VND']) {{ const v=td['USD/VND']; const c=v.price>26500?'badge-r':v.price>25500?'badge-y':v.price>24500?'badge-b':'badge-g'; const l=v.price>26500?'동 급락':v.price>25500?'동 약세':v.price>24500?'안정':'동 강세'; setBadge('badge-usdvnd',`₫${{fmt(v.price,0)}} — ${{l}}`,c); }}
  if (td['USD/CNY']) {{ const v=td['USD/CNY']; const c=v.price<7.1?'badge-g':v.price<7.3?'badge-y':'badge-r'; const l=v.price<7.1?'위안 안정':v.price<7.3?'위안 약세':'위안 급약세'; setBadge('badge-usdcny',`¥${{fmt(v.price)}} — ${{l}}`,c); }}
  if (td['DXY']) {{ const v=td['DXY']; const c=v.price>105?'badge-r':v.price>100?'badge-y':'badge-b'; setBadge('badge-dxy',`DXY ${{fmt(v.price)}} ${{arrow(v.pct)}}${{Math.abs(v.pct).toFixed(2)}} — ${{v.price>105?'달러 강세':v.price>100?'달러 강세 주의':'안정'}}`,c); }}
  if (td['EEM']) {{ const v=td['EEM']; const c=v.pct>=0.5?'badge-g':v.pct>=-0.5?'badge-b':'badge-r'; setBadge('badge-eem',`$${{fmt(v.price)}} ${{arrow(v.pct)}}${{Math.abs(v.pct).toFixed(2)}}% — ${{v.pct>=0.5?'상승':v.pct>=-0.5?'보합':'하락'}}`,c); }}
  if (td['VIX']) {{ const v=td['VIX']; const c=v.price>25?'badge-r':v.price>18?'badge-y':'badge-g'; setBadge('badge-vix',`US VIX ${{fmt(v.price,1)}} — ${{v.price>25?'공포':v.price>18?'불안':'안정'}}`,c); }}
  if (td['BCO/USD']) {{ const v=td['BCO/USD']; const c=v.price>90?'badge-r':v.price>80?'badge-y':'badge-g'; setBadge('badge-crude',`$${{fmt(v.price,1)}} ${{v.price>90?'고유가':v.price>80?'보통':'저유가'}}`,c); }}
  if (td['XAU/USD']) {{ const v=td['XAU/USD']; const c=v.pct>1?'badge-r':v.pct>0?'badge-y':'badge-g'; setBadge('badge-gold',`$${{fmt(v.price,0)}} ${{arrow(v.pct)}}${{Math.abs(v.pct).toFixed(1)}}% — ${{v.pct>1?'위험회피 심리 강함':'안정'}}`,c); }}
  return td;
}}
async function updateActionGuide(td) {{
  const API_KEY = getKey();
  if (!API_KEY) return;
  if (!td) td = await fetchLiveData().catch(() => ({{}}));
  const fmt = (sym, d=2) => td[sym] ? td[sym].price.toLocaleString('ko-KR',{{maximumFractionDigits:d}}) : '-';
  const pct  = sym => td[sym] ? `${{td[sym].pct>=0?'▲':'▼'}}${{Math.abs(td[sym].pct).toFixed(2)}}%` : '';
  const ctx = `당신은 10년차 베트남 펀드 매니저입니다.
현재 상황: 베트남 VN-Index 펀드 매수 전 관찰 중 (아직 미매수)
투자 계획: 1차 {invest:,}만원, 추가 {add:,}만원 분할, 손절 -{sl_pct}%

[실시간 시장 데이터]
- VNM ETF: $${{fmt('VNM')}} (${{pct('VNM')}})
- USD/VND: ₫${{fmt('USD/VND',0)}} / USD/CNY: ¥${{fmt('USD/CNY')}}
- DXY: ${{fmt('DXY')}} / EEM: $${{fmt('EEM')}} (${{pct('EEM')}})
- US VIX: ${{fmt('VIX',1)}} / 브렌트유: $${{fmt('BCO/USD',1)}} / 금: $${{fmt('XAU/USD',0)}}`;
  const prompt = `위 실시간 데이터를 바탕으로 지금 시점의 액션 가이드를 JSON으로 작성해주세요.
반드시 아래 형식만 출력하세요 (다른 텍스트 없이):
{{"now_title":"📌 지금 — [한 줄 현황]","now_desc":"[현재 상황 2문장]","buy1_title":"🟢 1차 매수 조건","buy1_desc":"[1차 매수 조건 2문장]","buy2_title":"🟢 2차 매수 조건","buy2_desc":"[2차 매수 조건 2문장]","sell_title":"🔴 손절 조건","sell_desc":"[손절 조건 1~2문장]"}}`;
  try {{
    const r = await fetch('https://api.anthropic.com/v1/messages', {{
      method: 'POST',
      headers: {{ 'x-api-key': API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json', 'anthropic-dangerous-direct-browser-access': 'true' }},
      body: JSON.stringify({{ model: 'claude-haiku-4-5-20251001', max_tokens: 600, system: ctx, messages: [{{ role: 'user', content: prompt }}] }})
    }});
    const d = await r.json();
    const text = d.content?.[0]?.text || '';
    const match = text.match(/\{{[\s\S]*\}}/);
    if (!match) return;
    const ag = JSON.parse(match[0]);
    if (ag.now_title)  {{ document.getElementById('ag-now-title').textContent  = ag.now_title;  document.getElementById('ag-now-desc').textContent  = ag.now_desc; }}
    if (ag.buy1_title) {{ document.getElementById('ag-buy1-title').textContent = ag.buy1_title; document.getElementById('ag-buy1-desc').textContent = ag.buy1_desc; }}
    if (ag.buy2_title) {{ document.getElementById('ag-buy2-title').textContent = ag.buy2_title; document.getElementById('ag-buy2-desc').textContent = ag.buy2_desc; }}
    if (ag.sell_title) {{ document.getElementById('ag-sell-title').textContent = ag.sell_title; document.getElementById('ag-sell-desc').textContent = ag.sell_desc; }}
  }} catch(e) {{}}
}}
if (!getKey()) document.getElementById('key-setup').style.display = 'block';
initTDKeyUI();
fetchLiveData().then(updateActionGuide);

function setQ(q) {{ document.getElementById('ai-q').value = q; }}

async function askAI() {{
  const q = document.getElementById('ai-q').value.trim();
  if (!q) return;
  const API_KEY = getKey();
  if (!API_KEY) {{
    document.getElementById('key-setup').style.display = 'block';
    document.getElementById('ai-resp').textContent = 'API 키를 먼저 입력해주세요.';
    return;
  }}
  const box = document.getElementById('ai-resp');
  box.textContent = '분석 중...';

  const _liveVN = (typeof _liveDataVN !== 'undefined' && _liveDataVN.vn) ? _liveDataVN.vn.toLocaleString('ko-KR',{{maximumFractionDigits:2}}) : '{current:,.2f}';
  const _liveVNPct = (typeof _liveDataVN !== 'undefined' && _liveDataVN.vnPct !== undefined) ? ((_liveDataVN.vnPct>=0)?'▲':'▼')+Math.abs(_liveDataVN.vnPct).toFixed(2)+'%' : '{_vn_chg_sign}{vn["change_pct"]}%';
  const _scVN = document.getElementById('sc-emoji')?.textContent?.trim() || '';
  const _todayVN = new Date().toLocaleDateString('ko-KR',{{year:'numeric',month:'long',day:'numeric'}});
  const ctx = `당신은 10년차 베트남 펀드 매니저입니다.
현재 상황: 베트남 VN-Index 펀드 매수 전 관찰 중 (아직 미매수)
투자 계획: 1차 {invest:,}만원, 추가 {add:,}만원 분할, 손절 -{sl_pct}%
오늘 날짜: ${{_todayVN}}

[실시간 시장 데이터]
- VN-Index: ${{_liveVN}} (${{_liveVNPct}})
- USD/VND: {mac.get('usdvnd','?'):,}동 / US VIX: {mac.get('vix','?')} / 브렌트유: ${mac.get('crude','?')}
- 종합신호: ${{_scVN}}
- FDI: {_n_fdi} / 외국인: {_n_fii}
- SBV 금리: {_n_sbv} / 미국 연준: {_n_fed}
- 미-베트남 무역: {_n_trade} / CPI: {_n_cpi}

3~5문장, 한국어, 마지막에 "이 답변은 참고용입니다" 짧게 명시.`;

  try {{
    const r = await fetch('https://api.anthropic.com/v1/messages', {{
      method: 'POST',
      headers: {{
        'Content-Type': 'application/json',
        'x-api-key': API_KEY,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true'
      }},
      body: JSON.stringify({{
        model: 'claude-sonnet-4-6',
        max_tokens: 600,
        system: ctx,
        messages: [{{ role: 'user', content: q }}]
      }})
    }});
    const d = await r.json();
    if (d.content?.[0]?.text) {{
      box.textContent = d.content[0].text;
    }} else {{
      box.textContent = '오류: ' + JSON.stringify(d.error || d);
    }}
  }} catch(e) {{
    box.textContent = '네트워크 오류: ' + e.message;
  }}
}}

document.getElementById('ai-q').addEventListener('keydown', e => {{ if (e.key === 'Enter') askAI(); }});

window._charts = {{}};
const PDATA_chartVN = {vn_periods_js};
window._charts['chartVN'] = {{inst: initChart('chartVN', PDATA_chartVN, 'd1'), data: PDATA_chartVN}};

// 페이지 열릴 때 신호 설명 자동 세팅
// 종합 투자 신호 설명은 업데이트.py 실행 시 실제 지표 기반으로 자동 생성됩니다.
</script>
</body>
</html>"""
    return html

# ── 카카오 알림 ──────────────────────────────────────────────────

def kakao_refresh_access_token(rest_api_key, refresh_token, client_secret=None):
    params = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        params["client_secret"] = client_secret
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        "https://kauth.kakao.com/oauth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read())
    if "access_token" not in result:
        raise RuntimeError(f"토큰 갱신 실패: {result}")
    return result["access_token"]


def kakao_send(access_token, text):
    template = json.dumps({
        "object_type": "text",
        "text": text,
        "link": {"web_url": "", "mobile_web_url": ""},
    }, ensure_ascii=False)
    data = urllib.parse.urlencode({"template_object": template}).encode()
    req = urllib.request.Request(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        data=data,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read())
    if result.get("result_code") != 0:
        raise RuntimeError(f"메시지 전송 실패: {result}")
    print("✅ 카카오 알림 전송 완료")


def generate_ai_commentary(vn, indicators, macro, cfg, api_key, signal_emoji=None, signal_desc=None):
    from datetime import timezone, timedelta
    KST = timezone(timedelta(hours=9))
    now_str = datetime.now(KST).strftime("%H:%M")
    buy_price = cfg.get("매수단가", 0)
    current = vn['current']
    pnl = (current - buy_price) / buy_price * 100 if buy_price else 0
    sc_line = f"{signal_emoji}\n" if signal_emoji else ""
    desc_line = f"\n{signal_desc}" if signal_desc else ""
    msg = (f"📊 베트남펀드 {now_str}\n"
           f"VN-Index {current:.0f} ({vn['change_pct']:+}%)\n"
           f"매수단가 {buy_price:.0f} / 손익 {pnl:+.1f}%\n"
           f"{sc_line}"
           f"{desc_line}")
    return msg.strip()


def check_action_guide_achievement(vn, indicators, macro, cfg, action_guide, api_key):
    if not api_key or not action_guide:
        return ""
    ind = indicators or {}
    mac = macro or {}
    buy_price = cfg.get("매수단가", 0)
    current = vn['current']
    pnl = (current - buy_price) / buy_price * 100 if buy_price else 0
    ag = action_guide
    prompt = f"""당신은 베트남 펀드 투자 어시스턴트입니다.
아래 [현재 데이터]와 [액션가이드]를 비교해서, 달성된 조건이 있으면 어떤 조건인지 한 문장으로 알려주세요.
달성된 조건이 없으면 "없음"이라고만 답하세요.

[현재 데이터]
- VN-Index: {current:.0f} ({vn['change_pct']:+}%)
- 매수단가: {buy_price:.0f} / 손익: {pnl:+.1f}%
- RSI(14주): {ind.get('rsi', '?')}
- 이평 배열: {ind.get('ma_signal', '?')}
- DXY: {mac.get('dxy', '?')}
- 미국 VIX: {mac.get('vix', '?')}

[액션가이드]
- 현재 상태: {ag.get('now', {}).get('desc', '')}
- 1차 매수 조건: {ag.get('buy1', {}).get('desc', '')}
- 2차 매수 조건: {ag.get('buy2', {}).get('desc', '')}
- 손절 조건: {ag.get('sell', {}).get('desc', '')}

달성된 조건만 간단히 알려주세요."""
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={"Content-Type": "application/json",
                     "x-api-key": api_key,
                     "anthropic-version": "2023-06-01"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
        answer = result["content"][0]["text"].strip()
        if "없음" in answer:
            return ""
        msg = f"🎯 [베트남펀드] 액션가이드 조건 달성!\n{answer}\n대시보드에서 확인하세요."
        return msg
    except Exception as e:
        print(f"달성 체크 실패: {e}")
        return ""


# ── 메인 ──────────────────────────────────────────────────────────
def main():
    cfg = load_config()
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic_api_key", "")).strip()
    newsapi_key = os.environ.get("NEWSAPI_KEY") or cfg.get("newsapi_key", "")
    from datetime import timezone, timedelta
    KST = timezone(timedelta(hours=9))
    updated_at = datetime.now(KST).strftime("%Y.%m.%d %H:%M")

    vn = fetch_vnindex()
    print(f"VN-Index 현재: {vn['current']:,} ({'+' if vn['change_pct']>=0 else ''}{vn['change_pct']}%)")

    print("매크로 지표 가져오는 중...")
    macro = fetch_macro_signals()

    print("뉴스 신호 수집 중...")
    news = fetch_news_signals(api_key, newsapi_key if newsapi_key else None)

    vn_ind = calc_indicators(vn["yr1"]["prices"])
    events = cfg.get("주요이벤트", [])

    # 종합신호 미리 계산
    _bmap_vn = {"badge-g": 1, "badge-y": 0, "badge-r": -1, "badge-b": 0}
    _rsi_vn = vn_ind.get("rsi", 50)
    _rsi_cls_vn = "badge-g" if _rsi_vn <= 30 else ("badge-r" if _rsi_vn >= 70 else "badge-b")
    _ma_cls_vn = "badge-g" if "정배열" in vn_ind.get("ma_signal","") else ("badge-r" if "역배열" in vn_ind.get("ma_signal","") else "badge-y")
    _mom_cls_vn = "badge-g" if vn_ind.get("momentum",0) > 1 else ("badge-r" if vn_ind.get("momentum",0) < -1 else "badge-y")
    _news_vn = sum(_bmap_vn.get(news.get(k,{}).get("badge","badge-b"),0) for k in ["fdi","fii","sbv","trade","cpi","fed"])
    _total_vn = sum(_bmap_vn.get(c,0)*1.5 for c in [_rsi_cls_vn,_ma_cls_vn,_mom_cls_vn]) + _news_vn*0.8
    _max_vn = 3*1.5 + 6*0.8
    if _total_vn >= _max_vn * 0.5:    sc_label_vn = "강매수"
    elif _total_vn >= _max_vn * 0.15: sc_label_vn = "매수 검토"
    elif _total_vn >= -_max_vn * 0.15: sc_label_vn = "관망"
    elif _total_vn >= -_max_vn * 0.5:  sc_label_vn = "조심"
    else:                               sc_label_vn = "진입 자제"
    print(f"  종합매수신호(미리보기): {sc_label_vn}")

    print("AI 차트 분석 생성 중...")
    vn_analysis = generate_chart_analysis(vn, api_key, scorecard_label=sc_label_vn)

    print("액션 가이드 생성 중...")
    action_guide = generate_action_guide(vn, vn_ind, macro, news, cfg, api_key, events=events, scorecard_label=sc_label_vn)

    html = build_html(vn, cfg, api_key, updated_at, vn_analysis,
                      indicators=vn_ind, macro=macro, news=news,
                      action_guide=action_guide, events=events)

    out_path = os.path.join(os.path.dirname(__file__), '베트남펀드_대시보드.html')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    idx_path = os.path.join(os.path.dirname(__file__), 'index.html')
    with open(idx_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"\n대시보드 업데이트 완료!")
    print(f"파일 위치: {out_path}")

    # ── 카카오 알림 발송 ──
    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()

    if rest_api_key and refresh_token:
        try:
            access_token = kakao_refresh_access_token(rest_api_key, refresh_token, client_secret or None)
            print("✅ 카카오 토큰 갱신 완료")

            import re as _re
            _html_path = os.path.join(os.path.dirname(__file__), "베트남펀드_대시보드.html")
            _html_txt = open(_html_path, encoding="utf-8").read()
            _em = _re.search(r'id="sc-emoji"[^>]*>([^<]+)<', _html_txt)
            _ds = _re.search(r'id="sc-desc"[^>]*>([^<]+)<', _html_txt)
            _pt = _re.search(r'id="sc-pct"[^>]*>([^<]+)<', _html_txt)
            _emoji = _em.group(1).strip() if _em else None
            _pct   = _pt.group(1).strip() if _pt else None
            signal_emoji = f"{_emoji} ({_pct})" if _emoji and _pct else _emoji
            signal_desc  = _ds.group(1).strip() if _ds else None
            commentary = generate_ai_commentary(vn, vn_ind, macro, cfg, api_key, signal_emoji=signal_emoji, signal_desc=signal_desc)
            if commentary:
                kakao_send(access_token, commentary)
                print("✅ AI 코멘트 발송 완료")
            else:
                print("ℹ️ AI 코멘트: 특이사항 없음 — 발송 안 함")

            achievement = check_action_guide_achievement(vn, vn_ind, macro, cfg, action_guide, api_key)
            if achievement:
                kakao_send(access_token, achievement)
                print("✅ 액션가이드 달성 알림 발송 완료")
            else:
                print("ℹ️ 액션가이드: 달성 조건 없음 — 발송 안 함")

        except Exception as e:
            print(f"카카오 알림 오류: {e}")
    else:
        print("⚠️ KAKAO 환경변수 없음 — 알림 건너뜀")

    import webbrowser
    webbrowser.open(f'file://{out_path}')

if __name__ == '__main__':
    main()
