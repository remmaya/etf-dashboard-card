# core.py
import pandas as pd
from datetime import timedelta

# ETF情報（キーはティッカー、値は日本語ラベル）
ETF_INFO = {
    "ICLN": "クリーエネ",
    "IEMG": "新興国",
    "IXP": "コミュ",
    "IXJ": "ヘルスケア",
    "KXI": "生活必需品",
    "SDG": "SDGs",
    "IAU": "ゴールド",
    "IVV": "米国大型株",
}

# -----------------------------
# MACD（現行ロジックそのまま：EMA方式）
# -----------------------------
def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


# -----------------------------
# RSI（現行ロジックそのまま：rolling方式）
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
def slice_period(df: pd.DataFrame, period_key: str) -> pd.DataFrame:
    """period_key: 'All', '1Y', '3M', '1M'"""
    if period_key == "All":
        return df

    end = df.index.max()

    if period_key == "1Y":
        start = end - timedelta(days=365)
    elif period_key == "3M":
        start = end - timedelta(days=90)
    elif period_key == "1M":
        start = end - timedelta(days=30)
    else:
        # 想定外の入力はそのまま返す
        return df

    return df[df.index >= start]