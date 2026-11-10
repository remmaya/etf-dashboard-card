# core.py
# 計算ロジック（Streamlit / Plotly に依存しない純粋な関数だけを置く）
from datetime import timedelta

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
