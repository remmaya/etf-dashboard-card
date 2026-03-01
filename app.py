# app.py
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

from core import macd, rsi, slice_period, ETF_INFO

# ETF_INFO のキー（ティッカー）をそのまま使う：8銘柄全部が対象
# ETF_INFO のキー（ティッカー）をそのまま使う：8銘柄全部が対象
TARGET_ETFS = list(ETF_INFO.keys())

def go_prev():
    cur = st.session_state.get("ticker_select", TARGET_ETFS[0])
    idx = TARGET_ETFS.index(cur)
    st.session_state["ticker_select"] = TARGET_ETFS[(idx - 1) % len(TARGET_ETFS)]

def go_next():
    cur = st.session_state.get("ticker_select", TARGET_ETFS[0])
    idx = TARGET_ETFS.index(cur)
    st.session_state["ticker_select"] = TARGET_ETFS[(idx + 1) % len(TARGET_ETFS)]

# ----------------------------------------
# ページ基本設定
# ----------------------------------------
st.set_page_config(page_title="ETF Dashboard", layout="centered")
st.title("ETF Dashboard（Price / MACD / RSI）")

# ----------------------------------------
# サイドバー（建値・期間・表示形式・レイアウト）
# ----------------------------------------
with st.sidebar:
    st.header("表示設定")

    # ★ デフォルト期間を 1M に
    period = st.selectbox("期間", ["All", "1Y", "3M", "1M"], index=3)

    currency = st.radio("建値", ["USD", "JPY"], index=1)

    view_mode = st.radio("表示内容", ["Price", "MACD+RSI"], index=0)

    # ★ レイアウト切り替え
    layout_mode = st.radio(
        "レイアウト",
        ["一覧（縦スクロール）", "カード（1銘柄ずつ）"],
        index=0,
    )

    st.markdown("---")
    if st.button("🔄 データ更新"):
        # キャッシュクリア & 再実行
        st.cache_data.clear()
        st.rerun()

# ----------------------------------------
# データ取得（cache付き）
# ----------------------------------------
@st.cache_data(ttl=60 * 60 * 6)  # 6時間キャッシュ
def load_data():
    tickers = TARGET_ETFS + ["USDJPY=X"]
    df = yf.download(tickers, period="2y", auto_adjust=True)["Close"]
    # 単一列のときでも DataFrame になるように調整
    if isinstance(df, pd.Series):
        df = df.to_frame()
    return df


raw = load_data()

# 為替（USD/JPY）
if "USDJPY=X" in raw.columns:
    fx = raw["USDJPY=X"].dropna()
else:
    fx = pd.Series(dtype=float)


# ----------------------------------------
# 1銘柄分の表示をまとめた関数
# ----------------------------------------
def render_etf_block(ticker, period, currency, view_mode, raw, fx, show_both: bool = False):
    if ticker not in raw.columns:
        return

    usd_series = raw[ticker].dropna()
    if usd_series.empty:
        return

    # 円建て or ドル建て
    if currency == "JPY" and not fx.empty:
        fx_aligned = fx.reindex(usd_series.index).ffill()
        price = usd_series * fx_aligned
        cur = "JPY"
    else:
        price = usd_series
        cur = "USD"

    df = pd.DataFrame({"Close": price})
    df = slice_period(df, period)
    if df.empty:
        return

    # パフォーマンス（期間内の騰落率）
    perf_pct = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
    label = ETF_INFO.get(ticker, ticker)

    # 見出し
    st.markdown(f"### {ticker}（{label}）｜ {perf_pct:+.2f}%  [{cur}]")

    # どのグラフを出すかを決定
    show_price = (view_mode == "Price") or show_both
    show_macd_rsi = (view_mode == "MACD+RSI") or show_both

    # ---------------------------
    # Price
    # ---------------------------
    if show_price:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["Close"],
                mode="lines",
                name="Price",
            )
        )
        fig.update_layout(
            height=280,
            margin=dict(l=20, r=20, t=40, b=20),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ---------------------------
    # MACD + RSI
    # ---------------------------
    if show_macd_rsi:
        macd_line, signal_line = macd(df["Close"])
        rsi_line = rsi(df["Close"])

        # ----- MACD -----
        macd_df = pd.DataFrame(
            {"MACD": macd_line, "Signal": signal_line}
        ).loc[df.index]

        fig_macd = go.Figure()

        fig_macd.add_trace(
            go.Scatter(
                x=macd_df.index,
                y=macd_df["MACD"],
                name="MACD",
                line=dict(color="blue", width=2),
            )
        )
        fig_macd.add_trace(
            go.Scatter(
                x=macd_df.index,
                y=macd_df["Signal"],
                name="Signal",
                line=dict(color="red", width=2),
            )
        )

        fig_macd.update_layout(
            height=260,
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
        )
        st.plotly_chart(fig_macd, use_container_width=True)

        # ----- RSI -----
        rsi_df = pd.DataFrame({"RSI": rsi_line}).loc[df.index]

        fig_rsi = go.Figure()
        fig_rsi.add_trace(
            go.Bar(
                x=rsi_df.index,
                y=rsi_df["RSI"],
                name="RSI",
                marker_color="rgba(100, 100, 255, 0.6)",
            )
        )

        for lvl in [30, 50, 70]:
            fig_rsi.add_hline(
                y=lvl,
                line_dash="dot",
                line_color="gray",
            )

        fig_rsi.update_layout(
            height=200,
            margin=dict(l=20, r=20, t=20, b=20),
            showlegend=False,
            yaxis=dict(range=[0, 100]),
        )
        st.plotly_chart(fig_rsi, use_container_width=True)

    # ETFごとに少し余白
    st.markdown("---")


# ----------------------------------------
# レイアウト切り替え
# ----------------------------------------
if layout_mode == "カード（1銘柄ずつ）":
    # 初期値のセット（selectbox 用）
    if "ticker_select" not in st.session_state:
        st.session_state["ticker_select"] = TARGET_ETFS[0]

    # ラベルは上にだけ表示
    st.caption("表示中のETF")

    col_left, col_center, col_right = st.columns([1, 4, 1])

    # ◀ ボタン（クリックで ticker_select を更新）
    with col_left:
        st.button("◀", on_click=go_prev, use_container_width=True)

    # 中央：セレクトボックス（ラベルは隠す）
    with col_center:
        current_ticker = st.selectbox(
            "",
            TARGET_ETFS,
            key="ticker_select",
            label_visibility="collapsed",
        )

    # ▶ ボタン
    with col_right:
        st.button("▶", on_click=go_next, use_container_width=True)

    # 選択中の1銘柄だけ表示（2段構成）
    render_etf_block(
        current_ticker,
        period,
        currency,
        view_mode,
        raw,
        fx,
        show_both=True,
    )

else:
    # 一覧（縦スクロール）モード
    for ticker in TARGET_ETFS:
        render_etf_block(ticker, period, currency, view_mode, raw, fx)
