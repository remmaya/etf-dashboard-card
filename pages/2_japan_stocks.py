from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import streamlit.components.v1 as components

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = BASE_DIR / "data" / "japan_holdings.csv"

st.set_page_config(page_title="日本株 Dashboard", layout="wide")


@st.cache_data(ttl=60 * 30)
def load_holdings():
    return pd.read_csv(CSV_PATH)


@st.cache_data(ttl=60 * 10)
def load_prices(tickers):
    df = yf.download(
        tickers,
        period="2y",
        auto_adjust=True,
        progress=False,
    )["Close"]

    if isinstance(df, pd.Series):
        df = df.to_frame()

    return df


def calc_perf(series):
    if len(series) < 2:
        return None, None

    period_perf = (series.iloc[-1] / series.iloc[0] - 1) * 100
    day_perf = (series.iloc[-1] / series.iloc[-2] - 1) * 100
    return period_perf, day_perf


def sign_class(val):
    try:
        val = float(val)
    except Exception:
        return ""

    if val > 0:
        return "pos"
    if val < 0:
        return "neg"
    return ""


def make_title(code, name, df):
    perf, day_perf = calc_perf(df["Close"])
    title = f"{code}（{name}）"

    if perf is not None:
        title += f"｜{perf:+.1f}%"
    if day_perf is not None:
        title += f" / {day_perf:+.1f}%"

    return title


def render_title(code, name, df):
    title = make_title(code, name, df)

    st.markdown(
        f"""
        <div style="
            background-color: #d9e8ff;
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


def make_price_chart(df):
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
        yaxis_title="JPY",
    )

    return fig


def macd(series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line


def rsi(series, period=14):
    diff = series.diff()
    gain = diff.clip(lower=0)
    loss = -diff.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


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


st.title("日本株 Dashboard")

with st.sidebar:
    st.header("表示設定")

    period = st.selectbox("期間", ["All", "1Y", "3M", "1M"], index=3)

    view_mode = st.radio(
        "表示内容",
        ["3×3 Price", "3×3 MACD+RSI", "Portfolio"],
        index=2,
    )

    sort_mode = st.radio(
        "並び替え",
        ["通常", "前日比順", "評価損益順", "評価額順"],
        index=0,
    )

    st.markdown("---")

    if st.button("🔄 データ更新"):
        st.cache_data.clear()

holdings = load_holdings().copy()

holdings["code"] = holdings["code"].astype(str)

def make_yfinance_ticker(code):
    code = str(code).strip()
    if code.startswith("^"):
        return code
    return code + ".T"

holdings["ticker"] = holdings["code"].apply(make_yfinance_ticker)

tickers = holdings["ticker"].tolist()
prices = load_prices(tickers)

items = []

for _, row in holdings.iterrows():
    ticker = row["ticker"]

    if ticker not in prices.columns:
        continue

    series = prices[ticker].dropna()
    if series.empty:
        continue

    df = pd.DataFrame({"Close": series})

    if period != "All":
        if period == "1Y":
            df = df.tail(252)
        elif period == "3M":
            df = df.tail(63)
        elif period == "1M":
            df = df.tail(21)

    if df.empty:
        continue

    items.append(
        {
            "code": row["code"],
            "ticker": ticker,
            "name": row["name"],
            "shares": int(row["shares"]),
            "avg_price": float(row["avg_price"]),
            "df": df,
        }
    )


def make_portfolio_rows(items):
    rows = []

    total_value = 0
    total_profit = 0
    total_day_change = 0
    total_cost = 0

    for item in items:
        df = item["df"]
        series = df["Close"].dropna()

        if len(series) < 2:
            continue

        current_price = float(series.iloc[-1])
        prev_price = float(series.iloc[-2])

        shares = item["shares"]
        avg_price = item["avg_price"]

        value = current_price * shares
        prev_value = prev_price * shares

        cost = avg_price * shares

        if avg_price > 0:
            profit = value - cost
            profit_pct = (current_price / avg_price - 1) * 100
        else:
            profit = value
            profit_pct = 0

        day_change = value - prev_value
        day_change_pct = (current_price / prev_price - 1) * 100

        total_value += value
        total_profit += profit
        total_day_change += day_change
        total_cost += cost

        rows.append(
            {
                "code": item["code"],
                "銘柄": item["name"],
                "株数": shares,
                "取得単価": avg_price,
                "現在値": current_price,
                "評価額": value,
                "評価損益": profit,
                "損益率": profit_pct,
                "前日比": day_change,
                "前日比率": day_change_pct,
            }
        )

    total_profit_pct = (
        total_profit / total_cost * 100
        if total_cost > 0
        else 0
    )

    return rows, total_value, total_profit, total_profit_pct, total_day_change


portfolio_rows, total_value, total_profit, total_profit_pct, total_day_change = make_portfolio_rows(items)

if sort_mode == "前日比順":
    portfolio_rows.sort(key=lambda x: x["前日比"], reverse=True)
elif sort_mode == "評価損益順":
    portfolio_rows.sort(key=lambda x: x["評価損益"], reverse=True)
elif sort_mode == "評価額順":
    portfolio_rows.sort(key=lambda x: x["評価額"], reverse=True)

if view_mode in ["3×3 Price", "3×3 MACD+RSI"]:
    cols = st.columns(3)

    for i, item in enumerate(items):
        with cols[i % 3]:
            render_title(item["code"], item["name"], item["df"])

            if view_mode == "3×3 Price":
                st.plotly_chart(
                    make_price_chart(item["df"]),
                    width="stretch",
                    config={"displayModeBar": False},
                )

            elif view_mode == "3×3 MACD+RSI":
                st.plotly_chart(
                    make_macd_rsi_chart(item["df"]),
                    width="stretch",
                    config={"displayModeBar": False},
                )


elif view_mode == "Portfolio":
    rows_html = ""

    for row in portfolio_rows:
        rows_html += f"""
<tr>
    <td class="name">{row["銘柄"]}</td>
    <td>{row["株数"]:,}</td>
    <td>{row["取得単価"]:,.0f}</td>
    <td>{row["現在値"]:,.0f}</td>
    <td>{row["評価額"]:,.0f}</td>
    <td class="{sign_class(row["評価損益"])}">{row["評価損益"]:+,.0f}</td>
    <td class="{sign_class(row["損益率"])}">{row["損益率"]:+.2f}%</td>
    <td class="{sign_class(row["前日比"])}">{row["前日比"]:+,.0f}</td>
    <td class="{sign_class(row["前日比率"])}">{row["前日比率"]:+.2f}%</td>
</tr>
"""

    rows_html += f"""
<tr class="total-row">
    <td class="name total-name">合計</td>
    <td></td>
    <td></td>
    <td></td>
    <td>{total_value:,.0f}</td>
    <td class="{sign_class(total_profit)}">{total_profit:+,.0f}</td>
    <td class="{sign_class(total_profit_pct)}">{total_profit_pct:+.2f}%</td>
    <td class="{sign_class(total_day_change)}">{total_day_change:+,.0f}</td>
    <td></td>
</tr>
"""

    table_html = f"""
<style>
html,
body {{
    background: transparent !important;
    color: #111111 !important;
    margin: 0;
    padding: 0;
}}

.stock-table {{
    background: #ffffff !important;
    color: #111111 !important;
    border-collapse: collapse;
    font-size: 18px;
    line-height: 1.35;
    margin-top: 12px;
    width: max-content;
    min-width: 980px;
}}

.stock-table th,
.stock-table td {{
    color: #111111 !important;
    border: 1px solid #bbb;
    padding: 8px 14px;
    text-align: right;
    white-space: nowrap;
}}

.stock-table th {{
    background-color: #f0f0f0;
    text-align: center;
    font-weight: 700;
}}

.stock-table .name {{
    color: black !important;
    background: #ffffff !important;
    text-align: left;
    font-weight: 700;

    position: sticky;
    left: 0;
    z-index: 2;

    box-shadow: 2px 0 0 #bbb;
}}

.stock-table th:first-child {{
    position: sticky;
    left: 0;
    z-index: 3;
    background-color: #f0f0f0;
}}

.stock-table .pos {{
    color: red !important;
    font-weight: 700;
}}

.stock-table .neg {{
    color: blue !important;
    font-weight: 700;
}}

.stock-table .total-row td {{
    background-color: #f5f5f5 !important;
    font-weight: 700;
    border-top: 3px solid #777;
}}

.stock-table .total-name {{
    background-color: #e0e0e0 !important;
}}

.table-wrap {{
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}}
</style>

<div class="table-wrap">
<table class="stock-table">
<thead>
<tr>
<th>銘柄</th>
<th>株数</th>
<th>取得単価</th>
<th>現在値</th>
<th>評価額</th>
<th>評価損益</th>
<th>損益率</th>
<th>前日比</th>
<th>前日比率</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>
"""

    components.html(
        table_html,
        height=700,
        scrolling=True,
    )

with st.expander("保有銘柄CSVを編集"):
    edited = st.data_editor(
        holdings.drop(columns=["ticker"], errors="ignore"),
        num_rows="dynamic",
        width="stretch",
    )

    if st.button("CSVに保存"):
        edited.to_csv(CSV_PATH, index=False)
        st.cache_data.clear()
        st.success("保存しました。画面を再読み込みしてください。")
