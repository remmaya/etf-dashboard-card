# ui.py
# 2つのページで共通の表示部品（バッジ・チャート・HTMLテーブル）
import html

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from core import calc_indicators, calc_perf

PLOTLY_CONFIG = {"displayModeBar": False}


# -----------------------------
# 正負の色分け用クラス
# -----------------------------
def sign_class(val):
    """数値・"+1.23%"・"-1,234" などを受け取り、pos / neg / "" を返す"""
    text = str(val).replace("%", "").replace(",", "").strip()
    try:
        num = float(text)
    except ValueError:
        return ""

    if num > 0:
        return "pos"
    if num < 0:
        return "neg"
    return ""


# -----------------------------
# タイトルバッジ
# -----------------------------
def make_title(code, label, close):
    perf, day_perf = calc_perf(close)
    title = f"{code}（{label}）"

    if perf is not None:
        title += f"｜{perf:+.1f}%"
    if day_perf is not None:
        title += f" / {day_perf:+.1f}%"

    return title


def render_badge(text, color="#999999", margin_bottom=6):
    st.markdown(
        f"""
        <div style="
            background-color: {color};
            color: black;
            font-weight: 700;
            padding: 6px 10px;
            border-radius: 8px;
            display: inline-block;
            margin-bottom: {margin_bottom}px;
            font-size: 0.95rem;
        ">
            {html.escape(str(text))}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_title(code, label, close, color="#999999"):
    render_badge(make_title(code, label, close), color=color)


# -----------------------------
# チャート
# -----------------------------
def make_price_chart(close, y_title):
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=close.index,
            y=close,
            mode="lines",
            name="Price",
        )
    )

    fig.update_layout(
        height=240,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
        yaxis_title=y_title,
    )

    return fig


def _rsi_color(v):
    if v != v:  # NaN
        return "gray"
    if v >= 70:
        return "red"
    if v <= 30:
        return "blue"
    return "rgba(100, 100, 255, 0.45)"


def make_macd_rsi_chart(full_close, display_index):
    """
    full_close   : 全期間の終値（指標の計算用）
    display_index: 表示する期間のインデックス
    """
    df_ind = calc_indicators(full_close, display_index)

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(x=df_ind.index, y=df_ind["MACD"], name="MACD", yaxis="y1")
    )
    fig.add_trace(
        go.Scatter(x=df_ind.index, y=df_ind["Signal"], name="Signal", yaxis="y1")
    )
    fig.add_trace(
        go.Bar(
            x=df_ind.index,
            y=df_ind["RSI"],
            name="RSI",
            yaxis="y2",
            marker_color=[_rsi_color(v) for v in df_ind["RSI"]],
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


def show_chart(fig):
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)


# -----------------------------
# HTMLテーブル（スマホで横スクロール＆1列目固定）
# -----------------------------
TABLE_CSS = """
<style>
html,
body {
    background: transparent !important;
    color: #111111 !important;
    margin: 0;
    padding: 0;
    font-family: "Source Sans Pro", "Hiragino Sans", "Noto Sans JP", sans-serif;
}

.dash-table {
    background: #ffffff !important;
    color: #111111 !important;
    border-collapse: collapse;
    font-size: 18px;
    line-height: 1.35;
    margin-top: 12px;
    width: max-content;
}

.dash-table th,
.dash-table td {
    color: #111111 !important;
    border: 1px solid #bbb;
    padding: 8px 14px;
    text-align: right;
    white-space: nowrap;
}

.dash-table th {
    background-color: #f0f0f0;
    text-align: center;
    font-weight: 700;
}

.dash-table .first {
    color: black !important;
    background: #ffffff;
    font-weight: 700;

    position: sticky;
    left: 0;
    z-index: 2;

    box-shadow: 2px 0 0 #bbb;
}

.dash-table .first.left {
    text-align: left;
}

.dash-table .first.center {
    text-align: center;
}

.dash-table th:first-child {
    position: sticky;
    left: 0;
    z-index: 3;
    background-color: #f0f0f0;
}

.dash-table .pos {
    color: red !important;
    font-weight: 700;
}

.dash-table .neg {
    color: blue !important;
    font-weight: 700;
}

.dash-table .total-row td {
    background-color: #f5f5f5;
    font-weight: 700;
    border-top: 3px solid #777;
}

.dash-table .total-row td.first {
    background-color: #e0e0e0;
}

.dash-table .copy-btn {
    margin-left: 10px;
    font-size: 18px;
    padding: 6px 10px;
    border-radius: 5px;
    border: 1px solid #999;
    background: #ffffff;
    color: #111111;
    cursor: pointer;
}

.table-wrap {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}
</style>
"""


def render_html_table(header_html, rows_html, min_width=860, rows_count=10):
    """
    header_html: <th>...</th> を並べた文字列
    rows_html  : <tr>...</tr> を並べた文字列
    rows_count : 行数（iframeの高さ計算用）
    """
    table_html = f"""
{TABLE_CSS}
<div class="table-wrap">
<table class="dash-table" style="min-width:{min_width}px;">
<thead><tr>{header_html}</tr></thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>
"""
    # 行数に合わせて高さを決める（余白が大きくなりすぎないように）
    height = min(60 + 46 * (rows_count + 1), 900)
    components.html(table_html, height=height, scrolling=True)
