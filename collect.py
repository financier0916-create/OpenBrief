#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KR Premarket Terminal - 데이터 수집기
지수/차트/미국시장: Yahoo(yfinance). 특징주(시총 포함)/업종: KRX OpenAPI(키 필요).
수급: KRX OpenAPI 미제공. 뉴스: RSS(중요도 랭킹). 실적: config/earnings.json(선택).
"""
import os, sys, json, re, html, argparse
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

def log(tag, msg): print(f"[{tag}] {msg}", file=sys.stderr)
def ok(name): log("OK", name)
def fail(name, e): log("FAIL", f"{name}: {e}")

def ts_ms(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)

def recent_business_days(n, base=None):
    if base is None:
        base = (datetime.now(KST) - timedelta(days=1)).date()
    out, cur = [], base
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.strftime("%Y%m%d"))
        cur -= timedelta(days=1)
    return out

def collect_indices_and_charts():
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
                try: v = int(v) if v == v else 0
                except Exception: v = 0
                ohlcv.append([ts_ms(idx), round(float(r["Open"]), 2), round(float(r["High"]), 2),
                              round(float(r["Low"]), 2), round(float(r["Close"]), 2), v])
            charts[name] = {"name": f"{name} 지수", "ohlcv": ohlcv}
            ok(f"지수/차트 {name} ({len(ohlcv)}봉)")
        except Exception as e:
            indices[key] = None; fail(f"지수 {name}", e)
    return indices, charts

GLOBAL_TICKERS = {
    "sp500":  ("^GSPC",    "S&P500",     None),
    "nasdaq": ("^IXIC",    "나스닥",      None),
    "dow":    ("^DJI",     "다우",        None),
    "sox":    ("^SOX",     "SOX 반도체",  None),
    "vix":    ("^VIX",     "VIX 공포지수", None),
    "us10y":  ("^TNX",     "미10년물",    "%"),
    "dxy":    ("DX-Y.NYB", "달러인덱스",  None),
    "wti":    ("CL=F",     "WTI",        None),
    "gold":   ("GC=F",     "금",          None),
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
    return g

KRX_BASE = "http://data-dbg.krx.co.kr/svc/apis"
def _krx(cat, api, basDd, key):
    import requests
    r = requests.get(f"{KRX_BASE}/{cat}/{api}", headers={"AUTH_KEY": key},
                     params={"basDd": basDd}, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j.get("OutBlock_1") or next((v for v in j.values() if isinstance(v, list)), [])

def _f(x):
    try: return float(str(x).replace(",", "").strip())
    except Exception: return None

def collect_movers(last_day, prev_day, key, min_value=1_000_000_000):
    if not key:
        fail("특징주", "KRX_API_KEY 없음"); return None
    try:
        today, prev = {}, {}
        for api, mkt in (("stk_bydd_trd", "kospi"), ("ksq_bydd_trd", "kosdaq")):
            for row in _krx("sto", api, last_day, key):
                row["_mkt"] = mkt; today[row.get("ISU_CD")] = row
            for row in _krx("sto", api, prev_day, key): prev[row.get("ISU_CD")] = row
        recs = []
        for code, row in today.items():
            val = _f(row.get("ACC_TRDVAL")); clo = _f(row.get("TDD_CLSPRC"))
            if val is None or val < min_value or not clo: continue
            vol = _f(row.get("ACC_TRDVOL")); pv = _f((prev.get(code) or {}).get("ACC_TRDVOL"))
            recs.append({"ticker": code, "name": row.get("ISU_NM"), "last": int(clo),
                         "change_pct": _f(row.get("FLUC_RT")), "volume": int(vol or 0),
                         "vol_ratio": (vol / pv) if (vol and pv and pv > 0) else None})
        if not recs: raise ValueError("빈 데이터")
        g = sorted(recs, key=lambda r: r["change_pct"] if r["change_pct"] is not None else -1e9, reverse=True)[:8]
        l = sorted(recs, key=lambda r: r["change_pct"] if r["change_pct"] is not None else 1e9)[:8]
        def clean(rows):
            return [{"ticker": r["ticker"], "name": r["name"], "last": r["last"],
                     "change_pct": round(r["change_pct"], 2) if r["change_pct"] is not None else None,
                     "volume": r["volume"]} for r in rows]
        def mcap_top(rows_pool, topn=10):
            rows = [r for r in rows_pool if _f(r.get("MKTCAP"))]
            rows.sort(key=lambda r: _f(r.get("MKTCAP")), reverse=True)
            out = []
            for r in rows[:topn]:
                fr = _f(r.get("FLUC_RT"))
                out.append({"ticker": r.get("ISU_CD"), "name": r.get("ISU_NM"),
                            "last": int(_f(r.get("TDD_CLSPRC")) or 0),
                            "change_pct": round(fr, 2) if fr is not None else None,
                            "mktcap": _f(r.get("MKTCAP"))})
            return out
        kospi_rows = [r for r in today.values() if r.get("_mkt") == "kospi"]
        kosdaq_rows = [r for r in today.values() if r.get("_mkt") == "kosdaq"]
        ok(f"특징주 (대상 {len(recs)}종목)")
        return {"gainers": clean(g), "losers": clean(l),
                "mcap_kospi": mcap_top(kospi_rows), "mcap_kosdaq": mcap_top(kosdaq_rows),
                "mcap_all": mcap_top(list(today.values()), 20)}
    except Exception as e:
        fail("특징주", e); return None

SECTORS = ["전기전자", "화학", "의약품", "운수장비", "금융업", "철강금속", "서비스업", "건설업", "기계"]
def collect_sectors(last_day, key):
    if not key:
        fail("업종", "KRX_API_KEY 없음"); return None
    try:
        rows = _krx("idx", "kospi_dd_trd", last_day, key)
        bynm = {(r.get("IDX_NM") or "").strip(): _f(r.get("FLUC_RT")) for r in rows}
        out = []
        for name in SECTORS:
            chg = next((v for k, v in bynm.items() if name in k), None)
            out.append({"name": name, "change_pct": round(chg, 2) if chg is not None else None})
        ok("업종 히트맵"); return out
    except Exception as e:
        fail("업종", e); return None

DEFAULT_FEEDS = [
    ("연합뉴스 경제", "https://www.yna.co.kr/rss/economy.xml"),
    ("연합뉴스 증권", "https://www.yna.co.kr/rss/market.xml"),
    ("매일경제 증권", "https://www.mk.co.kr/rss/50200011/"),
    ("매일경제 경제", "https://www.mk.co.kr/rss/30100041/"),
    ("한국경제 증권", "https://www.hankyung.com/feed/finance"),
    ("한국경제 경제", "https://www.hankyung.com/feed/economy"),
]
NEWS_KEYWORDS = {
    5: ["금리", "기준금리", "FOMC", "연준", "Fed", "환율", "원/달러", "원달러", "고용", "물가", "CPI", "GDP", "한국은행", "긴축", "인하"],
    4: ["코스피", "코스닥", "반도체", "삼성전자", "SK하이닉스", "외국인", "수급", "실적", "어닝", "관세", "수출"],
    3: ["엔비디아", "AI", "HBM", "테슬라", "애플", "유가", "국채", "달러", "증시", "사상최고", "급락", "급등", "상한가", "하한가"],
    2: ["배당", "자사주", "공매도", "IPO", "상장", "인수", "합병", "M&A", "투자", "전망", "목표주가"],
}
NEWS_NOISE = ["인사", "부고", "동정", "포토", "날씨", "운세", "사설", "칼럼", "기고", "당첨", "이벤트", "행사", "예고", "방송"]

def _clean(t): return html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()

def _news_score(title, summary):
    text = (title or "") + " " + (summary or "")
    score = 0
    for w, words in NEWS_KEYWORDS.items():
        for kw in words:
            if kw in text: score += w
    for kw in NEWS_NOISE:
        if kw in title: score -= 6
    if "속보" in title or "[속보]" in title: score += 2
    return score

def collect_news(limit=10):
    import feedparser
    feeds = DEFAULT_FEEDS
    cfg = os.path.join("config", "news_feeds.json")
    if os.path.exists(cfg):
        try: feeds = [(f["source"], f["url"]) for f in json.load(open(cfg, encoding="utf-8"))]
        except Exception as e: fail("news_feeds.json", e)
    items, seen = [], set()
    for src, url in feeds:
        try:
            for e in feedparser.parse(url).entries[:25]:
                title = _clean(e.get("title")); summary = _clean(e.get("summary"))
                if not title: continue
                k = re.sub(r"[^가-힣A-Za-z0-9]", "", title)[:24]
                if k in seen: continue
                seen.add(k)
                pub = datetime(*e.published_parsed[:6]).strftime("%m-%d %H:%M") if getattr(e, "published_parsed", None) else ""
                items.append({"title": title, "summary": summary[:120], "source": src,
                              "url": e.get("link"), "published_at": pub,
                              "_score": _news_score(title, summary), "_s": e.get("published_parsed")})
        except Exception as ex:
            fail(f"뉴스 {src}", ex)
    if not items: return None
    items.sort(key=lambda x: (x["_score"], x.get("_s") or ()), reverse=True)
    top = items[:limit]
    top.sort(key=lambda x: x.get("_s") or (), reverse=True)
    for it in top: it.pop("_s", None); it.pop("_score", None)
    ok(f"뉴스 {len(top)}건 (후보 {len(items)})"); return top

def load_earnings():
    path = os.path.join("config", "earnings.json")
    if os.path.exists(path):
        try:
            data = json.load(open(path, encoding="utf-8")); ok(f"실적 (수동 {len(data)}건)"); return data, "manual"
        except Exception as e:
            fail("실적", e)
    log("SKIP", f"실적: {path} 없음 → 데이터 없음"); return None, "없음"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--out", default="snapshot.json")
    args = ap.parse_args()
    key = os.environ.get("KRX_API_KEY")

    if args.date:
        last = args.date
        prev = recent_business_days(1, base=datetime.strptime(last, "%Y%m%d").date() - timedelta(days=1))[0]
    else:
        last, prev = recent_business_days(2)
    log("INFO", f"기준 거래일={last}, 전거래일={prev}, KRX키={'있음' if key else '없음'}")

    sources = {}
    snap = {"meta": {"generated_at": datetime.now(KST).isoformat(timespec="seconds"),
                     "demo": False, "trade_date": last, "sources": sources}}

    snap["indices"], snap["charts"] = collect_indices_and_charts()
    snap["global"] = collect_global()
    snap["movers"] = collect_movers(last, prev, key)
    snap["sectors"] = collect_sectors(last, key)
    snap["flows"] = None
    snap["news"] = collect_news()
    snap["earnings"], src_earn = load_earnings()

    def st(v, fb="수집 실패"):
        return "수집됨" if (v is not None and (not isinstance(v, list) or len(v) > 0)) else fb
    sources.update({
        "indices": st(snap.get("indices") and snap["indices"].get("kospi")),
        "flows": "미제공",
        "movers": st(snap.get("movers"), "수집 실패/키 확인"),
        "news": st(snap.get("news")),
        "earnings": src_earn,
        "charts": st(snap.get("charts")),
    })

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    log("DONE", f"{args.out} 생성 완료")

if __name__ == "__main__":
    main()
