# app.py
import html
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from core import (
    DPOINT_UPDATE_HOUR,
    ETF_INFO,
    RECORD_LABELS,
    RECORD_ORDER,
    build_record_row,
    daily_change,
    parse_record,
    period_profit,
    principal_flows,
    calc_perf,
    default_base_date as calc_default_base_date,
    download_close,
    download_intraday,
    estimate_ttm,
    is_ttm_fixed,
    next_dpoint_update_date,
    slice_period,
    summarize_indicators,
    us_market_status,
)
from ui import (
    copy_button_js,
    make_cumulative_chart,
    make_multi_line_chart,
    make_profit_bar_chart,
    make_allocation_pie,
    make_macd_rsi_chart,
    make_price_chart,
    render_copy_button,
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

# 記録シートのテーマ名 → 色（ETF以外のテーマも含む）
LABEL_COLORS = {
    label: THEME_COLORS.get(key, {"N225": "#f4b183", "N225INV": "#d9d9d9", "OMAKASE": "#ffe699"}.get(key, "#EEEEEE"))
    for key, label in RECORD_ORDER
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


def get_secret(key, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


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
        ["3×3 Price", "3×3 MACD+RSI", "翌日更新予測", "結果の取り込み", "損益の推移", "Card Detail"],
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
@st.cache_data(ttl=60 * 15, show_spinner="株価データを取得中…")
def load_data():
    return download_close(DISPLAY_ITEMS)


@st.cache_data(ttl=60 * 15)
def load_fx_intraday():
    return download_intraday(FX_TICKER)


@st.cache_data(ttl=60 * 5)
def load_record_sheet(url):
    """記録シート（日付＋残高11＋損益11）をCSVで読む"""
    return parse_record(pd.read_csv(url, dtype=str))


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
    raw, missing = load_data()
except Exception:
    st.error("価格データの取得に失敗しました。少し時間をおいて「🔄 データ更新」を押してください。")
    st.stop()

if missing:
    names = "、".join(f"{DISPLAY_LABELS.get(t, t)}（{t}）" for t in missing)
    st.warning(
        f"⚠️ 株価を取得できなかった銘柄があります: {names}　"
        "次の操作時に自動で再取得します。"
    )
    # 取りこぼした結果を6時間キャッシュし続けないよう、次回は取り直す
    load_data.clear()

if raw.empty:
    st.stop()

WD = "月火水木金土日"

fx = raw[FX_TICKER].dropna() if FX_TICKER in raw.columns else pd.Series(dtype=float)
fx_intraday = load_fx_intraday()

# 現在のドル円：30分足があればそちらの最新値（日足より新しい）
if not fx_intraday.empty:
    current_fx, fx_time = float(fx_intraday.iloc[-1]), fx_intraday.index[-1]
elif not fx.empty:
    current_fx, fx_time = float(fx.iloc[-1]), None
else:
    current_fx, fx_time = None, None

now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
etf_idx = etf_trading_index(raw)
last_etf_date = etf_idx[-1].date()
market_state, ny_now = us_market_status(last_etf_date, now_jst)

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

RECORD_CSV_URL = get_secret("RECORD_CSV_URL")
record, record_error = None, None
if RECORD_CSV_URL:
    try:
        record = load_record_sheet(RECORD_CSV_URL)
    except Exception as e:
        record_error = str(e)

points_source = ""
if record is not None and not record[0].empty:
    # 記録シートの最新行の残高を投入ptとして使う
    latest = record[0].iloc[-1]
    points_map = {key: int(latest[label]) for key, label in RECORD_ORDER if key in TARGET_ETFS}
    points_error = False
    points_source = f"記録シート {record[0].index[-1]:%m/%d} の残高"
else:
    try:
        points_map = load_dpoint_points_from_sheet(get_points_csv_url())
        points_error = False
        points_source = "投入ptシート"
    except Exception:
        points_map, points_error = {}, True


# -----------------------------
# データ時刻の表示（全ページ共通）
# -----------------------------
if market_state == "trading":
    etf_status = (
        f"ETF価格: {last_etf_date:%m/%d}（{WD[last_etf_date.weekday()]}）"
        f"🟢 取引中・途中経過（ニューヨーク {ny_now:%H:%M}）"
    )
else:
    etf_status = f"ETF価格: {last_etf_date:%m/%d}（{WD[last_etf_date.weekday()]}）終値"

fx_status = f"ドル円: {fx_time:%m/%d %H:%M} 時点" if fx_time is not None else "ドル円: 日足終値"
st.caption(f"{etf_status} ／ {fx_status} ／ 表示: {now_jst:%m/%d %H:%M}")


# -----------------------------
# サイドバー：AI分析用コピー
# -----------------------------
def build_ai_prompt():
    basis = "円建て（為替の影響込み）" if currency == "JPY" else "ドル建て"
    state = "途中経過（米国市場取引中）" if market_state == "trading" else "終値"
    total_pt = sum(points_map.get(t, 0) for t in TARGET_ETFS)

    lines = [
        "以下は「dポイント投資（テーマ運用）」の各テーマに連動する米国ETFの指標です。",
        f"基準: {last_etf_date:%Y/%m/%d} の{state} ／ 期間: {period} ／ {basis}",
        "各テーマについて、直近の傾向を1〜2文で簡潔にまとめ、最後に全体の所感を一言ください。",
        "（売買の推奨ではなく、指標の読み取りとしてお願いします）",
        "",
        "テーマ(ティッカー): 期間騰落率 / 前日比 / RSI(14) / MACDとシグナル / 25日線乖離 / 投入pt(構成比)",
    ]

    for item in items:
        t = item["ticker"]
        if t == FX_TICKER:
            continue
        ind = summarize_indicators(item["full"], item["close"])

        def pct(v):
            return f"{v:+.1f}%" if v is not None else "-"

        macd_text = "-"
        if ind["macd_state"]:
            macd_text = f"MACD{'>' if ind['macd_state'] == '上' else '<'}シグナル"
            if ind["cross_days"] is not None and ind["cross_days"] <= 10:
                cross = "上抜け" if ind["macd_state"] == "上" else "下抜け"
                macd_text += f"（{ind['cross_days']}営業日前に{cross}）" if ind["cross_days"] else f"（本日{cross}）"

        pt = points_map.get(t)
        pt_text = f"{pt:,}pt ({pt / total_pt * 100:.1f}%)" if pt is not None and total_pt else "-"
        rsi_text = f"RSI {ind['rsi']:.0f}" if ind["rsi"] is not None else "RSI -"

        lines.append(
            f"- {item['label']}({t}): {pct(ind['perf'])} / {pct(ind['day_perf'])} / {rsi_text} / "
            f"{macd_text} / {pct(ind['ma25_gap'])} / {pt_text}"
        )

    fx_item = next((it for it in items if it["ticker"] == FX_TICKER), None)
    if fx_item is not None:
        perf, day_perf = calc_perf(fx_item["close"])
        lines.append("")
        lines.append(
            f"ドル円: {current_fx:.2f} / 期間 {perf:+.1f}% / 前日比 {day_perf:+.1f}%"
            if perf is not None and day_perf is not None and current_fx
            else "ドル円: -"
        )

    return "\n".join(lines)


with st.sidebar:
    st.markdown("---")
    st.markdown("**🤖 AI分析用**")
    ai_prompt = build_ai_prompt()
    render_copy_button(ai_prompt, label="📋 指標をコピー")
    st.caption("ChatGPT や Claude に貼り付けて使えます（期間・建値の設定が反映されます）")
    with st.expander("コピー内容を確認"):
        st.code(ai_prompt, language=None)


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

    # 既定の前回基準日 = 直近のdポイント更新に使われたETF終値の日付
    # （日本時間の現在時刻・土日祝から「直近の更新日」を割り出して決める）
    default_base_date, last_update = calc_default_base_date(etf_idx, now_jst)
    next_update = next_dpoint_update_date(last_update)

    # 前回仲値（推定）＝直近更新日の 9:55 ごろのレート
    prev_ttm_est, prev_ttm_time = estimate_ttm(fx_intraday, last_update)
    default_prev_ttm = float(round(prev_ttm_est if prev_ttm_est else current_fx, 2))

    # 次回更新の仲値がもう決まっていれば（当日10時以降）、それを使う。まだなら現在レート
    next_ttm_est, next_ttm_time = (None, None)
    if is_ttm_fixed(now_jst, next_update):
        next_ttm_est, next_ttm_time = estimate_ttm(fx_intraday, next_update)

    if next_ttm_est:
        auto_fx = float(round(next_ttm_est, 2))
        auto_fx_label = f"{next_update:%m/%d}（{WD[next_update.weekday()]}）仲値・推定"
    else:
        auto_fx = float(round(current_fx, 2))
        auto_fx_label = "現在レート"

    # 表示切替をまたいで入力値を保持するため、ウィジェットとは別のキーに保存する
    # 直近の更新日が変わったら既定値も追従させる（同じ間は手動入力を保持）
    if st.session_state.get("defaults_for") != (last_update, default_prev_ttm):
        st.session_state["defaults_for"] = (last_update, default_prev_ttm)
        st.session_state["base_date"] = default_base_date
        st.session_state["prev_ttm"] = default_prev_ttm

    st.session_state.setdefault("current_fx_used", auto_fx)

    c1, c2, c3 = st.columns(3)

    with c1:
        prev_ttm = st.number_input(
            "前回仲値（USD/JPY）",
            min_value=0.0,
            value=st.session_state["prev_ttm"],
            step=0.01,
            format="%.2f",
            help="直近の更新日の 9:55 ごろのドル円（30分足）から自動で入ります。正式な仲値とは数銭ずれることがあります。",
        )
        st.session_state["prev_ttm"] = prev_ttm
        if prev_ttm_est:
            st.caption(f"自動値: {prev_ttm_est:.2f}（{prev_ttm_time:%m/%d %H:%M} 足から推定）")
        else:
            st.caption("自動推定できなかったため、現在レートを仮に入れています。")

    with c2:
        use_api_fx = st.checkbox("現在ドル円に自動値を使う", value=True)

        if use_api_fx:
            current_fx_used = auto_fx
            st.metric(f"現在ドル円（{auto_fx_label}）", f"{current_fx_used:.2f}")
        else:
            current_fx_used = st.number_input(
                "現在ドル円（使用値）",
                min_value=0.0,
                value=st.session_state["current_fx_used"],
                step=0.01,
                format="%.2f",
            )
            st.session_state["current_fx_used"] = current_fx_used

        st.caption(f"現在レート: {current_fx:.2f}")

    with c3:
        base_date = st.date_input(
            "前回基準日",
            value=st.session_state["base_date"],
            help=f"直近のdポイント更新（{DPOINT_UPDATE_HOUR}時更新とみなす）に使われた米国ETF終値の日付が自動で入ります。ずれている場合は手動で変更してください。",
        )
        st.session_state["base_date"] = base_date
        st.caption(
            f"直近の更新: {last_update:%m/%d}（{WD[last_update.weekday()]}）夕方 → "
            f"{default_base_date:%m/%d}（{WD[default_base_date.weekday()]}）終値ベース"
        )

    if prev_ttm <= 0 or current_fx_used <= 0:
        st.warning("ドル円には 0 より大きい値を入力してください。")
        st.stop()

    if st.button("投入pt更新"):
        load_dpoint_points_from_sheet.clear()
        st.rerun()

    if points_error:
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

    # 株価を取れなかったテーマも投入ptは合計に含める（予想損益は計算できた分のみ）
    failed = [t for t in TARGET_ETFS if t not in pred_map]
    total_points = sum(points_map.get(t, 0) for t in TARGET_ETFS)
    known_points = sum(r["投入pt"] for r in pred_rows)
    total_change = sum(r["予測変動pt"] for r in pred_rows)
    total_pct = total_change / known_points * 100 if known_points else 0

    st.caption(
        f"前回基準日: {base_date} ／ 前回仲値: {prev_ttm:.2f} ／ 現在ドル円使用値: {current_fx_used:.2f}"
    )
    if points_source:
        st.caption(f"投入pt: {points_source}")
    if failed:
        st.caption(
            "※ " + "、".join(DISPLAY_LABELS.get(t, t) for t in failed)
            + " は株価を取得できなかったため、予想損益に含まれていません。"
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
        if ticker == FX_TICKER:
            continue

        row = pred_map.get(ticker)
        if row is None:
            # 取得失敗のテーマも行は残す（見えなくならないように）
            rows_html += f"""
<tr>
    <td class="first center" style="background-color:{THEME_COLORS.get(ticker, '#EEEEEE')};">{html.escape(DISPLAY_LABELS.get(ticker, ticker))}</td>
    <td>{points_map.get(ticker, 0):,.0f}</td>
    <td colspan="5" style="text-align:center; color:#999 !important;">取得失敗</td>
</tr>
"""
            row_count += 1
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
    copy_js = html.escape(copy_button_js(copy_text, "現在"), quote=True)
    copy_button = f'<button class="copy-btn" title="Excel貼り付け用の現在値をコピー" onclick="{copy_js}">現在</button>'

    header_html = (
        "<th>テーマ</th><th>投入pt</th><th>昨日</th>"
        f"<th>{copy_button}</th>"
        "<th>変動</th><th>dポ投資</th><th>予想損益</th>"
    )

    render_html_table(header_html, rows_html, min_width=860, rows_count=row_count)

    # 投入ptの配分
    alloc = [t for t in PREDICTION_ORDER if t != FX_TICKER and points_map.get(t, 0) > 0]
    if alloc:
        st.markdown("#### 投入ptの配分")
        show_chart(
            make_allocation_pie(
                labels=[DISPLAY_LABELS.get(t, t) for t in alloc],
                values=[points_map[t] for t in alloc],
                colors=[THEME_COLORS.get(t, "#CCCCCC") for t in alloc],
            )
        )
        zero = [DISPLAY_LABELS.get(t, t) for t in TARGET_ETFS if points_map.get(t, 0) <= 0]
        if zero:
            st.caption("投入ptが0のテーマ: " + "、".join(zero))


# -----------------------------
# 結果の取り込み（Excel記録用の1行を作る）
# -----------------------------
elif view_mode == "結果の取り込み":
    _, last_update = calc_default_base_date(etf_idx, now_jst)
    st.markdown(f"### 結果の取り込み（{last_update:%m/%d}（{WD[last_update.weekday()]}）更新分）")
    st.caption(
        "dポイント運用の各ページで該当部分を選択してコピーし、下の欄に貼り付けてください。"
        "ページ全体（Ctrl+A）をコピーしても大丈夫です。"
    )

    c1, c2 = st.columns(2)
    with c1:
        theme_text = st.text_area(
            "① ホーム画面の「テーマ」（各テーマの残高）",
            height=260,
            key="record_theme_text",
            placeholder="おまかせ\nアクティブ\n265,897P\n+8,399P\n金（ゴールド）\n90,097P\n...",
        )
    with c2:
        total_text = st.text_area(
            "② 「これまでの合計損益」ページ",
            height=260,
            key="record_total_text",
            placeholder="これまでの合計損益\n↑ 385,003P\nおまかせ\n↑147,366P\n...",
        )

    def clear_record_inputs():
        st.session_state["record_theme_text"] = ""
        st.session_state["record_total_text"] = ""

    st.button("🗑 入力欄をクリア", on_click=clear_record_inputs)

    if theme_text.strip() or total_text.strip():
        row_text, details, check = build_record_row(theme_text, total_text)

        missing_bal = [d["label"] for d in details if d["残高"] is None]
        missing_prof = [d["label"] for d in details if d["通算損益"] is None]

        # 読み取りチェック
        if missing_bal and theme_text.strip():
            st.warning("① で読み取れなかったテーマ: " + "、".join(missing_bal))
        if missing_prof and total_text.strip():
            st.warning("② で読み取れなかったテーマ: " + "、".join(missing_prof))
        for name, (calc, page) in check.items():
            if calc == page:
                st.success(f"✓ {name}: 各テーマの合計 {calc:,} pt がページの表示と一致")
            else:
                st.error(f"✗ {name}: 各テーマの合計 {calc:,} pt ≠ ページの表示 {page:,} pt（読み取りを確認してください）")

        # 明細テーブル
        def fmt(v, signed=False):
            if v is None:
                return '<span style="color:#bbb !important;">—</span>'
            return f"{v:+,}" if signed else f"{v:,}"

        rows_html = ""
        for d in details:
            color = THEME_COLORS.get(d["key"], "#EEEEEE")
            rows_html += f"""
<tr>
    <td class="first center" style="background-color:{color};">{html.escape(d["label"])}</td>
    <td>{fmt(d["残高"])}</td>
    <td class="{sign_class(d["通算損益"]) if d["通算損益"] is not None else ""}">{fmt(d["通算損益"], signed=True)}</td>
</tr>
"""
        sum_bal = sum(d["残高"] or 0 for d in details)
        sum_prof = sum(d["通算損益"] or 0 for d in details)
        rows_html += f"""
<tr class="total-row">
    <td class="first center">合計</td>
    <td>{sum_bal:,}</td>
    <td class="{sign_class(sum_prof)}">{sum_prof:+,}</td>
</tr>
"""
        header_html = "<th>テーマ</th><th>残高（B〜L列）</th><th>通算損益（M〜W列）</th>"

        st.markdown("#### 記録シート用（日付つき・最終行の下に貼る）")
        render_copy_button(f"{last_update:%Y/%m/%d}\t" + row_text, label="📋 日付つきでコピー（23項目）")

        st.markdown("#### Excel貼り付け用（Sheet1 の B〜W列）")
        render_copy_button(row_text, label="📋 1行分をコピー（22項目・タブ区切り）")
        st.caption(f"Sheet1 の {last_update:%m/%d} の行の B列を選択して貼り付けてください。空欄は読み取れなかった項目です。")

        render_html_table(header_html, rows_html, min_width=480, rows_count=len(details) + 1)


# -----------------------------
# 損益の推移（記録シートから）
# -----------------------------
elif view_mode == "損益の推移":
    st.markdown("### 損益の推移")

    rec = record
    if rec is None:
        if record_error:
            st.error("記録シートを読み込めませんでした。シートの共有設定とURLを確認してください。")
        else:
            st.info(
                "記録シートのURLが未設定です。Streamlit の Secrets に `RECORD_CSV_URL` を設定すると、"
                "ここに自動で表示されます。試しに見るだけなら、下で記録CSVを選んでください。"
            )
        up = st.file_uploader("記録CSV（日付＋残高11＋損益11）", type=["csv"])
        if up is not None:
            try:
                rec = parse_record(pd.read_csv(up, dtype=str, encoding="utf-8-sig"))
            except Exception:
                st.error("CSVを読み込めませんでした。1行目が見出しになっているか確認してください。")
                st.stop()
        else:
            st.stop()

    bal, pl = rec
    if len(pl) < 2:
        st.warning("記録が2日分以上必要です。")
        st.stop()

    total = pl.sum(axis=1)
    monthly = period_profit(total, "M")
    yearly = period_profit(total, "Y")
    d_pt, d_pct = daily_change(bal, pl)
    last_day = pl.index[-1]

    # サマリー
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("通算損益", f"{total.iloc[-1]:+,.0f} pt")
    m2.metric(f"{last_day:%Y}年", f"{yearly.iloc[-1]:+,.0f} pt")
    m3.metric(f"{last_day:%m}月", f"{monthly.iloc[-1]:+,.0f} pt")
    m4.metric(f"前日比（{last_day:%m/%d}）", f"{d_pt.iloc[-1].sum():+,.0f} pt")
    st.caption(f"記録: {pl.index[0]:%Y/%m/%d} 〜 {last_day:%Y/%m/%d}（{len(pl):,}日分）")

    def pl_cell(v, fmt="{:+,.0f}"):
        if pd.isna(v):
            return "<td></td>"
        return f'<td class="{sign_class(v)}">{fmt.format(v)}</td>'

    def theme_header(first):
        cells = f"<th>{first}</th>"
        for label in RECORD_LABELS:
            cells += f'<th style="background-color:{LABEL_COLORS[label]};">{html.escape(label)}</th>'
        return cells + "<th>合計</th>"

    # 切り替えても各設定（単位・日数・月数・年）を保持する
    for k in ["hist_unit", "hist_days", "hist_months", "hist_year", "hist_cum_period", "hist_cum_zero",
              "hist_cum_mode", "hist_cum_themes", "hist_flow_theme", "hist_flow_n"]:
        if k in st.session_state:
            st.session_state[k] = st.session_state[k]
    st.session_state.setdefault("hist_unit", "pt")
    st.session_state.setdefault("hist_days", 20)

    SECTIONS = ["テーマ別の前日比", "月別損益", "年別損益", "通算の推移", "追加・引出"]
    if hasattr(st, "segmented_control"):
        section = st.segmented_control("表示", SECTIONS, default=SECTIONS[0], key="history_section", label_visibility="collapsed")
    else:
        section = st.radio("表示", SECTIONS, horizontal=True, key="history_section", label_visibility="collapsed")
    section = section or SECTIONS[0]

    if section == "テーマ別の前日比":
        # テーマ別の前日比
        c1, c2 = st.columns([1, 2])
        with c1:
            unit = st.radio("単位", ["pt", "%"], horizontal=True, key="hist_unit")
        with c2:
            n_days = st.select_slider("表示する日数", options=[10, 20, 40, 60, 120], key="hist_days")
        src = d_pt if unit == "pt" else d_pct
        rows_html = ""
        for day, row in src.tail(n_days).iloc[::-1].iterrows():
            rows_html += f'<tr><td class="first center">{day:%Y/%m/%d}（{WD[day.weekday()]}）</td>'
            if unit == "pt":
                rows_html += "".join(pl_cell(row[label]) for label in RECORD_LABELS)
                rows_html += pl_cell(d_pt.loc[day].sum())
            else:
                rows_html += "".join(pl_cell(row[label], "{:+.2f}%") for label in RECORD_LABELS)
                prev_total = bal.shift(1).loc[day].sum()
                rows_html += pl_cell(d_pt.loc[day].sum() / prev_total * 100 if prev_total else float("nan"), "{:+.2f}%")
            rows_html += "</tr>"
        render_html_table(theme_header("日付"), rows_html, min_width=1300, rows_count=n_days)

    elif section == "月別損益":
        # 月別損益
        month_opts = [n for n in [12, 24, 36, 60] if n < len(monthly)] + [len(monthly)]
        if st.session_state.get("hist_months") not in month_opts:
            st.session_state["hist_months"] = 24 if 24 in month_opts else month_opts[-1]
        n_months = st.select_slider(
            "表示する月数",
            options=month_opts,
            key="hist_months",
            format_func=lambda n: "全期間" if n == len(monthly) else f"{n}か月",
        )
        mon = monthly.tail(n_months)
        show_chart(make_profit_bar_chart([f"{p.year}/{p.month:02d}" for p in mon.index], mon.values.tolist()))

        # 選んだ年の月別（テーマ別）
        years = sorted({p.year for p in monthly.index}, reverse=True)
        st.markdown("##### テーマ別の月別損益")
        if st.session_state.get("hist_year") not in years:
            st.session_state["hist_year"] = years[0]
        sel_year = st.selectbox("表示する年", years, key="hist_year")
        month_last = pl.groupby(pl.index.to_period("M")).last()
        month_theme = month_last.diff()
        month_theme.iloc[0] = month_last.iloc[0] - pl.iloc[0]
        month_theme = month_theme[[p.year == sel_year for p in month_theme.index]]
        rows_html = ""
        for per, row in month_theme.iloc[::-1].iterrows():
            rows_html += f'<tr><td class="first center">{per.month}月</td>'
            rows_html += "".join(pl_cell(row[label]) for label in RECORD_LABELS)
            rows_html += pl_cell(row.sum()) + "</tr>"
        if not month_theme.empty:
            year_sum = month_theme.sum()
            rows_html += f'<tr class="total-row"><td class="first center">{sel_year}年 計</td>'
            rows_html += "".join(pl_cell(year_sum[label]) for label in RECORD_LABELS)
            rows_html += pl_cell(year_sum.sum()) + "</tr>"
        render_html_table(theme_header("月"), rows_html, min_width=1200, rows_count=len(month_theme) + 1)


    elif section == "年別損益":
        # 年別（テーマ別）
        show_chart(make_profit_bar_chart([str(p.year) for p in yearly.index], yearly.values.tolist(), height=260))
        yearly_theme = pl.groupby(pl.index.to_period("Y")).last().diff()
        yearly_theme.iloc[0] = pl.groupby(pl.index.to_period("Y")).last().iloc[0] - pl.iloc[0]
        rows_html = ""
        for per, row in yearly_theme.iloc[::-1].iterrows():
            rows_html += f'<tr><td class="first center">{per.year}</td>'
            rows_html += "".join(pl_cell(row[label]) for label in RECORD_LABELS)
            rows_html += pl_cell(row.sum()) + "</tr>"
        render_html_table(theme_header("年"), rows_html, min_width=1200, rows_count=len(yearly_theme))


    elif section == "通算の推移":
        # 期間・起点0・合計/テーマ別
        PERIODS = {"3か月": 91, "6か月": 182, "1年": 365, "3年": 365 * 3, "全期間": None}
        st.session_state.setdefault("hist_cum_period", "1年")
        st.session_state.setdefault("hist_cum_zero", False)
        st.session_state.setdefault("hist_cum_mode", "合計")
        held_now = [label for label in RECORD_LABELS if bal[label].iloc[-1] > 0]
        st.session_state.setdefault("hist_cum_themes", held_now or RECORD_LABELS[:3])

        c1, c2, c3 = st.columns([3, 1.3, 1.3])
        with c1:
            period_key = st.select_slider("期間", options=list(PERIODS), key="hist_cum_period")
        with c2:
            mode = st.radio("表示", ["合計", "テーマ別"], horizontal=True, key="hist_cum_mode")
        with c3:
            zero = st.toggle("期間の初日を0にする", key="hist_cum_zero") if hasattr(st, "toggle") \
                else st.checkbox("期間の初日を0にする", key="hist_cum_zero")

        days = PERIODS[period_key]
        start = pl.index[-1] - pd.Timedelta(days=days) if days else pl.index[0]

        if mode == "合計":
            ser = total[total.index >= start]
            if zero:
                ser = ser - ser.iloc[0]
            show_chart(make_cumulative_chart(ser))
            st.caption(f"{ser.index[0]:%Y/%m/%d} 〜 {ser.index[-1]:%Y/%m/%d}　期間中の増減: {ser.iloc[-1] - ser.iloc[0]:+,.0f} pt")
        else:
            themes = st.multiselect("表示するテーマ", RECORD_LABELS, key="hist_cum_themes")
            if not themes:
                st.info("表示するテーマを選んでください。")
            else:
                df = pl.loc[pl.index >= start, themes]
                if zero:
                    df = df - df.iloc[0]
                show_chart(make_multi_line_chart(df, [LABEL_COLORS[t] for t in themes]))
                change = (df.iloc[-1] - df.iloc[0]).sort_values(ascending=False)
                st.caption(
                    f"{df.index[0]:%Y/%m/%d} 〜 {df.index[-1]:%Y/%m/%d} の増減: "
                    + "　".join(f"{t} {v:+,.0f}" for t, v in change.items())
                )

    elif section == "追加・引出":
        flows = principal_flows(bal, pl)
        st.caption(
            "その日の「残高の増減 − 損益の増減」から、入れた（＋）・出した（−）ptを出しています。"
            "テーマ間の移し替えは、出したテーマが − 、入れたテーマが ＋ になります。"
            "2025/08 より前は残高が推定値のため、多少ずれることがあります。"
        )
        if flows.empty:
            st.info("追加・引出の記録はありません。")
        else:
            st.session_state.setdefault("hist_flow_theme", "すべて")
            st.session_state.setdefault("hist_flow_n", 30)
            c1, c2 = st.columns([1, 2])
            with c1:
                flow_theme = st.selectbox("テーマ", ["すべて"] + RECORD_LABELS, key="hist_flow_theme")
            with c2:
                n_flow = st.select_slider("表示する件数", options=[10, 30, 60, 120, 300], key="hist_flow_n")

            def flow_cell(v):
                if pd.isna(v) or v == 0:
                    return "<td></td>"
                return f"<td>{v:+,.0f}</td>"

            if flow_theme == "すべて":
                part = flows.tail(n_flow).iloc[::-1]
                rows_html = ""
                for day, row in part.iterrows():
                    rows_html += f'<tr><td class="first center">{day:%Y/%m/%d}（{WD[day.weekday()]}）</td>'
                    rows_html += "".join(flow_cell(row[label]) for label in RECORD_LABELS)
                    rows_html += flow_cell(row.sum()) + "</tr>"
                header = theme_header("日付").replace("<th>合計</th>", "<th>純額</th>")
                render_html_table(header, rows_html, min_width=1300, rows_count=len(part))
            else:
                one = flows[flow_theme]
                one = one[one != 0]
                part = one.tail(n_flow).iloc[::-1]
                rows_html = ""
                for day, v in part.items():
                    kind = "追加" if v > 0 else "引出"
                    rows_html += (
                        f'<tr><td class="first center">{day:%Y/%m/%d}（{WD[day.weekday()]}）</td>'
                        f"<td>{kind}</td><td>{v:+,.0f}</td><td>{bal.loc[day, flow_theme]:,.0f}</td></tr>"
                    )
                header = "<th>日付</th><th>種類</th><th>pt</th><th>その日の残高</th>"
                st.caption(
                    f"{flow_theme}: 追加 {int((one > 0).sum())}回（計 {one[one > 0].sum():+,.0f}）／"
                    f"引出 {int((one < 0).sum())}回（計 {one[one < 0].sum():+,.0f}）"
                )
                render_html_table(header, rows_html, min_width=520, rows_count=len(part))



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
