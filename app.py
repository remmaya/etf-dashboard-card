# app.py
import html
import json

import pandas as pd
import streamlit as st
import yfinance as yf

from core import ETF_INFO, calc_perf, slice_period
from ui import (
    make_macd_rsi_chart,
    make_price_chart,
    render_html_table,
    render_title,
    show_chart,
    sign_class,
)

TARGET_ETFS = list(ETF_INFO.keys())
FX_TICKER = "USDJPY=X"
DISPLAY_ITEMS = TARGET_ETFS + [FX_TICKER]

DISPLAY_LABELS = {
    **ETF_INFO,
    FX_TICKER: "ドル円",
}

THEME_COLORS = {
    "ICLN": "#97e993",
    "IEMG": "#ff8989",
    "IXP": "#b9b8f0",
    "IXJ": "#87d9d6",
    "KXI": "#a7dcf5",
    "IAU": "#dcda00",
    "SDG": "#00dc1a",
    "IVV": "#8ea9db",
    FX_TICKER: "#CCCCCC",
}

# Googleスプレッドシートの投入pt行の並び（A2:K2）
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

# 予測テーブル・Excel貼り付け用の並び
PREDICTION_ORDER = [FX_TICKER, "ICLN", "IEMG", "IXP", "IXJ", "KXI", "IAU", "SDG", "IVV"]

DEFAULT_DPOINT_POINTS_CSV_URL = "https://docs.google.com/spreadsheets/d/1Nr-e5iOt0j7i2njxQixPMSnky16KQqR_4REXHnxizsY/export?format=csv&gid=0"


def get_points_csv_url():
    """Secrets に DPOINT_POINTS_CSV_URL があればそちらを優先する"""
    try:
        return st.secrets.get("DPOINT_POINTS_CSV_URL", DEFAULT_DPOINT_POINTS_CSV_URL)
    except Exception:
        return DEFAULT_DPOINT_POINTS_CSV_URL


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


# -----------------------------
# データ取得
# -----------------------------
@st.cache_data(ttl=60 * 60 * 6)
def load_data():
    df = yf.download(DISPLAY_ITEMS, period="2y", auto_adjust=True, progress=False)["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame()
    return df


@st.cache_data(ttl=60 * 5)
def load_dpoint_points_from_sheet(url):
    df = pd.read_csv(url, header=None)

    # 2行目の A〜K 列（11セル）を読む
    values = df.iloc[1, 0:len(POINT_ORDER)].tolist()

    points_map = {}
    for ticker, value in zip(POINT_ORDER, values):
        if ticker is None:
            continue
        try:
            text = str(value).replace(",", "").strip()
            points_map[ticker] = int(float(text))
        except Exception:
            points_map[ticker] = 0

    return points_map


def get_price_series(ticker, raw, fx, currency):
    if ticker not in raw.columns:
        return None, None

    series = raw[ticker].dropna()
    if series.empty:
        return None, None

    if ticker == FX_TICKER:
        return series, "JPY"

    if currency == "JPY" and not fx.empty:
        fx_aligned = fx.reindex(series.index).ffill().bfill()
        return series * fx_aligned, "JPY"

    return series, "USD"


def etf_trading_index(raw):
    """ETFが実際に取引された日だけのインデックス（ドル円だけの日を除く）"""
    cols = [t for t in TARGET_ETFS if t in raw.columns]
    if not cols:
        return raw.index
    return raw[cols].dropna(how="all").index


def calc_next_update_predictions(raw, prev_ttm, current_fx, points_map, base_date):
    rows = []

    for ticker in TARGET_ETFS:
        if ticker not in raw.columns:
            continue

        series = raw[ticker].dropna()
        if len(series) < 2:
            continue

        # 前回基準日以前の最新終値を「前回値」として使う
        # GW・年末年始・日本祝日明け対策
        base_series = series[series.index.date <= base_date]
        if base_series.empty:
            continue

        prev_usd = base_series.iloc[-1]
        current_usd = series.iloc[-1]

        prev_jpy = prev_usd * prev_ttm
        current_jpy = current_usd * current_fx

        pred_pct = (current_jpy / prev_jpy - 1) * 100
        points = points_map.get(ticker, 0)
        pred_pt = points * pred_pct / 100

        rows.append(
            {
                "ticker": ticker,
                "テーマ": DISPLAY_LABELS.get(ticker, ticker),
                "予測騰落率": pred_pct,
                "投入pt": points,
                "予測変動pt": pred_pt,
                "予測更新後pt": points + pred_pt,
                "ETF現在値": current_usd,
                "ETF前回値": prev_usd,
                "ETF変動": (current_usd / prev_usd - 1) * 100,
                "前回基準日": base_series.index[-1].date(),
            }
        )

    return rows


# -----------------------------
# 表示用データの準備
# -----------------------------
try:
    raw = load_data()
except Exception:
    st.error("価格データの取得に失敗しました。少し時間をおいて「🔄 データ更新」を押してください。")
    st.stop()

if raw.empty:
    st.error("価格データが空でした。少し時間をおいて「🔄 データ更新」を押してください。")
    st.stop()

fx = raw[FX_TICKER].dropna() if FX_TICKER in raw.columns else pd.Series(dtype=float)
current_fx = float(fx.iloc[-1]) if not fx.empty else None

items = []
for ticker in DISPLAY_ITEMS:
    price, cur = get_price_series(ticker, raw, fx, currency)
    if price is None:
        continue

    df = slice_period(pd.DataFrame({"Close": price}), period)
    if df.empty:
        continue

    items.append(
        {
            "ticker": ticker,
            "label": DISPLAY_LABELS.get(ticker, ticker),
            "close": df["Close"],   # 表示期間
            "full": price,          # 全期間（指標計算用）
            "cur": cur,
            "perf": calc_perf(df["Close"])[0],
        }
    )

if sort_mode == "騰落率順":
    items.sort(
        key=lambda x: x["perf"] if x["perf"] is not None else -9999,
        reverse=True,
    )


# -----------------------------
# 3×3 Price / 3×3 MACD+RSI
# -----------------------------
if view_mode in ["3×3 Price", "3×3 MACD+RSI"]:
    cols = st.columns(3)

    for i, item in enumerate(items):
        with cols[i % 3]:
            render_title(
                item["ticker"], item["label"], item["close"],
                color=THEME_COLORS.get(item["ticker"], "#999999"),
            )
            if view_mode == "3×3 Price":
                show_chart(make_price_chart(item["close"], item["cur"]))
            else:
                show_chart(make_macd_rsi_chart(item["full"], item["close"].index))


# -----------------------------
# 翌日更新予測
# -----------------------------
elif view_mode == "翌日更新予測":
    st.markdown("### 翌日夕方更新予測")

    if current_fx is None:
        st.error("USDJPY=X を取得できませんでした。")
        st.stop()

    # 既定の前回基準日 = ETFの「前営業日」
    # （ドル円だけ当日の行があっても影響されないよう、ETFの取引日で判定）
    etf_idx = etf_trading_index(raw)
    default_base_date = (etf_idx[-2] if len(etf_idx) >= 2 else etf_idx[-1]).date()

    # 表示切替をまたいで入力値を保持するため、ウィジェットとは別のキーに保存する
    # 日付が変わったら前回基準日の既定値も追従させる（同じ日の間は手動入力を保持）
    if st.session_state.get("base_date_default") != default_base_date:
        st.session_state["base_date_default"] = default_base_date
        st.session_state["base_date"] = default_base_date

    st.session_state.setdefault("prev_ttm", float(round(current_fx, 2)))
    st.session_state.setdefault("current_fx_used", float(round(current_fx, 2)))

    c1, c2, c3 = st.columns(3)

    with c1:
        prev_ttm = st.number_input(
            "前回仲値（USD/JPY）",
            min_value=0.0,
            value=st.session_state["prev_ttm"],
            step=0.01,
            format="%.2f",
        )
        st.session_state["prev_ttm"] = prev_ttm

    with c2:
        use_api_fx = st.checkbox("現在ドル円にAPI値を使う", value=True)

        if use_api_fx:
            current_fx_used = float(round(current_fx, 2))
            st.metric("現在ドル円（使用値）", f"{current_fx_used:.2f}")
        else:
            current_fx_used = st.number_input(
                "現在ドル円（使用値）",
                min_value=0.0,
                value=st.session_state["current_fx_used"],
                step=0.01,
                format="%.2f",
            )
            st.session_state["current_fx_used"] = current_fx_used

        st.caption(f"API値: {current_fx:.2f}")

    with c3:
        base_date = st.date_input(
            "前回基準日",
            value=st.session_state["base_date"],
            help="通常日は前営業日、GW・年末年始・祝日明けはdポイント投資の前回更新に使われた基準日を選びます。",
        )
        st.session_state["base_date"] = base_date

    if prev_ttm <= 0 or current_fx_used <= 0:
        st.warning("ドル円には 0 より大きい値を入力してください。")
        st.stop()

    if st.button("投入pt更新"):
        load_dpoint_points_from_sheet.clear()
        st.rerun()

    try:
        points_map = load_dpoint_points_from_sheet(get_points_csv_url())
    except Exception:
        st.error("投入ptのGoogleスプレッドシート読込に失敗しました。シートの共有設定（リンクを知っている全員が閲覧可）を確認してください。")
        st.stop()

    pred_rows = calc_next_update_predictions(
        raw=raw,
        prev_ttm=prev_ttm,
        current_fx=current_fx_used,
        points_map=points_map,
        base_date=base_date,
    )
    pred_map = {row["ticker"]: row for row in pred_rows}

    total_points = sum(r["投入pt"] for r in pred_rows)
    total_change = sum(r["予測変動pt"] for r in pred_rows)
    total_pct = total_change / total_points * 100 if total_points else 0

    # 上部サマリー
    m1, m2, m3 = st.columns(3)
    m1.metric("投入pt 合計", f"{total_points:,.0f} pt")
    m2.metric("予想損益", f"{total_change:+,.0f} pt", f"{total_pct:+.2f}%")
    m3.metric("予想更新後", f"{total_points + total_change:,.0f} pt")

    st.caption(
        f"前回基準日: {base_date} ／ 現在ドル円使用値: {current_fx_used:.2f}（API値: {current_fx:.2f}）"
    )

    # Excel「ETF値」タブ貼り付け用：現在値（タブ区切り）
    copy_values = []
    for ticker in PREDICTION_ORDER:
        if ticker == FX_TICKER:
            copy_values.append(f"{current_fx_used:.2f}")
        elif ticker in raw.columns and not raw[ticker].dropna().empty:
            copy_values.append(f"{raw[ticker].dropna().iloc[-1]:.2f}")
        else:
            copy_values.append("")
    copy_text = "\t".join(copy_values)

    # テーブル行
    rows_html = ""
    row_count = 0

    fx_change = (current_fx_used / prev_ttm - 1) * 100
    rows_html += f"""
<tr>
    <td class="first center" style="background-color:{THEME_COLORS[FX_TICKER]};">ドル円</td>
    <td></td>
    <td>{prev_ttm:,.2f}</td>
    <td>{current_fx_used:,.2f}</td>
    <td class="{sign_class(fx_change)}">{fx_change:+.2f}%</td>
    <td></td>
    <td></td>
</tr>
"""
    row_count += 1

    for ticker in PREDICTION_ORDER:
        row = pred_map.get(ticker)
        if row is None:
            continue

        rows_html += f"""
<tr>
    <td class="first center" style="background-color:{THEME_COLORS.get(ticker, '#EEEEEE')};">{html.escape(row["テーマ"])}</td>
    <td>{row['投入pt']:,.0f}</td>
    <td>{row['ETF前回値']:,.2f}</td>
    <td>{row['ETF現在値']:,.2f}</td>
    <td class="{sign_class(row['ETF変動'])}">{row['ETF変動']:+.2f}%</td>
    <td class="{sign_class(row['予測騰落率'])}">{row['予測騰落率']:+.2f}%</td>
    <td class="{sign_class(row['予測変動pt'])}">{row['予測変動pt']:+,.0f}</td>
</tr>
"""
        row_count += 1

    rows_html += f"""
<tr class="total-row">
    <td class="first center">合計</td>
    <td>{total_points:,.0f}</td>
    <td></td>
    <td></td>
    <td></td>
    <td class="{sign_class(total_pct)}">{total_pct:+.2f}%</td>
    <td class="{sign_class(total_change)}">{total_change:+,.0f}</td>
</tr>
"""
    row_count += 1

    # 「現在」ボタンを押すと Excel 貼り付け用の値をコピー
    copy_button = f"""
<button class="copy-btn" title="Excel貼り付け用の現在値をコピー" onclick='
    const text = {json.dumps(copy_text)};
    const btn = this;
    const done = () => {{ btn.textContent = "✓ コピー"; setTimeout(() => btn.textContent = "現在", 1500); }};
    const fallback = () => {{
        const ta = document.createElement("textarea");
        ta.value = text; document.body.appendChild(ta); ta.select();
        try {{ document.execCommand("copy"); done(); }} catch (e) {{ btn.textContent = "コピー失敗"; }}
        document.body.removeChild(ta);
    }};
    if (navigator.clipboard) {{ navigator.clipboard.writeText(text).then(done).catch(fallback); }} else {{ fallback(); }}
'>現在</button>
"""

    header_html = (
        "<th>テーマ</th><th>投入pt</th><th>昨日</th>"
        f"<th>{copy_button}</th>"
        "<th>変動</th><th>dポ投資</th><th>予想損益</th>"
    )

    render_html_table(header_html, rows_html, min_width=860, rows_count=row_count)


# -----------------------------
# Card Detail
# -----------------------------
elif view_mode == "Card Detail":
    for item in items:
        ticker = item["ticker"]
        close = item["close"]
        cur = item["cur"]

        render_title(ticker, item["label"], close, color=THEME_COLORS.get(ticker, "#999999"))

        perf, day_perf = calc_perf(close)

        c1, c2, c3 = st.columns(3)
        c1.metric("現在値", f"{close.iloc[-1]:,.2f} {cur}")
        c2.metric("期間騰落率", f"{perf:+.2f}%" if perf is not None else "-")
        c3.metric("前日比", f"{day_perf:+.2f}%" if day_perf is not None else "-")

        show_chart(make_price_chart(close, cur))

        if ticker != FX_TICKER:
            show_chart(make_macd_rsi_chart(item["full"], close.index))

        st.markdown("---")
