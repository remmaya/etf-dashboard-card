import html
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core import calc_perf, slice_period  # noqa: E402
from ui import (  # noqa: E402
    make_macd_rsi_chart,
    make_price_chart,
    render_html_table,
    render_title,
    show_chart,
    sign_class,
)

CSV_PATH = BASE_DIR / "data" / "japan_holdings.csv"
CSV_COLUMNS = ["code", "name", "shares", "avg_price"]
BADGE_COLOR = "#d9e8ff"

st.set_page_config(page_title="日本株 Dashboard", layout="wide")


# -----------------------------
# データ取得
# -----------------------------
@st.cache_data(ttl=60 * 30)
def load_holdings():
    df = pd.read_csv(CSV_PATH, dtype={"code": str})
    df["code"] = df["code"].str.strip()
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0).astype(int)
    df["avg_price"] = pd.to_numeric(df["avg_price"], errors="coerce").fillna(0.0)
    return df.dropna(subset=["code"])


@st.cache_data(ttl=60 * 10)
def load_prices(tickers):
    df = yf.download(
        list(tickers),
        period="2y",
        auto_adjust=True,
        progress=False,
    )["Close"]

    if isinstance(df, pd.Series):
        df = df.to_frame(name=tickers[0])

    return df


def make_yfinance_ticker(code):
    code = str(code).strip()
    if code.startswith("^"):
        return code
    return code + ".T"


def calc_position(close, shares, avg_price):
    """1銘柄分の評価額・損益・前日比を計算する"""
    if len(close) < 2:
        return None

    current_price = float(close.iloc[-1])
    prev_price = float(close.iloc[-2])

    value = current_price * shares
    cost = avg_price * shares

    if avg_price > 0:
        profit = value - cost
        profit_pct = (current_price / avg_price - 1) * 100
    else:
        # 取得単価0（無償取得など）の場合は評価額をそのまま損益とする（従来どおり）
        profit = value
        profit_pct = 0.0

    return {
        "現在値": current_price,
        "評価額": value,
        "取得額": cost,
        "評価損益": profit,
        "損益率": profit_pct,
        "前日比": (current_price - prev_price) * shares,
        "前日比率": (current_price / prev_price - 1) * 100,
    }


# -----------------------------
# サイドバー
# -----------------------------
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


# -----------------------------
# 表示用データの準備
# -----------------------------
holdings = load_holdings().copy()
holdings["ticker"] = holdings["code"].apply(make_yfinance_ticker)

tickers = tuple(holdings["ticker"].tolist())

try:
    prices = load_prices(tickers)
except Exception:
    st.error("価格データの取得に失敗しました。少し時間をおいて「🔄 データ更新」を押してください。")
    st.stop()

items = []
missing = []

for _, row in holdings.iterrows():
    ticker = row["ticker"]

    if ticker not in prices.columns or prices[ticker].dropna().empty:
        missing.append(f"{row['code']}（{row['name']}）")
        continue

    full = prices[ticker].dropna()
    close = slice_period(pd.DataFrame({"Close": full}), period)["Close"]
    if close.empty:
        continue

    items.append(
        {
            "code": row["code"],
            "ticker": ticker,
            "name": row["name"],
            "shares": int(row["shares"]),
            "avg_price": float(row["avg_price"]),
            "close": close,   # 表示期間
            "full": full,     # 全期間（指標計算用・前日比用）
            # 前日比は表示期間に関係なく全期間データの直近2日で計算
            "pos": calc_position(full, int(row["shares"]), float(row["avg_price"])),
        }
    )

if missing:
    st.warning("価格を取得できなかった銘柄: " + "、".join(missing))

# 並び替え（グラフ表示にも反映）
SORT_KEYS = {
    "前日比順": "前日比",
    "評価損益順": "評価損益",
    "評価額順": "評価額",
}
sort_key = SORT_KEYS.get(sort_mode)
if sort_key:
    items.sort(
        key=lambda x: x["pos"][sort_key] if x["pos"] else float("-inf"),
        reverse=True,
    )


# -----------------------------
# 3×3 Price / 3×3 MACD+RSI
# -----------------------------
if view_mode in ["3×3 Price", "3×3 MACD+RSI"]:
    cols = st.columns(3)

    for i, item in enumerate(items):
        with cols[i % 3]:
            render_title(item["code"], item["name"], item["close"], color=BADGE_COLOR)

            if view_mode == "3×3 Price":
                y_title = "pt" if item["ticker"].startswith("^") else "JPY"
                show_chart(make_price_chart(item["close"], y_title))
            else:
                show_chart(make_macd_rsi_chart(item["full"], item["close"].index))


# -----------------------------
# Portfolio
# -----------------------------
elif view_mode == "Portfolio":
    # 株数0の銘柄（日経平均などの参考指標）は表から除外
    held = [it for it in items if it["shares"] > 0 and it["pos"]]

    total_value = sum(it["pos"]["評価額"] for it in held)
    total_cost = sum(it["pos"]["取得額"] for it in held if it["avg_price"] > 0)
    total_profit = sum(it["pos"]["評価損益"] for it in held)
    total_day_change = sum(it["pos"]["前日比"] for it in held)
    total_profit_pct = total_profit / total_cost * 100 if total_cost > 0 else 0
    prev_total = total_value - total_day_change
    total_day_pct = total_day_change / prev_total * 100 if prev_total > 0 else 0

    # 上部サマリー
    m1, m2, m3 = st.columns(3)
    m1.metric("評価額 合計", f"{total_value:,.0f} 円")
    m2.metric("評価損益", f"{total_profit:+,.0f} 円", f"{total_profit_pct:+.2f}%")
    m3.metric("前日比", f"{total_day_change:+,.0f} 円", f"{total_day_pct:+.2f}%")

    rows_html = ""
    for it in held:
        p = it["pos"]
        rows_html += f"""
<tr>
    <td class="first left">{html.escape(str(it["name"]))}</td>
    <td>{it["shares"]:,}</td>
    <td>{it["avg_price"]:,.0f}</td>
    <td>{p["現在値"]:,.0f}</td>
    <td>{p["評価額"]:,.0f}</td>
    <td class="{sign_class(p["評価損益"])}">{p["評価損益"]:+,.0f}</td>
    <td class="{sign_class(p["損益率"])}">{p["損益率"]:+.2f}%</td>
    <td class="{sign_class(p["前日比"])}">{p["前日比"]:+,.0f}</td>
    <td class="{sign_class(p["前日比率"])}">{p["前日比率"]:+.2f}%</td>
</tr>
"""

    rows_html += f"""
<tr class="total-row">
    <td class="first left">合計</td>
    <td></td>
    <td></td>
    <td></td>
    <td>{total_value:,.0f}</td>
    <td class="{sign_class(total_profit)}">{total_profit:+,.0f}</td>
    <td class="{sign_class(total_profit_pct)}">{total_profit_pct:+.2f}%</td>
    <td class="{sign_class(total_day_change)}">{total_day_change:+,.0f}</td>
    <td class="{sign_class(total_day_pct)}">{total_day_pct:+.2f}%</td>
</tr>
"""

    header_html = "".join(
        f"<th>{h}</th>"
        for h in ["銘柄", "株数", "取得単価", "現在値", "評価額", "評価損益", "損益率", "前日比", "前日比率"]
    )

    render_html_table(header_html, rows_html, min_width=980, rows_count=len(held) + 1)


# -----------------------------
# CSV編集
# -----------------------------
with st.expander("保有銘柄CSVを編集"):
    st.caption(
        "※ 保存先はアプリが動いている環境内のファイルです。"
        "Streamlit Cloud では再起動で元に戻るため、恒久的に残すには GitHub の data/japan_holdings.csv も更新してください。"
    )

    edited = st.data_editor(
        holdings[CSV_COLUMNS],
        num_rows="dynamic",
        width="stretch",
        column_config={
            "code": st.column_config.TextColumn("code", required=True),
            "name": st.column_config.TextColumn("name", required=True),
            "shares": st.column_config.NumberColumn("shares", min_value=0, step=1, format="%d"),
            "avg_price": st.column_config.NumberColumn("avg_price", min_value=0.0, format="%.2f"),
        },
    )

    if st.button("CSVに保存"):
        to_save = edited.dropna(subset=["code"]).copy()
        to_save["code"] = to_save["code"].astype(str).str.strip()
        to_save = to_save[to_save["code"] != ""]
        to_save["shares"] = pd.to_numeric(to_save["shares"], errors="coerce").fillna(0).astype(int)
        to_save["avg_price"] = pd.to_numeric(to_save["avg_price"], errors="coerce").fillna(0.0)

        to_save.to_csv(CSV_PATH, index=False)
        st.cache_data.clear()
        st.session_state["csv_saved"] = True
        st.rerun()

    if st.session_state.pop("csv_saved", False):
        st.success("保存しました。")
