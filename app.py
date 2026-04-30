# app.py
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

from core import macd, rsi, slice_period, ETF_INFO

TARGET_ETFS = list(ETF_INFO.keys())
DISPLAY_ITEMS = TARGET_ETFS + ["USDJPY=X"]

DISPLAY_LABELS = {
    **ETF_INFO,
    "USDJPY=X": "ドル円",
}

st.set_page_config(page_title="ETF Dashboard", layout="wide")
st.title("ETF Dashboard")

with st.sidebar:
    st.header("表示設定")

    period = st.selectbox("期間", ["All", "1Y", "3M", "1M"], index=3)
    currency = st.radio("建値", ["USD", "JPY"], index=1)

    view_mode = st.radio(
        "表示内容",
        ["3×3 Price", "3×3 MACD+RSI", "Card Detail"],
        index=0,
    )

    st.markdown("---")
    if st.button("🔄 データ更新"):
        st.cache_data.clear()
        st.rerun()


@st.cache_data(ttl=60 * 60 * 6)
def load_data():
    tickers = DISPLAY_ITEMS
    df = yf.download(tickers, period="2y", auto_adjust=True)["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame()
    return df


def get_price_series(ticker, raw, fx, currency):
    if ticker not in raw.columns:
        return None, None

    series = raw[ticker].dropna()
    if series.empty:
        return None, None

    if ticker == "USDJPY=X":
        return series, "JPY"

    if currency == "JPY" and not fx.empty:
        fx_aligned = fx.reindex(series.index).ffill()
        return series * fx_aligned, "JPY"

    return series, "USD"


def calc_perf(series):
    if len(series) < 2:
        return None, None

    period_perf = (series.iloc[-1] / series.iloc[0] - 1) * 100
    day_perf = (series.iloc[-1] / series.iloc[-2] - 1) * 100
    return period_perf, day_perf


def make_price_chart(df, ticker, label, cur):
    perf, day_perf = calc_perf(df["Close"])

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["Close"],
            mode="lines",
            name=ticker,
        )
    )

    title = f"{ticker}（{label}）"
    if perf is not None:
        title += f"｜{perf:+.1f}%"

    fig.update_layout(
        title=title,
        height=260,
        margin=dict(l=10, r=10, t=45, b=10),
        showlegend=False,
        yaxis_title=cur,
    )
    return fig


def make_macd_rsi_chart(df, ticker, label):
    macd_line, signal_line = macd(df["Close"])
    rsi_line = rsi(df["Close"])

    macd_df = pd.DataFrame(
        {"MACD": macd_line, "Signal": signal_line, "RSI": rsi_line}
    ).loc[df.index]

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=macd_df.index,
            y=macd_df["MACD"],
            name="MACD",
            yaxis="y1",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=macd_df.index,
            y=macd_df["Signal"],
            name="Signal",
            yaxis="y1",
        )
    )

    fig.add_trace(
        go.Bar(
            x=macd_df.index,
            y=macd_df["RSI"],
            name="RSI",
            yaxis="y2",
            opacity=0.35,
        )
    )

    latest_rsi = macd_df["RSI"].dropna().iloc[-1] if not macd_df["RSI"].dropna().empty else None
    title = f"{ticker}（{label}）"
    if latest_rsi is not None:
        title += f"｜RSI {latest_rsi:.1f}"

    fig.update_layout(
        title=title,
        height=280,
        margin=dict(l=10, r=10, t=45, b=10),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        yaxis=dict(title="MACD"),
        yaxis2=dict(
            title="RSI",
            overlaying="y",
            side="right",
            range=[0, 100],
        ),
    )

    fig.add_hline(y=30, line_dash="dot", line_color="gray", yref="y2")
    fig.add_hline(y=70, line_dash="dot", line_color="gray", yref="y2")

    return fig


raw = load_data()
fx = raw["USDJPY=X"].dropna() if "USDJPY=X" in raw.columns else pd.Series(dtype=float)

items = []

for ticker in DISPLAY_ITEMS:
    price, cur = get_price_series(ticker, raw, fx, currency)
    if price is None:
        continue

    df = pd.DataFrame({"Close": price})
    df = slice_period(df, period)

    if df.empty:
        continue

    items.append((ticker, DISPLAY_LABELS.get(ticker, ticker), df, cur))


if view_mode == "3×3 Price":
    cols = st.columns(3)

    for i, (ticker, label, df, cur) in enumerate(items):
        with cols[i % 3]:
            fig = make_price_chart(df, ticker, label, cur)
            st.plotly_chart(fig, use_container_width=True)

elif view_mode == "3×3 MACD+RSI":
    cols = st.columns(3)

    for i, (ticker, label, df, cur) in enumerate(items):
        with cols[i % 3]:
            fig = make_macd_rsi_chart(df, ticker, label)
            st.plotly_chart(fig, use_container_width=True)

else:
    selected = st.selectbox(
        "銘柄",
        [ticker for ticker, _, _, _ in items],
        format_func=lambda x: f"{x}（{DISPLAY_LABELS.get(x, x)}）",
    )

    for ticker, label, df, cur in items:
        if ticker != selected:
            continue

        perf, day_perf = calc_perf(df["Close"])
        latest = df["Close"].iloc[-1]

        st.subheader(f"{ticker}（{label}）")

        c1, c2, c3 = st.columns(3)
        c1.metric("現在値", f"{latest:,.2f} {cur}")
        c2.metric("期間騰落率", f"{perf:+.2f}%" if perf is not None else "-")
        c3.metric("前日比", f"{day_perf:+.2f}%" if day_perf is not None else "-")

        st.plotly_chart(
            make_price_chart(df, ticker, label, cur),
            use_container_width=True,
        )

        st.plotly_chart(
            make_macd_rsi_chart(df, ticker, label),
            use_container_width=True,
        )
