def calc_next_update_predictions(raw, prev_ttm, current_fx, points_map, base_date):
    rows = []

    for ticker in TARGET_ETFS:
        if ticker not in raw.columns:
            continue

        series = raw[ticker].dropna()
        if len(series) < 2:
            continue

        # ★ 前回基準日対応
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
