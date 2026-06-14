#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
베트남 펀드 알림 체크 — 매일 GitHub Actions에서 실행
"""

import json
import os
import urllib.request
import urllib.parse
from datetime import datetime

import yfinance as yf


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


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "설정.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_vietnam_data():
    # VNM ETF로 주간 추세 계산 (^VNINDEX.VN은 당일 데이터만 가능)
    vnm = yf.Ticker("VNM")
    hist = vnm.history(period="1y", interval="1wk")
    vnm_prices = [float(row["Close"]) for _, row in hist.iterrows() if not row.isnull()["Close"]]

    # 현재 VN-Index 실제값은 ^VNINDEX.VN에서 가져와서 스케일 계산
    try:
        vn_now = yf.Ticker("^VNINDEX.VN").history(period="1d", interval="1d")
        vn_current = float(vn_now["Close"].iloc[-1]) if not vn_now.empty else None
        vnm_now = float(hist["Close"].iloc[-1]) if not hist.empty else None
        scale = vn_current / vnm_now if vn_current and vnm_now else 100
    except Exception:
        scale = 100

    prices = [p * scale for p in vnm_prices]

    current = prices[-1]
    prev = prices[-2] if len(prices) >= 2 else current

    ma5  = sum(prices[-5:])  / min(5,  len(prices))
    ma13 = sum(prices[-13:]) / min(13, len(prices))
    ma26 = sum(prices[-26:]) / min(26, len(prices))

    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else 0
    avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else 1
    rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss else 100

    prev_deltas = deltas[:-1]
    prev_gains  = [d for d in prev_deltas if d > 0]
    prev_losses = [-d for d in prev_deltas if d < 0]
    prev_avg_gain = sum(prev_gains[-14:]) / 14 if len(prev_gains) >= 14 else 0
    prev_avg_loss = sum(prev_losses[-14:]) / 14 if len(prev_losses) >= 14 else 1
    prev_rsi = 100 - (100 / (1 + prev_avg_gain / prev_avg_loss)) if prev_avg_loss else 100

    if ma5 > ma13 > ma26:
        ma_signal = "정배열"
    elif ma5 < ma13 < ma26:
        ma_signal = "역배열"
    else:
        ma_signal = "혼조"

    consecutive_down = 0
    for i in range(len(prices) - 1, 0, -1):
        if prices[i] < prices[i-1]:
            consecutive_down += 1
        else:
            break

    us_vix, dxy, eem = None, None, None
    try:
        us_vix = round(yf.Ticker("^VIX").fast_info.last_price, 1)
    except Exception:
        pass
    try:
        dxy_h = yf.Ticker("DX-Y.NYB").history(period="5d", interval="1d")
        if not dxy_h.empty:
            dxy = round(float(dxy_h["Close"].iloc[-1]), 2)
    except Exception:
        pass
    try:
        eem_h = yf.Ticker("EEM").history(period="5d", interval="1d")
        if len(eem_h) >= 2:
            eem_now = float(eem_h["Close"].iloc[-1])
            eem_prev = float(eem_h["Close"].iloc[-2])
            eem = round((eem_now - eem_prev) / eem_prev * 100, 2)
    except Exception:
        pass

    return {
        "current": round(current, 2),
        "rsi": round(rsi, 1),
        "prev_rsi": round(prev_rsi, 1),
        "ma_signal": ma_signal,
        "us_vix": us_vix,
        "dxy": dxy,
        "eem_change_pct": eem,
        "consecutive_down": consecutive_down,
    }


def check_vietnam_conditions(cfg, data):
    alerts = []
    current = data["current"]
    rsi = data["rsi"]
    prev_rsi = data["prev_rsi"]
    ma_signal = data["ma_signal"]
    dxy = data["dxy"]
    eem = data["eem_change_pct"]
    us_vix = data["us_vix"]
    buy_price = cfg.get("매수단가", 0)

    # ── 핵심 매수 조건 ──
    if 1720 <= current <= 1750:
        alerts.append({"type": "매수핵심",
            "msg": f"🟢 [베트남펀드] 매수 신호!\nVN-Index {current:.0f} → 1,720~1,750 진입\n지금 매수 검토하세요"})

    if prev_rsi > rsi and rsi <= 50 and prev_rsi >= 50:
        alerts.append({"type": "매수핵심",
            "msg": f"🟢 [베트남펀드] 매수 신호!\nRSI {prev_rsi} → {rsi} 하락, 중립선 이하\n지금 매수 검토하세요"})

    if ma_signal == "정배열":
        alerts.append({"type": "매수핵심",
            "msg": f"🟢 [베트남펀드] 매수 신호!\n이평선 정배열 전환 (VN-Index {current:.0f})\n지금 매수 검토하세요"})

    # ── 보조 매수 조건 ──
    if rsi <= 50:
        alerts.append({"type": "매수참고", "msg": f"📊 [베트남펀드] 참고: RSI {rsi} (중립 이하)"})
    if dxy and dxy <= 103:
        alerts.append({"type": "매수참고", "msg": f"📊 [베트남펀드] 참고: DXY {dxy} (달러 약세 호재)"})
    if eem and eem > 0:
        alerts.append({"type": "매수참고", "msg": f"📊 [베트남펀드] 참고: EEM {eem:+.1f}% (신흥국 자금 유입)"})
    if us_vix and us_vix <= 20:
        alerts.append({"type": "매수참고", "msg": f"📊 [베트남펀드] 참고: VIX {us_vix} (글로벌 안정)"})

    # ── 매도 조건 ──
    if buy_price > 0:
        gain_pct = (current - buy_price) / buy_price * 100
        if gain_pct >= 25:
            alerts.append({"type": "매도",
                "msg": f"🟡 [베트남펀드] 매도 신호!\n수익률 +{gain_pct:.1f}% (VN-Index {current:.0f})\n지금 매도하세요"})
        elif gain_pct >= 15:
            alerts.append({"type": "매도",
                "msg": f"🟡 [베트남펀드] 매도 신호!\n수익률 +{gain_pct:.1f}% (VN-Index {current:.0f})\n1차 수익실현 검토"})
    if rsi >= 70:
        alerts.append({"type": "매도", "msg": f"🟡 [베트남펀드] 매도 신호!\nRSI {rsi} 과매수\n매도 검토하세요"})

    # ── 손절 조건 ──
    if current <= 1612:
        alerts.append({"type": "손절",
            "msg": f"🔴 [베트남펀드] 손절 경고!\nVN-Index {current:.0f} → 손절선 1,612 이탈\n즉시 손절하세요"})
    if dxy and dxy >= 106:
        alerts.append({"type": "손절",
            "msg": f"🔴 [베트남펀드] 경고!\nDXY {dxy} → 달러 급강세\n포지션 점검 필요"})
    if us_vix and us_vix >= 30:
        alerts.append({"type": "손절",
            "msg": f"🔴 [베트남펀드] 경고!\n미국 VIX {us_vix} → 글로벌 공포\n포지션 점검 필요"})
    if data["consecutive_down"] >= 3:
        alerts.append({"type": "손절",
            "msg": f"🔴 [베트남펀드] 경고!\nVN-Index {data['consecutive_down']}주 연속 하락\n추세 점검 필요"})

    # ── 이벤트 알림 ──
    today = datetime.now().date()
    for ev in cfg.get("주요이벤트", []):
        try:
            ev_date = datetime.strptime(ev["날짜"], "%Y-%m-%d").date()
            diff = (ev_date - today).days
            if diff == 3:
                alerts.append({"type": "이벤트예고",
                    "msg": f"📅 [베트남펀드] D-3 이벤트\n{ev['내용']} ({ev['날짜']})\n포지션 점검하세요"})
            elif diff == 0:
                alerts.append({"type": "이벤트당일",
                    "msg": f"📅 [베트남펀드] 오늘 이벤트\n{ev['내용']}\n대시보드에서 결과 확인하세요"})
        except Exception:
            pass

    return alerts


def main():
    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()

    if not rest_api_key or not refresh_token:
        print("⚠️  KAKAO 환경변수 없음 — 알림 건너뜀")
        return

    print("카카오 토큰 갱신 중...")
    access_token = kakao_refresh_access_token(rest_api_key, refresh_token, client_secret or None)

    print("베트남 펀드 데이터 수집 중...")
    cfg = load_config()
    data = fetch_vietnam_data()
    print(f"VN-Index: {data['current']:.0f} | RSI: {data['rsi']}")

    alerts = check_vietnam_conditions(cfg, data)
    if not alerts:
        print("✅ 알림 조건 없음")
        return

    priority = {"손절": 0, "매수핵심": 1, "매도": 2, "이벤트당일": 3, "이벤트예고": 4, "매수참고": 5}
    alerts.sort(key=lambda a: priority.get(a["type"], 99))

    for alert in alerts:
        kakao_send(access_token, alert["msg"])
        print(f"  → {alert['type']}: {alert['msg'][:40]}...")


if __name__ == "__main__":
    main()
