#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KR Premarket Terminal — 데이터 수집기 (approach a: 무료 라이브러리)

snapshot.json 을 생성합니다. 프론트엔드(index.html)가 이 파일을 읽습니다.
원칙: 데이터를 가져오지 못하면 가짜로 채우지 않고 null 로 둡니다 → 화면에 "데이터 없음".

수집 항목: 지수/차트(코스피·코스닥), 수급(외인·기관·개인), 전일 특징주,
           업종 히트맵, 글로벌(미국지수·SOX·금리·달러·WTI·환율·EWY), 뉴스.
화면 전용(수집 안 함): 오늘 일정·야간선물 → index.html 의 Investing.com 위젯.
실적/컨센서스 → config/earnings.json 직접 입력(선택).

사용법:
    python collect.py
    python collect.py --date 20260602
    python collect.py --out snapshot.json

설치: pip install -r requirements.txt
"""
import os, sys, json, re, html, argparse
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

def log(tag, msg): print(f"[{tag}] {msg}", file=sys.stderr)
def ok(name): log("OK", name)
def fail(name, e): log("FAIL", f"{name}: {e}")

def ts_ms(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)

# --------------------------------------------------------------------------
def recent_business_days(n, base=None):
    """base(KST date) 이하의 최근 평일 n개(최신순). KRX 의존 없이 주말만 건너뜀.
    (공휴일은 야후가 자동으로 직전 거래일 데이터를 주므로 별도 처리 불필요)"""
    if base is None:
        base = (datetime.now(KST) - timedelta(days=1)).date()
    out, cur = [], base
    while len(out) < n:
        if cur.weekday() < 5:  # 0=월 ... 4=금
            out.append(cur.strftime("%Y%m%d"))
        cur -= timedelta(days=1)
    return out

# 지수 + 차트 ----------------------------------------------------------------
INDEX_CODES = {"코스피": "1001", "코스닥": "2001"}

def collect_indices_and_charts(last_day):
    """코스피/코스닥 지수 last/change + 10Y 일봉 차트.
    2025-12 KRX 로그인 전환으로 pykrx 무인 수집이 막혀, 지수/차트는 Yahoo(^KS11/^KQ11)로 수집."""
    import yfinance as yf
    indices, charts = {}, {}
    spec = {"코스피": ("^KS11", "kospi"), "코스닥": ("^KQ11", "kosdaq")}
    for name, (tk, key) in spec.items():
        try:
            df = yf.Ticker(tk).history(period="10y", auto_adjust=False).dropna(subset=["Close"])
            if df.empty: raise ValueError("빈 데이터")
            closes = df["Close"]
            lastv = float(closes.iloc[-1]); prev = float(closes.iloc[-2]) if len(closes) > 1 else lastv
            chg = (lastv / prev - 1) * 100 if prev else None
            indices[key] = {"name": name, "last": round(lastv, 2),
                            "change_pct": round(chg, 2) if chg is not None else None}
            ohlcv = []
            for idx, r in df.iterrows():
                v = r.get("Volume", 0)
                try: v = int(v) if v == v else 0   # NaN 방지
                except Exception: v = 0
                ohlcv.append([ts_ms(idx), round(float(r["Open"]), 2), round(float(r["High"]), 2),
                              round(float(r["Low"]), 2), round(float(r["Close"]), 2), v])
            charts[name] = {"name": f"{name} 지수", "ohlcv": ohlcv}
            ok(f"지수/차트 {name} ({len(ohlcv)}봉)")
        except Exception as e:
            indices[key] = None; fail(f"지수 {name}", e)
    return indices, charts

# 글로벌 --------------------------------------------------------------------
GLOBAL_TICKERS = {
    "sp500":  ("^GSPC",    "S&P500",     None),
    "nasdaq": ("^IXIC",    "나스닥",      None),
    "sox":    ("^SOX",     "SOX 반도체",  None),
    "us10y":  ("^TNX",     "미10년물",    "%"),
    "dxy":    ("DX-Y.NYB", "달러인덱스",  None),
    "wti":    ("CL=F",     "WTI",        None),
    "usdkrw": ("KRW=X",    "원/달러",     None),
    "ewy":    ("EWY",      "EWY 한국ETF", None),
}

def collect_global():
    import yfinance as yf
    g = {}
    for key, (tk, name, unit) in GLOBAL_TICKERS.items():
        try:
            closes = yf.Ticker(tk).history(period="7d", auto_adjust=False)["Close"].dropna()
            if len(closes) < 2: raise ValueError("종가 부족")
            lastv = float(closes.iloc[-1]); prev = float(closes.iloc[-2])
            if key == "us10y" and lastv > 20: lastv /= 10; prev /= 10
            chg = (lastv / prev - 1) * 100 if prev else None
            entry = {"name": name, "last": round(lastv, 2), "change_pct": round(chg, 2) if chg is not None else None}
            if unit: entry["unit"] = unit
            g[key] = entry; ok(f"글로벌 {name}")
        except Exception as e:
            g[key] = None; fail(f"글로벌 {name}", e)
    g["vkospi"] = None   # 무료 안정 소스 없음 → 데이터 없음
    return g

# 수급 (외인/기관/개인 순매수, 억원) ----------------------------------------
def _net_by_investor(day, market):
    from pykrx import stock
    net = stock.get_market_trading_value_by_investor(day, day, market)["순매수"]
    def pick(label): return float(net[label]) / 1e8 if label in net.index else None
    foreign, etc_f = pick("외국인"), pick("기타외국인")
    if foreign is not None and etc_f is not None: foreign += etc_f
    inst, indi = pick("기관합계"), pick("개인")
    return {"foreign": round(foreign) if foreign is not None else None,
            "institution": round(inst) if inst is not None else None,
            "individual": round(indi) if indi is not None else None}

def collect_flows(last_day):
    flows = {}
    for mkt_name, mkt in (("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")):
        try:
            flows[mkt_name] = _net_by_investor(last_day, mkt); ok(f"수급 {mkt}")
        except Exception as e:
            flows[mkt_name] = None; fail(f"수급 {mkt}", e)
    return flows

# 전일 특징주 ----------------------------------------------------------------
def collect_movers(last_day, prev_day, min_value=1_000_000_000):
    from pykrx import stock
    import pandas as pd
    try:
        t = pd.concat([stock.get_market_ohlcv(last_day, market=m) for m in ("KOSPI", "KOSDAQ")])
        p = pd.concat([stock.get_market_ohlcv(prev_day, market=m) for m in ("KOSPI", "KOSDAQ")])
        t = t[(t["거래대금"] >= min_value) & (t["종가"] > 0)].copy()
        t["prev_vol"] = p["거래량"].reindex(t.index)
        t["vol_ratio"] = t.apply(lambda r: (r["거래량"] / r["prev_vol"]) if r["prev_vol"] and r["prev_vol"] > 0 else None, axis=1)
        cache = {}
        def nm(code):
            if code not in cache:
                try: cache[code] = stock.get_market_ticker_name(code)
                except Exception: cache[code] = code
            return cache[code]
        def rows(df, vol=False):
            out = []
            for code, r in df.iterrows():
                it = {"ticker": code, "name": nm(code), "last": int(r["종가"]), "change_pct": round(float(r["등락률"]), 2)}
                if vol: it["vol_ratio"] = round(float(r["vol_ratio"]), 1) if r["vol_ratio"] else None
                else: it["volume"] = int(r["거래량"])
                out.append(it)
            return out
        ok(f"특징주 (대상 {len(t)}종목)")
        return {"gainers": rows(t.sort_values("등락률", ascending=False).head(8)),
                "losers":  rows(t.sort_values("등락률", ascending=True).head(8)),
                "volume":  rows(t[t["vol_ratio"].notna()].sort_values("vol_ratio", ascending=False).head(8), vol=True)}
    except Exception as e:
        fail("특징주", e); return None

# 업종 히트맵 (실제 KRX KOSPI 업종지수) --------------------------------------
SECTOR_CODES = {"전기전자": "1013", "화학": "1008", "의약품": "1009", "운수장비": "1015",
                "금융업": "1021", "철강금속": "1011", "서비스업": "1026", "건설업": "1018", "기계": "1012"}

def collect_sectors(last_day):
    from pykrx import stock
    frm = (datetime.strptime(last_day, "%Y%m%d") - timedelta(days=10)).strftime("%Y%m%d")
    out = []
    for name, code in SECTOR_CODES.items():
        try:
            c = stock.get_index_ohlcv(frm, last_day, code).dropna()["종가"]
            out.append({"name": name, "change_pct": round((float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100, 2)})
        except Exception as e:
            out.append({"name": name, "change_pct": None}); fail(f"업종 {name}", e)
    ok("업종 히트맵"); return out or None

# 뉴스 (RSS) ----------------------------------------------------------------
DEFAULT_FEEDS = [
    ("연합뉴스 경제", "https://www.yna.co.kr/rss/economy.xml"),
    ("매일경제 증권", "https://www.mk.co.kr/rss/50200011/"),
    ("한국경제 증권", "https://www.hankyung.com/feed/finance"),
]
def _clean(t): return html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()

def collect_news(limit=8):
    import feedparser
    feeds = DEFAULT_FEEDS
    cfg = os.path.join("config", "news_feeds.json")
    if os.path.exists(cfg):
        try: feeds = [(f["source"], f["url"]) for f in json.load(open(cfg, encoding="utf-8"))]
        except Exception as e: fail("news_feeds.json", e)
    items = []
    for src, url in feeds:
        try:
            for e in feedparser.parse(url).entries[:limit]:
                pub = datetime(*e.published_parsed[:6]).strftime("%m-%d %H:%M") if getattr(e, "published_parsed", None) else ""
                items.append({"title": _clean(e.get("title")), "summary": _clean(e.get("summary"))[:120],
                              "source": src, "url": e.get("link"), "published_at": pub, "_s": e.get("published_parsed")})
        except Exception as ex:
            fail(f"뉴스 {src}", ex)
    if not items: return None
    items.sort(key=lambda x: x.get("_s") or (), reverse=True)
    for it in items: it.pop("_s", None)
    ok(f"뉴스 {len(items)}건"); return items[:limit]

# 실적 (수동 큐레이션 — 선택) -----------------------------------------------
def load_earnings():
    path = os.path.join("config", "earnings.json")
    if os.path.exists(path):
        try:
            data = json.load(open(path, encoding="utf-8")); ok(f"실적 (수동 {len(data)}건)"); return data, "manual"
        except Exception as e:
            fail("실적", e)
    log("SKIP", f"실적: {path} 없음 → 데이터 없음"); return None, "없음"

# main ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="기준 거래일 YYYYMMDD (기본: 최근 거래일)")
    ap.add_argument("--out", default="snapshot.json")
    args = ap.parse_args()

    try:
        if args.date:
            last = args.date
            prev = recent_business_days(1, base=datetime.strptime(last, "%Y%m%d").date() - timedelta(days=1))[0]
        else:
            last, prev = recent_business_days(2)
        log("INFO", f"기준 거래일={last}, 전거래일={prev}")
    except Exception as e:
        fail("거래일 계산", e); last = prev = None

    sources = {}
    snap = {"meta": {"generated_at": datetime.now(KST).isoformat(timespec="seconds"),
                     "demo": False, "trade_date": last, "sources": sources}}

    if last:
        snap["indices"], snap["charts"] = collect_indices_and_charts(last)
        snap["flows"] = collect_flows(last)
        snap["movers"] = collect_movers(last, prev)
        snap["sectors"] = collect_sectors(last)
    else:
        snap.update({k: None for k in ("indices", "charts", "flows", "movers", "sectors")})

    snap["global"] = collect_global()
    snap["news"] = collect_news()
    snap["earnings"], src_earn = load_earnings()

    def st(v, fb="수집 실패"):
        return "수집됨" if (v is not None and (not isinstance(v, list) or len(v) > 0)) else fb
    sources.update({
        "indices": st(snap.get("indices") and snap["indices"].get("kospi")),
        "flows": st(snap.get("flows") and snap["flows"].get("kospi")),
        "movers": st(snap.get("movers")),
        "news": st(snap.get("news")),
        "earnings": src_earn,
        "charts": st(snap.get("charts")),
    })

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    log("DONE", f"{args.out} 생성 완료")

if __name__ == "__main__":
    main()
