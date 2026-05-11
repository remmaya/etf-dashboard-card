import streamlit as st
import pandas as pd
import yfinance as yf
import streamlit.components.v1 as components

st.set_page_config(page_title="日本株 Dashboard", layout="wide")

CSV_PATH = "data/japan_holdings.csv"


@st.cache_data(ttl=60 * 30)
def load_holdings():
    return pd.read_csv(CSV_PATH)


@st.cache_data(ttl=60 * 10)
def load_prices(tickers):
    df = yf.download(
        tickers,
        period="5d",
        auto_adjust=True,
        progress=False,
    )["Close"]

    if isinstance(df, pd.Series):
        df = df.to_frame()

    return df


def sign_class(val):
    if val > 0:
        return "pos"
    if val < 0:
        return "neg"
    return ""


st.title("日本株 Dashboard")

holdings = load_holdings()

holdings["ticker"] = holdings["code"].astype(str) + ".T"

prices = load_prices(holdings["ticker"].tolist())

table_rows = []

total_value = 0
total_profit = 0
total_day_change = 0

for _, row in holdings.iterrows():
    ticker = row["ticker"]

    if ticker not in prices.columns:
        continue

    s = prices[ticker].dropna()

    if len(s) < 2:
        continue

    current_price = float(s.iloc[-1])
    prev_price = float(s.iloc[-2])

    shares = int(row["shares"])
    avg_price = float(row["avg_price"])

    value = current_price * shares

    profit = (current_price - avg_price) * shares
    profit_pct = (
        (current_price / avg_price - 1) * 100
        if avg_price > 0
        else 0
    )

    day_change = (current_price - prev_price) * shares
    day_change_pct = (current_price / prev_price - 1) * 100

    total_value += value
    total_profit += profit
    total_day_change += day_change

    table_rows.append(
        {
            "銘柄": row["name"],
            "株数": f"{shares:,}",
            "取得単価": f"{avg_price:,.0f}",
            "現在値": f"{current_price:,.0f}",
            "評価額": f"{value:,.0f}",
            "評価損益": profit,
            "損益率": profit_pct,
            "前日比": day_change,
            "前日比率": day_change_pct,
        }
    )

rows_html = ""

for row in table_rows:
    rows_html += f"""
<tr>
<td class="name">{row["銘柄"]}</td>
<td>{row["株数"]}</td>
<td>{row["取得単価"]}</td>
<td>{row["現在値"]}</td>
<td>{row["評価額"]}</td>

<td class="{sign_class(row["評価損益"])}">
{row["評価損益"]:+,.0f}
</td>

<td class="{sign_class(row["損益率"])}">
{row["損益率"]:+.2f}%
</td>

<td class="{sign_class(row["前日比"])}">
{row["前日比"]:+,.0f}
</td>

<td class="{sign_class(row["前日比率"])}">
{row["前日比率"]:+.2f}%
</td>
</tr>
"""

rows_html += f"""
<tr class="total-row">
<td class="name">合計</td>
<td></td>
<td></td>
<td></td>

<td>{total_value:,.0f}</td>

<td class="{sign_class(total_profit)}">
{total_profit:+,.0f}
</td>

<td></td>

<td class="{sign_class(total_day_change)}">
{total_day_change:+,.0f}
</td>

<td></td>
</tr>
"""

table_html = f"""
<style>

.stock-table {{
    border-collapse: collapse;
    font-size: 18px;
    min-width: 1100px;
    background: white;
}}

.stock-table th,
.stock-table td {{
    border: 1px solid #bbb;
    padding: 8px 14px;
    text-align: right;
    white-space: nowrap;
}}

.stock-table th {{
    background: #f0f0f0;
    font-weight: 700;
}}

.stock-table .name {{
    text-align: left;
    font-weight: 700;

    position: sticky;
    left: 0;
    background: white;
    z-index: 2;
}}

.stock-table th:first-child {{
    position: sticky;
    left: 0;
    z-index: 3;
}}

.stock-table .pos {{
    color: red;
    font-weight: 700;
}}

.stock-table .neg {{
    color: blue;
    font-weight: 700;
}}

.stock-table .total-row td {{
    border-top: 3px solid #777;
    background: #f5f5f5;
    font-weight: 700;
}}

.table-wrap {{
    overflow-x: auto;
    width: 100%;
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
