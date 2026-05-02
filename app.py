# app.py
from io import StringIO

import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import streamlit.components.v1 as components

from core import macd, rsi, slice_period, ETF_INFO

TARGET_ETFS = list(ETF_INFO.keys())
DISPLAY_ITEMS = TARGET_ETFS + ["USDJPY=X"]

DISPLAY_LABELS = {
    **ETF_INFO,
    "USDJPY=X": "ドル円",
}

THEME_COLORS = {
    "ICLN": "#8FD19E",
    "IEMG": "#F28B82",
    "IXP": "#C5B3E6",
    "IXJ": "#8FD3C7",
    "KXI": "#9ECAE1",
    "IAU": "#FFE066",
    "SDG": "#00C853",
    "IVV": "#8DA0CB",
    "USDJPY=X": "#CCCCCC",
}

# Excelの投入pt行の並び
# クリエネ, 新興国, コミュ, 生活必需品, ヘルスケア,
# ゴールド, SDGs, 日経, 日経Inv, おまかせ, 米国大型株
POINT_ORDER = [
    "ICLN",
    "IEMG",
    "IXP",
    "KXI",
    "IXJ",
    "IAU",
    "SDG",
    None,
    None,
    None,
    "IVV",
]

st.set_page_config(page_title="ETF Dashboard", layout="wide")

with st.sidebar:
    st.header("表示設定")

    period = st.selectbox("期間", ["All", "1Y", "3M", "1M"], index=3)
    currency = st.radio("建値", ["USD", "JPY"], index=1)

    view_mode = st.radio(
        "表示内容",
        ["3×3 Price", "3×3 MACD+RSI", "翌日更新予測", "Card Detail"],
        index=0,
    )

    sort_mode = st.radio(
        "並び替え",
        ["通常", "騰落率順"],
        index=0,
    )

    st.markdown("---")
    if st.button("🔄 データ更新"):
        st.cache_data.clear()
        st.rerun()


@st.cache_data(ttl=60 * 60 * 6)
def load_data():
    df = yf.download(DISPLAY_ITEMS, period="2y", auto_adjust=True)["Close"]
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


def parse_latest_points_row(text):
    if not text.strip():
        return {}

    values = text.strip().replace("\n", "\t").split("\t")
    points = {}

    for ticker, value in zip(POINT_ORDER, values):
        if ticker is None:
            continue

        try:
            points[ticker] = int(float(str(value).replace(",", "")))
        except ValueError:
            points[ticker] = 0

    return points


def make_title(ticker, label, df):
    perf, day_perf = calc_perf(df["Close"])

    title = f"{ticker}（{label}）"
    if perf is not None:
        title += f"｜{perf:+.1f}%"
    if day_perf is not None:
        title += f" / {day_perf:+.1f}%"

    return title


def render_title(ticker, label, df):
    title = make_title(ticker, label, df)
    color = THEME_COLORS.get(ticker, "#999999")

    st.markdown(
        f"""
        <div style="
            background-color: {color};
            color: black;
            font-weight: 700;
            padding: 6px 10px;
            border-radius: 8px;
            display: inline-block;
            margin-bottom: 6px;
            font-size: 0.95rem;
        ">
            {title}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_colored_label(ticker, text):
    color = THEME_COLORS.get(ticker, "#999999")

    st.markdown(
        f"""
        <div style="
            background-color: {color};
            color: black;
            font-weight: 700;
            padding: 6px 10px;
            border-radius: 8px;
            display: inline-block;
            font-size: 0.95rem;
        ">
            {text}
        </div>
        """,
        unsafe_allow_html=True,
    )


def make_price_chart(df, cur):
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
        height=240,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
        yaxis_title=cur,
    )

    return fig


def make_macd_rsi_chart(df):
    macd_line, signal_line = macd(df["Close"])
    rsi_line = rsi(df["Close"])

    df_ind = pd.DataFrame(
        {
            "MACD": macd_line,
            "Signal": signal_line,
            "RSI": rsi_line,
        }
    ).loc[df.index]

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df_ind.index,
            y=df_ind["MACD"],
            name="MACD",
            yaxis="y1",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df_ind.index,
            y=df_ind["Signal"],
            name="Signal",
            yaxis="y1",
        )
    )

    colors = []
    for v in df_ind["RSI"]:
        if pd.isna(v):
            colors.append("gray")
        elif v >= 70:
            colors.append("red")
        elif v <= 30:
            colors.append("blue")
        else:
            colors.append("rgba(100, 100, 255, 0.45)")

    fig.add_trace(
        go.Bar(
            x=df_ind.index,
            y=df_ind["RSI"],
            name="RSI",
            yaxis="y2",
            marker_color=colors,
            opacity=0.75,
        )
    )

    fig.update_layout(
        height=260,
        margin=dict(l=10, r=10, t=10, b=10),
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


def calc_next_update_predictions(raw, prev_ttm, current_fx, points_map):
    rows = []

    for ticker in TARGET_ETFS:
        if ticker not in raw.columns:
            continue

        series = raw[ticker].dropna()
        if len(series) < 2:
            continue

        prev_usd = series.iloc[-2]
        current_usd = series.iloc[-1]

        prev_jpy = prev_usd * prev_ttm
        current_jpy = current_usd * current_fx

        pred_pct = (current_jpy / prev_jpy - 1) * 100
        points = points_map.get(ticker, 0)
        pred_pt = points * pred_pct / 100
        after_pt = points + pred_pt

        rows.append(
            {
                "ticker": ticker,
                "テーマ": DISPLAY_LABELS.get(ticker, ticker),
                "予測騰落率": pred_pct,
                "投入pt": points,
                "予測変動pt": pred_pt,
                "予測更新後pt": after_pt,
                "ETF現在値": current_usd,
                "ETF前回値": prev_usd,
            }
        )

    return rows


raw = load_data()
fx = raw["USDJPY=X"].dropna() if "USDJPY=X" in raw.columns else pd.Series(dtype=float)
current_fx = fx.iloc[-1] if not fx.empty else None

items = []

for ticker in DISPLAY_ITEMS:
    price, cur = get_price_series(ticker, raw, fx, currency)
    if price is None:
        continue

    df = pd.DataFrame({"Close": price})
    df = slice_period(df, period)

    if df.empty:
        continue

    label = DISPLAY_LABELS.get(ticker, ticker)
    items.append((ticker, label, df, cur))


if sort_mode == "騰落率順":
    items.sort(
        key=lambda x: calc_perf(x[2]["Close"])[0]
        if calc_perf(x[2]["Close"])[0] is not None
        else -9999,
        reverse=True,
    )


if view_mode == "3×3 Price":
    cols = st.columns(3)

    for i, (ticker, label, df, cur) in enumerate(items):
        with cols[i % 3]:
            render_title(ticker, label, df)
            st.plotly_chart(
                make_price_chart(df, cur),
                use_container_width=True,
                config={"displayModeBar": False},
            )


elif view_mode == "3×3 MACD+RSI":
    cols = st.columns(3)

    for i, (ticker, label, df, cur) in enumerate(items):
        with cols[i % 3]:
            render_title(ticker, label, df)
            st.plotly_chart(
                make_macd_rsi_chart(df),
                use_container_width=True,
                config={"displayModeBar": False},
            )


elif view_mode == "翌日更新予測":
    st.markdown("### 翌日夕方更新予測")

    if current_fx is None:
        st.error("USDJPY=X を取得できませんでした。")
        st.stop()

    c1, c2 = st.columns(2)

    with c1:
        prev_ttm = st.number_input(
            "前回仲値（USD/JPY）",
            min_value=0.0,
            value=float(round(current_fx, 2)),
            step=0.01,
            format="%.2f",
        )

    with c2:
        st.metric("現在ドル円（API）", f"{current_fx:.2f}")

    point_text = st.text_area(
        "最新行の投入ポイントをExcelから貼り付け",
        height=80,
        placeholder="32,953\t0\t50,962\t49,815\t67,186\t45,868\t0\t0\t0\t130,335\t32,101",
    )

    points_map = parse_latest_points_row(point_text)

    pred_rows = calc_next_update_predictions(
        raw=raw,
        prev_ttm=prev_ttm,
        current_fx=current_fx,
        points_map=points_map,
    )

    pred_rows.sort(key=lambda x: x["予測騰落率"], reverse=True)

    total_points = sum(r["投入pt"] for r in pred_rows)
    total_change = sum(r["予測変動pt"] for r in pred_rows)

    m1, m2, m3 = st.columns(3)
    m1.metric("投入pt合計", f"{total_points:,.0f}")
    m2.metric("予測変動pt合計", f"{total_change:+,.0f}")
    if total_points:
        m3.metric("全体予測騰落率", f"{total_change / total_points * 100:+.2f}%")
    else:
        m3.metric("全体予測騰落率", "-")


    table_df = pd.DataFrame(pred_rows)

    table_df["ETF変動率"] = (
        (table_df["ETF現在値"] / table_df["ETF前回値"] - 1) * 100
    )

    table_df = table_df[
        [
            "テーマ",
            "ETF前回値",
            "ETF現在値",
            "ETF変動率",
            "予測騰落率",
            "予測変動pt",
        ]
    ]

    table_df["ETF前回値"] = table_df["ETF前回値"].map(lambda x: f"{x:,.2f}")
    table_df["ETF現在値"] = table_df["ETF現在値"].map(lambda x: f"{x:,.2f}")
    table_df["ETF変動率"] = table_df["ETF変動率"].map(lambda x: f"{x:+.2f}%")
    table_df["予測騰落率"] = table_df["予測騰落率"].map(lambda x: f"{x:+.2f}%")
    table_df["予測変動pt"] = table_df["予測変動pt"].map(lambda x: f"{x:+,.0f}")

    table_df.columns = [
        "テーマ",
        "昨日",
        "現在",
        "変動",
        "dポ投資",
        "予想損益",
    ]


        ticker = label_to_ticker.get(row["テーマ"])
        color = THEME_COLORS.get(ticker)

        styles = [""] * len(row)

        if color:
            styles[0] = f"background-color: {color}; color: black; font-weight: bold;"

        return styles

    def sign_class(val):
        text = str(val).replace("%", "").replace(",", "")
        try:
            num = float(text)
        except ValueError:
            return ""

        if num > 0:
            return "pos"
        elif num < 0:
            return "neg"
        return ""

    label_to_ticker = {
        "クリエネ": "ICLN",
        "新興国": "IEMG",
        "コミュ": "IXP",
        "生活必需品": "KXI",
        "ヘルスケア": "IXJ",
        "ゴールド": "IAU",
        "SDGs": "SDG",
        "米国大型株": "IVV",
    }

    rows_html = ""

    for _, row in table_df.iterrows():
        ticker = label_to_ticker.get(row["テーマ"])
        theme_color = THEME_COLORS.get(ticker, "#EEEEEE")

        rows_html += f"""
        <tr>
            <td class="theme" style="background-color:{theme_color};">{row["テーマ"]}</td>
            <td>{row["昨日"]}</td>
            <td>{row["現在"]}</td>
            <td class="{sign_class(row["変動"])}">{row["変動"]}</td>
            <td class="{sign_class(row["dポ投資"])}">{row["dポ投資"]}</td>
            <td class="{sign_class(row["予想損益"])}">{row["予想損益"]}</td>
        </tr>
        """

table_html = f"""
<style>
.prediction-table {{
    border-collapse: collapse;
    font-size: 22px;
    line-height: 1.35;
    margin-top: 12px;
    width: 760px;
}}

.prediction-table th,
.prediction-table td {{
    border: 1px solid #bbb;
    padding: 8px 14px;
    text-align: right;
    white-space: nowrap;
}}

.prediction-table th {{
    background-color: #f0f0f0;
    text-align: center;
    font-weight: 700;
}}

.prediction-table .theme {{
    color: black;
    text-align: center;
    font-weight: 700;
}}

.prediction-table .pos {{
    color: red;
    font-weight: 700;
}}

.prediction-table .neg {{
    color: blue;
    font-weight: 700;
}}
</style>

<table class="prediction-table">
<thead>
<tr>
<th>テーマ</th>
<th>昨日</th>
<th>現在</th>
<th>変動</th>
<th>dポ投資</th>
<th>予想損益</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
"""

components.html(
    table_html,
    height=420,
    scrolling=False,
)
