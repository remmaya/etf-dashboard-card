# app.py
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

from core import macd, rsi, slice_period, ETF_INFO

# ETF_INFO のキー（ティッカー）をそのまま使う：8銘柄全部が対象
TARGET_ETFS = list(ETF_INFO.keys())


# ----------------------------------------
# ETF 選択用：矢印ボタンのハンドラ
# ----------------------------------------
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
st.title("ETF Dashboard")

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
# ETF ラベル文字列（ティッカー＋日本語名＋騰落率＋通貨）を作るヘルパ
# ----------------------------------------
def build_etf_label(ticker, period, currency, raw, fx):
    """
    ICLN → 'ICLN（クリエネ）｜ -2.12% [JPY]' みたいな表示用ラベルを作る。
    データが欠ける場合は単純に 'ICLN（クリエネ）' を返す。
    """
    if ticker not in raw.columns:
        return ticker

    usd_series = raw[ticker].dropna()
    if usd_series.empty:
        return ticker

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
        # 期間内データがなければ騰落率は出さない
        label_jp = ETF_INFO.get(ticker, ticker)
        return f"{ticker}（{label_jp}）"

    perf_pct = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
    label_jp = ETF_INFO.get(ticker, ticker)
    return f"{ticker}（{label_jp}）｜ {perf_pct:+.2f}% [{cur}]"


# ----------------------------------------
# 1銘柄分の表示をまとめた関数
# ----------------------------------------
def render_etf_block(
    ticker,
    period,
    currency,
    view_mode,
    raw,
    fx,
    show_both: bool = False,
    compact: bool = False,
    show_heading: bool = True,
):
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

    # 見出し（カードモードでは非表示にできる）
    if show_heading:
        st.markdown(f"### {ticker}（{label}）｜ {perf_pct:+.2f}%  [{cur}]")

    # どのグラフを出すかを決定
    show_price = (view_mode == "Price") or show_both
    show_macd_rsi = (view_mode == "MACD+RSI") or show_both

    # コンパクトモード用の高さ
    price_height = 220 if compact else 280
    mr_height = 260 if compact else 320

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
            height=price_height,
            margin=dict(l=20, r=20, t=40, b=20),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ---------------------------
    # MACD + RSI（1枚のグラフに統合）
    # ---------------------------
    if show_macd_rsi:
        macd_line, signal_line = macd(df["Close"])
        rsi_line = rsi(df["Close"])

        macd_df = pd.DataFrame(
            {"MACD": macd_line, "Signal": signal_line}
        ).loc[df.index]
        rsi_df = pd.DataFrame({"RSI": rsi_line}).loc[df.index]

        fig_mr = go.Figure()

        # --- MACD / Signal（左軸・折れ線） ---
        fig_mr.add_trace(
            go.Scatter(
                x=macd_df.index,
                y=macd_df["MACD"],
                name="MACD",
                line=dict(color="blue", width=2),
                yaxis="y",
            )
        )
        fig_mr.add_trace(
            go.Scatter(
                x=macd_df.index,
                y=macd_df["Signal"],
                name="Signal",
                line=dict(color="red", width=2),
                yaxis="y",
            )
        )

        # --- RSI（右軸・棒グラフ：ゾーンで色分け） ---
        # 30 未満 = 水色, 70 超 = 赤, それ以外 = 既存の青系
        rsi_colors = []
        for v in rsi_df["RSI"]:
            if pd.isna(v):
                # 欠損は透明にしておく
                rsi_colors.append("rgba(0, 0, 0, 0)")
            elif v < 30:
                # 水色（オーバーソールド）
                rsi_colors.append("rgba(0, 191, 255, 0.8)")  # DeepSkyBlue-ish
            elif v > 70:
                # 赤（オーバーボート）
                rsi_colors.append("rgba(255, 99, 132, 0.85)")
            else:
                # 通常ゾーンは従来どおり薄い青
                rsi_colors.append("rgba(100, 100, 255, 0.4)")

        fig_mr.add_trace(
            go.Bar(
                x=rsi_df.index,
                y=rsi_df["RSI"],
                name="RSI",
                marker_color=rsi_colors,
                yaxis="y2",
            )
        )
        # RSI 30/50/70 の基準線（右軸）
        if not rsi_df.empty:
            x0 = rsi_df.index.min()
            x1 = rsi_df.index.max()
            for lvl in [30, 50, 70]:
                fig_mr.add_shape(
                    type="line",
                    x0=x0,
                    x1=x1,
                    y0=lvl,
                    y1=lvl,
                    xref="x",
                    yref="y2",
                    line=dict(color="gray", dash="dot"),
                )

        fig_mr.update_layout(
            height=mr_height,
            margin=dict(l=20, r=20, t=40, b=20),
            barmode="overlay",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            # 左軸：MACD
            yaxis=dict(
                title="MACD",
                showgrid=True,
            ),
            # 右軸：RSI（0〜100）
            yaxis2=dict(
                title="RSI",
                overlaying="y",
                side="right",
                range=[0, 100],
                showgrid=False,
            ),
        )

        st.plotly_chart(fig_mr, use_container_width=True)

    # ETFごとに少し余白（一覧モードのみ）
    if not compact:
        st.markdown("---")


# ----------------------------------------
# レイアウト切り替え
# ----------------------------------------
if layout_mode == "カード（1銘柄ずつ）":
    # 初期値のセット（selectbox 用）
    if "ticker_select" not in st.session_state:
        st.session_state["ticker_select"] = TARGET_ETFS[0]

    # 各ETFの表示用ラベルを事前計算
    etf_labels = {
        t: build_etf_label(t, period, currency, raw, fx) for t in TARGET_ETFS
    }

    # 3 カラムで ◀ [ETFラベル付きセレクト] ▶ を 1 行にまとめる
    col_left, col_center, col_right = st.columns([1, 4, 1])

    # ◀ ボタン
    with col_left:
        st.button("◀", on_click=go_prev, use_container_width=True)

    # セレクトボックス（ラベルは隠して中身にラベル文字列を表示）
    with col_center:
        # セレクトの見た目を少しだけ短く抑える（任意）
        st.markdown(
            """
            <style>
            div[data-baseweb="select"] {
                max-width: 260px !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        current_ticker = st.selectbox(
            "",
            TARGET_ETFS,
            key="ticker_select",
            format_func=lambda x: etf_labels.get(x, x),
            label_visibility="collapsed",
        )

    # ▶ ボタン
    with col_right:
        st.button("▶", on_click=go_next, use_container_width=True)

    # 選択中の1銘柄だけ表示（カードモードは常に2段＋コンパクト）
    # ※ 見出しは selectbox に統合したので show_heading=False
    render_etf_block(
        current_ticker,
        period,
        currency,
        view_mode,
        raw,
        fx,
        show_both=True,
        compact=True,
        show_heading=False,
    )

else:
    # 一覧（縦スクロール）モード：従来どおり view_mode に従う
    for ticker in TARGET_ETFS:
        render_etf_block(
            ticker,
            period,
            currency,
            view_mode,
            raw,
            fx,
            show_both=False,
            compact=False,
            show_heading=True,
        )
