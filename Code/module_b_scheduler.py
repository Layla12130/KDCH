# -*- coding: utf-8 -*-
"""
Module B - Day-level Heuristic Scheduler (修正版：
1) 修复 cum_ring_need 未初始化
2) 当天配件需求按当日投产量严谨汇总
3) 保持 first_start_date 导出
)
"""

import pandas as pd
import numpy as np

CONFIG = {
    "gt150_units": 8,
    "gt130_units": 4,
    "sk750_units": 2,  # 2 台配件机
    "gt150_daily": {"GT150": 4800, "GT130on150": 3000},
    "gt130_daily": 3000,
    "gt130_adapter_slots_on_150": 2,  # 适配位数（如果你用它的话）
    "sk750_daily": {"stand": 2000, "ring": 4000},
}

OUT_CFG = {
    "outsourcing_daily_cap": float("inf"),
    "outsourcing_lead_days": 0,
}

def schedule_day_level(ord_df: pd.DataFrame):
    # —— 准备订单表 —— #
    df = ord_df.reset_index(drop=True).copy()
    if "order_id" not in df.columns:
        df["order_id"] = np.arange(len(df)).astype(int)
    df["remain"] = df["qty"].astype(float)

    start_date = pd.to_datetime(df["earliest_start_date"]).min()
    end_date   = pd.to_datetime(df["latest_finish_date"]).max()
    days = pd.date_range(start_date, end_date, freq="D")

    # —— 配件累计：需求 与 产出 —— #
    cum_ring_need  = 0.0
    cum_stand_need = 0.0
    cum_ring_prod  = 0.0
    cum_stand_prod = 0.0
    acc_rows = []  # 配件日生产记录

    alloc_rows = []  # 壳体日排程记录（GT150/GT130/GT130on150）

    for day in days:
        # 当日壳体产能
        cap_gt150_native = CONFIG["gt150_units"] * CONFIG["gt150_daily"]["GT150"]
        cap_gt150_adapt  = CONFIG["gt150_units"] * CONFIG["gt150_daily"]["GT130on150"]
        cap_gt130_native = CONFIG["gt130_units"] * CONFIG["gt130_daily"]

        # 当日可投订单（在窗口内且未完）
        today_mask = (
            (pd.to_datetime(df["earliest_start_date"]) <= day)
            & (pd.to_datetime(df["latest_finish_date"]) >= day)
            & (df["remain"] > 1e-9)
        )
        todays = df.loc[today_mask].sort_values(["latest_finish_date", "due_date"]).index

        # —— 先做壳体投产（GT150 专用，GT130 原生，GT130 on GT150） —— #
        for o in todays:
            need = float(df.at[o, "remain"])
            if need <= 1e-9:
                continue
            mold = str(df.at[o, "mold_machine"] or "")

            put150 = put130 = put150a = 0.0
            if "150" in mold:  # 只能上 GT150
                take = min(need, cap_gt150_native)
                put150 = take
                cap_gt150_native -= take
            else:              # 130 模具：优先 GT130，再用 GT150 适配
                if cap_gt130_native > 0:
                    take = min(need, cap_gt130_native)
                    put130 = take
                    cap_gt130_native -= take
                    need -= take
                if need > 1e-9 and cap_gt150_adapt > 0:
                    take = min(need, cap_gt150_adapt)
                    put150a = take
                    cap_gt150_adapt -= take

            take_all = put150 + put130 + put150a
            if take_all > 1e-9:
                df.at[o, "remain"] -= take_all
                alloc_rows.append({
                    "date": day.date(),
                    "order_idx": int(df.at[o, "order_id"]),
                    "x150": float(put150),
                    "x130": float(put130),
                    "x150_adapter": float(put150a),
                })

        # —— 以“当日壳体投产量”→推导“当日配件需求” —— #
        # 仅统计“当日”的分配行
        day_rows = [r for r in alloc_rows if r["date"] == day.date()]
        today_alloc = pd.DataFrame(day_rows) if day_rows else pd.DataFrame(
            columns=["date", "order_idx", "x150", "x130", "x150_adapter"]
        )

        today_ring_need = 0.0
        today_stand_need = 0.0
        if not today_alloc.empty:
            # 对每个订单，汇总当日壳体产量
            qty_by_order = (
                today_alloc.assign(qty=lambda x: x[["x150", "x130", "x150_adapter"]].sum(axis=1))
                           .groupby("order_idx")["qty"].sum()
            )
            # 根据订单属性 need_ring / need_stand 计算配件需求
            need_ring_flag  = df.set_index("order_id").get("need_ring", pd.Series(False, index=df["order_id"]))
            need_stand_flag = df.set_index("order_id").get("need_stand", pd.Series(False, index=df["order_id"]))
            for oid, qty_shell in qty_by_order.items():
                if bool(need_ring_flag.get(oid, False)):
                    today_ring_need  += float(qty_shell)
                if bool(need_stand_flag.get(oid, False)):
                    today_stand_need += float(qty_shell)

        # 累计需求
        cum_ring_need  += today_ring_need
        cum_stand_need += today_stand_need

        # —— 当天配件产出（按缺口与产能） —— #
        need_ring_gap  = max(0.0, cum_ring_need  - cum_ring_prod)
        need_stand_gap = max(0.0, cum_stand_need - cum_stand_prod)

        max_stand_today = CONFIG["sk750_units"] * CONFIG["sk750_daily"]["stand"]
        max_ring_today  = CONFIG["sk750_units"] * CONFIG["sk750_daily"]["ring"]

        # 先尽量生产 stand，再用剩余“机台折算槽位”生产 ring
        stand_make = min(need_stand_gap, max_stand_today)
        used_slots = stand_make / CONFIG["sk750_daily"]["stand"] if CONFIG["sk750_daily"]["stand"] > 0 else 0.0
        ring_cap_left = max(0.0, CONFIG["sk750_units"] - used_slots) * CONFIG["sk750_daily"]["ring"]
        ring_make = min(need_ring_gap, ring_cap_left, max_ring_today)

        cum_stand_prod += stand_make
        cum_ring_prod  += ring_make

        acc_rows.append({
            "date": day.date(),
            "ring_need_cum": cum_ring_need,
            "stand_need_cum": cum_stand_need,
            "ring_prod_cum": cum_ring_prod,
            "stand_prod_cum": cum_stand_prod,
            "ring_prod_today": ring_make,
            "stand_prod_today": stand_make,
        })

    # —— 外协兜底 —— #
    df["outsourced_units"] = 0.0
    df["lateness_units"] = 0.0
    for o in df.index:
        remain = float(df.at[o, "remain"] or 0.0)
        if remain <= 1e-9:
            continue
        start = pd.to_datetime(df.at[o, "earliest_start_date"]) + pd.Timedelta(days=OUT_CFG["outsourcing_lead_days"])
        end   = pd.to_datetime(df.at[o, "latest_finish_date"])
        if end < start:
            cap = 0.0
        else:
            days_cnt = (end - start).days + 1
            cap = days_cnt * OUT_CFG["outsourcing_daily_cap"]
        outsourced = min(remain, cap)
        lateness   = max(0.0, remain - outsourced)
        df.at[o, "outsourced_units"] = outsourced
        df.at[o, "lateness_units"]   = lateness

    alloc_df = pd.DataFrame(alloc_rows)

    # —— 完工日期（内部达成日）与上线时间 —— #
    comp_rows = []
    for o in df.index:
        oid = int(df.at[o, "order_id"])
        qty = float(df.at[o, "qty"])
        outsourced = float(df.at[o, "outsourced_units"])
        need_internal = qty - outsourced

        o_hist = alloc_df[alloc_df["order_idx"] == oid].sort_values("date")
        done_date = None
        if not o_hist.empty:
            cum = (o_hist[["x150", "x130", "x150_adapter"]].sum(axis=1)).cumsum()
            for dt, val in zip(o_hist["date"], cum):
                if val >= need_internal - 1e-6:
                    done_date = pd.to_datetime(dt)
                    break

        comp_rows.append({
            "order_idx": oid,
            "client": df.at[o, "client_code"],
            "product": df.at[o, "product_code"],
            "qty": qty,
            "due_date": pd.to_datetime(df.at[o, "due_date"]).date(),
            "latest_finish": pd.to_datetime(df.at[o, "latest_finish_date"]).date(),
            "done_date": (done_date.date() if done_date is not None else None),
            "outsourced_units": outsourced,
            "lateness_units": float(df.at[o, "lateness_units"]),
        })

    summary_df = pd.DataFrame(comp_rows)

    # 上线时间（首次开始生产的日期）
    if not alloc_df.empty and not summary_df.empty:
        first_start_map = alloc_df.groupby("order_idx")["date"].min().to_dict()
        summary_df["first_start_date"] = summary_df["order_idx"].map(first_start_map)
        summary_df["first_start_date"] = pd.to_datetime(summary_df["first_start_date"]).dt.date
    else:
        if not summary_df.empty:
            summary_df["first_start_date"] = None

    acc_df = pd.DataFrame(acc_rows)
    return alloc_df, acc_df, summary_df
