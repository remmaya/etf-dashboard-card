# app.py
import streamlit as st
import yfinance as yf
import pandas as pd

from core import macd, rsi, slice_period, ETF_INFO

# ETF_INFO のキー（ティッカー）をそのまま使う：8銘柄全部が対象
TARGET_ETFS = list(ETF_INFO.keys())

st.set_page_config(page_title="ETF Dashboard", layout="centered")
st.title("ETF Dashboard（Price / MACD / RSI）")

# ----------------------------------------
# サイドバー（建値・期間・表示形式）
# ----------------------------------------
with st.sidebar:
    st.header("表示設定")

    period = st.selectbox("期間", ["All", "1Y", "3M", "1M"], index=1)
    currency = st.radio("建値", ["USD", "JPY"], index=1)
    view_mode = st.radio("表示内容", ["Price", "MACD+RSI"], index=0)

    st.markdown("---")
    if st.button("🔄 データ更新"):
        # キャッシュクリア & 再実行
        st.cache_data.clear()
        st.rerun()

# ----------------------------------------
# データ取得（cache付き）
# ----------------------------------------
@st.cache_data
def load_data():
    tickers = TARGET_ETFS + ["USDJPY=X"]
    df = yf.download(tickers, period="2y", auto_adjust=True)["Close"]
    return df

raw = load_data()

# USDJPY（為替）
fx = raw["USDJPY=X"].dropna()

# ----------------------------------------
# 各ETFを縦にそのまま表示（Expander なし）
# ----------------------------------------
for ticker in TARGET_ETFS:

    if ticker not in raw:
        continue

    usd_series = raw[ticker].dropna()

    # 円建て or ドル建て
    if currency == "JPY":
        fx_aligned = fx.reindex(usd_series.index).ffill()
        price = usd_series * fx_aligned
        cur = "JPY"
    else:
        price = usd_series
        cur = "USD"

    df = pd.DataFrame({"Close": price})
    df = slice_period(df, period)
    if df.empty:
        continue

    perf_pct = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
    label = ETF_INFO.get(ticker, ticker)

    # 見出し（タップ不要で常に表示）
    st.markdown(f"### {ticker}（{label}）｜ {perf_pct:+.2f}%  [{cur}]")

    if view_mode == "Price":
        import plotly.graph_objects as go

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Close"],
            mode="lines", name="Price"
        ))
        fig.update_layout(
            height=280,
            margin=dict(l=20, r=20, t=40, b=20),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    else:  # MACD+RSI
    import plotly.graph_objects as go

    macd_line, signal_line = macd(df["Close"])
    rsi_line = rsi(df["Close"])

    # -------------------------
    # MACD（MACD=青・Signal=赤）
    # -------------------------
    fig = go.Figure()

    # MACD（青）
    fig.add_trace(go.Scatter(
        x=df.index, y=macd_line,
        name="MACD",
        line=dict(color="blue", width=2)
    ))

    # Signal（赤）
    fig.add_trace(go.Scatter(
        x=df.index, y=signal_line,
        name="Signal",
        line=dict(color="red", width=2)
    ))

    fig.update_layout(
        height=260,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    # -------------------------
    # RSI（棒グラフ表示 + 基準線）
    # -------------------------
    fig2 = go.Figure()

    # RSI を棒グラフに
    fig2.add_trace(go.Bar(
        x=df.index,
        y=rsi_line,
        name="RSI",
        marker_color="rgba(100, 100, 255, 0.6)",  # 見やすい青系
    ))

    # 基準線 30 / 50 / 70
    for lvl in [30, 50, 70]:
        fig2.add_hline(
            y=lvl,
            line_dash="dot",
            line_color="gray"
        )

    fig2.update_layout(
        height=200,
        margin=dict(l=20, r=20, t=20, b=20),
        showlegend=False,
        yaxis=dict(range=[0, 100])  # RSI の上下レンジ固定
    )

    st.plotly_chart(fig2, use_container_width=True)

    # ETFごとに少し余白
    st.markdown("---")