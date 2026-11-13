# core.py
# 計算ロジック（Streamlit / Plotly に依存しない純粋な関数だけを置く）
import re
from datetime import timedelta
from zoneinfo import ZoneInfo

import pandas as pd

# ETF情報（キーはティッカー、値は日本語ラベル）
ETF_INFO = {
    "ICLN": "クリエネ",
    "IEMG": "新興国",
    "IXP": "コミュ",
    "IXJ": "ヘルスケア",
    "KXI": "生活必需品",
    "SDG": "SDGs",
    "IAU": "ゴールド",
    "IVV": "米国大型株",
}


# -----------------------------
# 株価取得（取りこぼし対策つき）
# -----------------------------
def _close_frame(df, tickers):
    """yf.download の結果から終値の DataFrame を取り出す"""
    if df is None or df.empty:
        return pd.DataFrame()
    close = df["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
    return close


def missing_tickers(df: pd.DataFrame, tickers) -> list:
    """列がない／全部NaNの銘柄を返す"""
    return [t for t in tickers if t not in df.columns or df[t].dropna().empty]


def download_close(tickers, period="2y", retries=2, wait_sec=1.5):
    """
    まとめて取得 → 取れなかった銘柄だけ1銘柄ずつ再取得する。
    戻り値: (終値DataFrame, それでも取れなかった銘柄のリスト)
    """
    import time

    import yfinance as yf

    tickers = list(tickers)

    try:
        close = _close_frame(
            yf.download(tickers, period=period, auto_adjust=True, progress=False),
            tickers,
        )
    except Exception:
        close = pd.DataFrame()

    for _ in range(retries):
        missing = missing_tickers(close, tickers)
        if not missing:
            break

        time.sleep(wait_sec)
        for t in missing:
            try:
                one = _close_frame(
                    yf.download(t, period=period, auto_adjust=True, progress=False),
                    [t],
                )
            except Exception:
                continue
            if t in one.columns and not one[t].dropna().empty:
                close = close.drop(columns=[t], errors="ignore").join(one[[t]], how="outer")

    close = close.sort_index()
    return close, missing_tickers(close, tickers)


def download_intraday(ticker, period="1mo", interval="30m") -> pd.Series:
    """30分足の終値（日本時間インデックス）。失敗時は空Series"""
    import yfinance as yf

    try:
        df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False)
    except Exception:
        return pd.Series(dtype=float)
    if df is None or df.empty:
        return pd.Series(dtype=float)

    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return to_jst_index(close.dropna())


# -----------------------------
# dポイント投資の更新日と前回基準日
# -----------------------------
# dポイント投資（テーマ）の更新時刻（日本時間）。この時刻を過ぎたら「今日の更新は済んだ」とみなす
DPOINT_UPDATE_HOUR = 17


def is_jp_business_day(d) -> bool:
    """日本の営業日か（土日・祝日・年末年始 12/31〜1/3 を除く）"""
    if d.weekday() >= 5:
        return False
    if (d.month, d.day) in [(12, 31), (1, 1), (1, 2), (1, 3)]:
        return False
    try:
        import jpholiday

        if jpholiday.is_holiday(d):
            return False
    except ImportError:
        pass
    return True


def last_dpoint_update_date(now_jst, update_hour: int = DPOINT_UPDATE_HOUR):
    """直近（すでに済んだ）dポイント更新の日付"""
    d = now_jst.date()
    if not (is_jp_business_day(d) and now_jst.hour >= update_hour):
        d -= timedelta(days=1)
        while not is_jp_business_day(d):
            d -= timedelta(days=1)
    return d


def default_base_date(etf_dates, now_jst, update_hour: int = DPOINT_UPDATE_HOUR):
    """
    前回基準日 = 直近のdポイント更新に使われたETF終値の日付。
    更新日 D には「D より前の最新の米国終値」が反映される
    （米国の X日終値は日本時間 X+1日の朝に確定するため）。
    """
    last_update = last_dpoint_update_date(now_jst, update_hour)
    dates = sorted({pd.Timestamp(x).date() for x in etf_dates})
    before = [x for x in dates if x < last_update]
    if before:
        return before[-1], last_update
    return (dates[-2] if len(dates) >= 2 else dates[-1]), last_update


def next_dpoint_update_date(last_update):
    """直近更新の次の更新日（＝次に反映される更新）"""
    d = last_update + timedelta(days=1)
    while not is_jp_business_day(d):
        d += timedelta(days=1)
    return d


# -----------------------------
# 仲値（TTM）の推定
# -----------------------------
TTM_HOUR, TTM_MINUTE = 9, 55  # 仲値はおおむね 9:55 時点の相場で決まる


def to_jst_index(series: pd.Series) -> pd.Series:
    """インデックスを日本時間に変換（タイムゾーンなしはUTCとみなす）"""
    s = series.copy()
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    s.index = idx.tz_convert("Asia/Tokyo")
    return s


def estimate_ttm(fx_intraday_jst: pd.Series, date):
    """
    指定日の 9:55 時点に最も近い（それ以前に始まった）足の終値を仲値の推定値とする。
    戻り値: (推定値, 使った足の時刻) / 見つからなければ (None, None)
    """
    if fx_intraday_jst is None or fx_intraday_jst.empty:
        return None, None

    s = fx_intraday_jst.dropna()
    day = s[s.index.date == date]
    cutoff = pd.Timestamp(date).tz_localize("Asia/Tokyo") + pd.Timedelta(hours=TTM_HOUR, minutes=TTM_MINUTE)
    day = day[day.index <= cutoff]
    if day.empty:
        return None, None
    return float(day.iloc[-1]), day.index[-1]


def is_ttm_fixed(now_jst, date) -> bool:
    """その日の仲値がもう決まっているか"""
    return now_jst.date() > date or (
        now_jst.date() == date and (now_jst.hour, now_jst.minute) >= (TTM_HOUR, TTM_MINUTE + 5)
    )


# -----------------------------
# 米国市場の状態
# -----------------------------
def us_market_status(last_etf_date, now_utc):
    """
    ETF価格が確定した終値か、取引中の途中経過かを判定する。
    戻り値: (状態, ニューヨーク現在時刻)  状態は "trading" / "close"
    """
    ny = now_utc.astimezone(ZoneInfo("America/New_York"))
    open_t = ny.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = ny.replace(hour=16, minute=0, second=0, microsecond=0)

    trading = (
        ny.weekday() < 5
        and open_t <= ny < close_t
        and last_etf_date == ny.date()
    )
    return ("trading" if trading else "close"), ny


def expected_last_close_date(now_utc, margin_min: int = 30):
    """
    今の時点で確定しているはずの、最新の米国終値の日付（土日のみ考慮。米国の祝日は考慮しない）。
    引け（16:00 NY）から margin_min 分たっていれば当日、そうでなければ前の平日。
    """
    ny = now_utc.astimezone(ZoneInfo("America/New_York"))
    d = ny.date()
    after_close = (ny.hour, ny.minute) >= (16, margin_min)
    if not (d.weekday() < 5 and after_close):
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d


def fetch_recent_close(tickers, days: str = "10d") -> pd.DataFrame:
    """1銘柄ずつ直近数日の終値を取り直す（まとめて取得で最新日が抜けたときの補完用）"""
    import yfinance as yf

    frames = {}
    for t in tickers:
        try:
            h = yf.Ticker(t).history(period=days, auto_adjust=True)
        except Exception:
            continue
        if h is None or h.empty or "Close" not in h:
            continue
        s = h["Close"].dropna()
        idx = pd.DatetimeIndex(s.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        s.index = idx.normalize()
        frames[t] = s
    return pd.DataFrame(frames)


def fill_latest_close(close: pd.DataFrame, tickers, expected_date):
    """
    expected_date の終値が欠けている銘柄だけ取り直して埋める。
    戻り値: (埋めたあとのDataFrame, それでも欠けている銘柄のリスト)
    """
    def lacking(df):
        out = []
        for t in tickers:
            if t not in df.columns:
                out.append(t)
                continue
            s = df[t].dropna()
            if s.empty or s.index[-1].date() < expected_date:
                out.append(t)
        return out

    need = lacking(close)
    if not need:
        return close, []

    recent = fetch_recent_close(need)
    if not recent.empty:
        # 既存の値はそのまま、欠けている日・銘柄だけを補う
        close = (close.combine_first(recent) if not close.empty else recent).sort_index()
    return close, lacking(close)


# -----------------------------
# AI分析用の指標まとめ
# -----------------------------
def summarize_indicators(full_close: pd.Series, period_close: pd.Series) -> dict:
    """期間騰落率・前日比・RSI・MACDの位置とクロス・25日線乖離率"""
    perf, day_perf = calc_perf(period_close)

    macd_line, signal_line = macd(full_close)
    diff = (macd_line - signal_line).dropna()
    macd_state, cross_days = None, None
    if not diff.empty:
        macd_state = "上" if diff.iloc[-1] > 0 else "下"
        sign = diff > 0
        changed = sign.ne(sign.shift())
        changed.iloc[0] = False
        if changed.any():
            last_cross = changed[changed].index[-1]
            cross_days = len(diff.loc[last_cross:]) - 1

    rsi_now = rsi(full_close).dropna()
    ma25 = full_close.rolling(25).mean().dropna()

    return {
        "perf": perf,
        "day_perf": day_perf,
        "rsi": float(rsi_now.iloc[-1]) if not rsi_now.empty else None,
        "macd_state": macd_state,
        "cross_days": cross_days,
        "ma25_gap": float(full_close.iloc[-1] / ma25.iloc[-1] * 100 - 100) if not ma25.empty else None,
    }


# -----------------------------
# dポイント運用ページのコピー結果を読み取る（Excel記録用）
# -----------------------------
# Excel Sheet1 の B〜L列（残高）・M〜W列（通算損益）の並び
RECORD_ORDER = [
    ("ICLN", "クリエネ"),
    ("IEMG", "新興国"),
    ("IXP", "コミュ"),
    ("KXI", "生活必需品"),
    ("IXJ", "ヘルスケア"),
    ("IAU", "ゴールド"),
    ("SDG", "SDGs"),
    ("N225", "日経"),
    ("N225INV", "日経Inv"),
    ("OMAKASE", "おまかせ"),
    ("IVV", "米国大型株"),
]

# ページ上の名前 → キー（上から順に判定。「日経インバース」は「日経」より先に）
_NAME_RULES = [
    ("インバース", "N225INV"),
    ("日経", "N225"),
    ("クリーン", "ICLN"),
    ("新興国", "IEMG"),
    ("コミュ", "IXP"),
    ("生活必需", "KXI"),
    ("ヘルスケア", "IXJ"),
    ("ゴールド", "IAU"),
    ("SDG", "SDG"),
    ("米国大型", "IVV"),
    ("おまかせ", "OMAKASE"),
]

_NUM_RE = re.compile(r"^([+\-−－↑↓]?)\s*([\d,，]+)\s*[PＰpｐ]?$")
_SIGN_ONLY = {"+", "-", "−", "－", "↑", "↓"}
# 「日経平均株価 ↑20,349P」のように名前と数字が同じ行に来た場合の分割用
_TAIL_NUM_RE = re.compile(r"^(.*[^\d,，+\-−－↑↓\s])\s*([+\-−－↑↓]?\s*[\d,，]+\s*[PＰpｐ]?)$")


def _split_lines(text):
    for raw_line in (text or "").replace("\t", "\n").splitlines():
        line = raw_line.strip()
        nums = []
        # 行末の数字を順にはがす（「名前 265,897P +8,399P」→ 名前 / 265,897P / +8,399P）
        while not _NUM_RE.match(line):
            m = _TAIL_NUM_RE.match(line)
            if not m:
                break
            nums.insert(0, m.group(2).strip())
            line = m.group(1).strip()
        if _NUM_RE.match(line) and nums:
            # 「265,897P +8,399P」のように数字だけが並んでいる行
            parts = re.findall(r"[+\-−－↑↓]?\s*[\d,，]+\s*[PＰpｐ]?", line)
            yield from (p.strip() for p in parts)
        else:
            yield line
        yield from nums


def _match_name(buffer: str):
    text = buffer.replace(" ", "").replace("　", "")
    if text == "テーマ":
        return "THEME_TOTAL"
    if text.endswith("これまでの合計損益"):
        return "TOTAL"
    for word, key in _NAME_RULES:
        if word in text:
            return key
    return None


def parse_dpoint_page(text: str) -> dict:
    """
    ページをコピーしたテキストから {キー: [数値, 数値, ...]} を作る。
    テーマ画面なら [残高, 前日比]、合計損益ページなら [通算損益]。
    名前が改行で分かれていても（例:「金（ゴールド」「）」）つなげて判定する。
    """
    result = {}
    buffer, current, pending_sign = [], None, ""

    for line in _split_lines(text):
        if not line or line in {"P", "Ｐ"}:
            continue

        if line in _SIGN_ONLY:
            pending_sign = line
            continue

        m = _NUM_RE.match(line)
        if m:
            if buffer:
                current = _match_name("".join(buffer))
                buffer = []
            sign = m.group(1) or pending_sign
            pending_sign = ""
            value = int(m.group(2).replace(",", "").replace("，", ""))
            if sign in {"-", "−", "－", "↓"}:
                value = -value
            if current is not None:
                result.setdefault(current, []).append(value)
            continue

        # 名前などの文字列行
        if current is not None and not buffer:
            current = None
        pending_sign = ""
        buffer.append(line)

    return result


def build_record_row(theme_text: str, total_text: str):
    """
    戻り値: (タブ区切りの22個の値, 明細リスト, チェック結果dict)
    明細: [{"key","label","残高","前日比","通算損益"}, ...]
    """
    theme = parse_dpoint_page(theme_text)
    total = parse_dpoint_page(total_text)

    details, balances, profits = [], [], []
    for key, label in RECORD_ORDER:
        t = theme.get(key, [])
        p = total.get(key, [])
        bal = t[0] if len(t) >= 1 else None
        day = t[1] if len(t) >= 2 else None
        prof = p[0] if len(p) >= 1 else None
        details.append({"key": key, "label": label, "残高": bal, "前日比": day, "通算損益": prof})
        balances.append(bal)
        profits.append(prof)

    values = ["" if v is None else str(v) for v in balances + profits]

    # 合計チェック（ページに出ている合計と、各テーマの合計が一致するか）
    check = {}
    theme_keys = [k for k, _ in RECORD_ORDER if k != "OMAKASE"]
    if "THEME_TOTAL" in total:
        parts = [total.get(k, [None])[0] for k in theme_keys]
        if None not in parts:
            check["テーマ合計"] = (sum(parts), total["THEME_TOTAL"][0])
    if "TOTAL" in total:
        parts = [total.get(k, [None])[0] for k in ["OMAKASE"]] + [total.get("THEME_TOTAL", [None])[0]]
        if None not in parts:
            check["合計損益"] = (sum(parts), total["TOTAL"][0])

    return "\t".join(values), details, check


# -----------------------------
# 記録シート（日付＋残高11＋損益11）の読み込みと集計
# -----------------------------
RECORD_LABELS = [label for _, label in RECORD_ORDER]


def parse_record(df: pd.DataFrame):
    """
    記録シートのDataFrame（1行目が見出し）→ (残高DataFrame, 通算損益DataFrame)
    列名はテーマの日本語ラベル、インデックスは日付。数字のカンマや空欄にも対応。
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col].astype(str).str.strip(), errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    df = df[~df.index.duplicated(keep="last")]

    def pick(prefix):
        out = pd.DataFrame(index=df.index)
        for label in RECORD_LABELS:
            col = f"{prefix}:{label}"
            if col in df.columns:
                s = df[col].astype(str).str.replace(",", "").str.replace("，", "").str.strip()
                out[label] = pd.to_numeric(s, errors="coerce")
            else:
                out[label] = float("nan")
        return out

    bal, pl = pick("残高"), pick("損益")
    # 損益がすべて空の行（未入力の日付だけの行など）は除く
    keep = pl.notna().any(axis=1)
    return bal[keep].fillna(0), pl[keep].ffill().fillna(0)


def period_profit(pl_total: pd.Series, freq: str) -> pd.Series:
    """
    期間ごとの損益（= 期末の通算損益 − 前期末の通算損益）
    freq: "M"（月）/ "Y"（年）
    """
    key = pl_total.index.to_period(freq)
    last = pl_total.groupby(key).last()
    first_prev = pl_total.iloc[0]  # 最初の期は記録開始時点からの増減
    return last.diff().fillna(last.iloc[0] - first_prev)


def principal_flows(bal: pd.DataFrame, pl: pd.DataFrame, min_abs: int = 100) -> pd.DataFrame:
    """
    追加・引出の履歴。
    その日の「残高の増減 − 損益の増減」＝ 入れた（+）／出した（−）pt。
    min_abs 未満の小さな差（推定残高の誤差など）は除く。
    戻り値: 入出金のあった日だけのDataFrame（列＝テーマ）
    """
    flow = (bal.diff() - pl.diff()).iloc[1:].round(0)
    flow = flow.where(flow.abs() >= min_abs, 0)
    return flow[flow.ne(0).any(axis=1)]


def daily_change(bal: pd.DataFrame, pl: pd.DataFrame):
    """更新日ごとの前日比（pt と %）。% は前回残高に対する割合"""
    d_pt = pl.diff()
    prev_bal = bal.shift(1)
    d_pct = (d_pt / prev_bal.where(prev_bal > 0)) * 100
    # 全テーマ変動なしの日（祝日に前日と同じ値を記録した日など）は除く
    moved = d_pt.fillna(0).ne(0).any(axis=1)
    moved.iloc[0] = False
    return d_pt[moved], d_pct[moved]


# -----------------------------
# MACD（EMA方式）
# -----------------------------
def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


# -----------------------------
# RSI（rolling方式：従来ロジックのまま）
# -----------------------------
def rsi(series: pd.Series, period: int = 14):
    delta = series.diff()
    up = delta.clip(lower=0).rolling(period).mean()
    down = (-delta.clip(upper=0)).rolling(period).mean()
    rs = up / down
    return 100 - (100 / (1 + rs))


# -----------------------------
# 期間切替（All / 1Y / 3M / 1M）
# -----------------------------
PERIOD_DAYS = {"1Y": 365, "3M": 90, "1M": 30}


def slice_period(df: pd.DataFrame, period_key: str) -> pd.DataFrame:
    """period_key: 'All', '1Y', '3M', '1M'"""
    days = PERIOD_DAYS.get(period_key)
    if days is None or df.empty:
        return df

    start = df.index.max() - timedelta(days=days)
    return df[df.index >= start]


# -----------------------------
# 騰落率
# -----------------------------
def calc_perf(series: pd.Series):
    """(期間騰落率%, 前日比%) を返す。データ不足なら (None, None)"""
    series = series.dropna()
    if len(series) < 2:
        return None, None

    period_perf = (series.iloc[-1] / series.iloc[0] - 1) * 100
    day_perf = (series.iloc[-1] / series.iloc[-2] - 1) * 100
    return period_perf, day_perf


def calc_indicators(full_close: pd.Series, display_index) -> pd.DataFrame:
    """
    MACD / Signal / RSI を「全期間のデータ」で計算してから、表示期間だけ切り出す。
    （表示期間だけで計算すると、1Mなどの短期表示で値が不正確になるため）
    """
    macd_line, signal_line = macd(full_close)
    rsi_line = rsi(full_close)

    df_ind = pd.DataFrame(
        {
            "MACD": macd_line,
            "Signal": signal_line,
            "RSI": rsi_line,
        }
    )
    return df_ind.reindex(display_index)
