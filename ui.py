# ui.py
# 2つのページで共通の表示部品（バッジ・チャート・HTMLテーブル）
import html
import json

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


# -----------------------------
# コピーボタン（クリップボードへ）
# -----------------------------
def copy_button_js(text, label, done_label="✓ コピー"):
    """onclick に入れるJS。text はJSON文字列化して安全に埋め込む"""
    t = json.dumps(text)
    l = json.dumps(label)
    d = json.dumps(done_label)
    return (
        f"const text = {t}; const btn = this;"
        f"const done = () => {{ btn.textContent = {d}; setTimeout(() => btn.textContent = {l}, 1500); }};"
        "const fallback = () => {"
        " const ta = document.createElement(\"textarea\"); ta.value = text;"
        " document.body.appendChild(ta); ta.select();"
        " try { document.execCommand(\"copy\"); done(); } catch (e) { btn.textContent = \"コピー失敗\"; }"
        " document.body.removeChild(ta); };"
        "if (navigator.clipboard) { navigator.clipboard.writeText(text).then(done).catch(fallback); } else { fallback(); }"
    )


def render_copy_button(text, label="📋 コピー"):
    """単独のコピーボタン（サイドバーなどに置く）"""
    js = html.escape(copy_button_js(text, label), quote=True)
    components.html(
        f"""
<button onclick="{js}" style="
    width: 100%; font-size: 15px; padding: 8px 10px; border-radius: 8px;
    border: 1px solid rgba(49,51,63,0.2); background: #ffffff; color: #31333f; cursor: pointer;
    font-family: 'Source Sans Pro', 'Hiragino Sans', 'Noto Sans JP', sans-serif;
">{html.escape(label)}</button>
""",
        height=48,
    )


# -----------------------------
# 投入ptの配分グラフ
# -----------------------------
def make_allocation_chart(labels, values, colors):
    """横棒（多い順に上から）。各棒に pt と構成比を表示"""
    total = sum(values) or 1
    order = sorted(range(len(values)), key=lambda i: values[i])  # 横棒は下から描かれるので昇順
    labels = [labels[i] for i in order]
    values = [values[i] for i in order]
    colors = [colors[i] for i in order]
    texts = [f"{v:,.0f} pt（{v / total * 100:.1f}%）" for v in values]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=colors, line=dict(color="#ffffff", width=2)),
            text=texts,
            textposition="outside",
            textfont=dict(color="#31333f", size=14),
            cliponaxis=False,
            hovertemplate="%{y}: %{x:,.0f} pt<extra></extra>",
        )
    )

    fig.update_layout(
        height=60 + 38 * len(values),
        margin=dict(l=10, r=150, t=10, b=10),
        showlegend=False,
        xaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.06)", tickformat=",", title=None),
        yaxis=dict(tickfont=dict(size=15)),
        bargap=0.25,
    )
    return fig


# -----------------------------
# 損益の推移
# -----------------------------
POS_COLOR = "#e06666"  # 利益（赤）
NEG_COLOR = "#6d9eeb"  # 損失（青）


def make_profit_bar_chart(labels, values, height=300):
    """期間ごとの損益（プラスは赤・マイナスは青）"""
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker=dict(
                color=[POS_COLOR if v >= 0 else NEG_COLOR for v in values],
                line=dict(color="#ffffff", width=2),
            ),
            hovertemplate="%{x}: %{y:+,.0f} pt<extra></extra>",
        )
    )
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
        yaxis=dict(title="pt", tickformat=",", zeroline=True, zerolinecolor="#999", gridcolor="rgba(0,0,0,0.06)"),
        xaxis=dict(type="category"),
        bargap=0.25,
    )
    return fig


def make_cumulative_chart(series, height=300):
    """通算損益の推移（1本の線）"""
    fig = go.Figure(
        go.Scatter(
            x=series.index,
            y=series.values,
            mode="lines",
            line=dict(width=2, color="#4a6fa5"),
            hovertemplate="%{x|%Y/%m/%d}: %{y:,.0f} pt<extra></extra>",
        )
    )
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
        hovermode="x",
        yaxis=dict(title="pt", tickformat=",", gridcolor="rgba(0,0,0,0.06)"),
    )
    return fig
