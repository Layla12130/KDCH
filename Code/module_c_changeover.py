# -*- coding: utf-8 -*-
"""
Module C - Machine-level Scheduler with Changeover
修正版（关键修复）：
1) 换模损失通过 LOSS_FACTOR 折减到“日能力”，不再把换模当天产能置 0；
2) 分配表 alloc_df 在空时也输出标准列，避免 KeyError('order_idx')；
3) 继续输出 first_start_date。
"""

import pandas as pd
import numpy as np

CHANGEOVER_HOURS = 5.0
DAY_HOURS = 24.0
LOSS_FACTOR = (DAY_HOURS - CHANGEOVER_HOURS) / DAY_HOURS  # 19/24

CONFIG = {
    "gt150_units": 8,
    "gt130_units": 4,
    "gt150_daily": {"GT150": 4800 * LOSS_FACTOR, "GT130on150": 3000 * LOSS_FACTOR},
    "gt130_daily": 3000 * LOSS_FACTOR,
    "adpt_units": 2,  # GT150 适配 GT130 的“ADPT”位
}

OUT_CFG = {
    "outsourcing_daily_cap": float("inf"),
    "outsourcing_lead_days": 0,
}

class Machine:
    """简化：不再把换模当天产能置 0；cur_mold 仅用于统计/扩展。"""
    def __init__(self, name, pool):
        self.name = name     # e.g., GT150-01 / GT130-01 / ADPT-01
        self.pool = pool     # "GT150" / "GT130" / "ADPT"
        self.cur_mold = None

    def available_capacity(self):
        if self.pool == "GT150":
            return CONFIG["gt150_daily"]["GT150"]
        elif self.pool == "GT130":
            return CONFIG["gt130_daily"]
        elif self.pool == "ADPT":
            return CONFIG["gt150_daily"]["GT130on150"]
        return 0.0

    def assign(self, mold):
        self.cur_mold = mold


def schedule_with_changeover(ord_df: pd.DataFrame):
    """
    机台级排程（含换模影响，简化版）

    与旧版的关键区别：
    - 为每台机、每天维护“剩余能力” rem_cap，保证单机单日产量不超过 CONFIG 中的日能力；
    - 换模损失已经通过 LOSS_FACTOR 体现在日能力中，这里不再单独把换模当天置为 0 产能；
    - 返回值接口与原函数保持完全一致：
        alloc_df: 机台-日期-订单排产明细
        acc_df:   预留（目前为空表）
        summary_df: 订单完工与外包/迟期情况
    """
    # 复制并准备基础字段
    df = ord_df.reset_index(drop=True).copy()
    if "order_id" not in df.columns:
        df["order_id"] = np.arange(len(df)).astype(int)
    df["remain"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0.0).astype(float)

    start_date = pd.to_datetime(df["earliest_start_date"]).min()
    end_date   = pd.to_datetime(df["latest_finish_date"]).max()
    days = pd.date_range(start_date, end_date, freq="D")

    # 建立机台对象
    gt150_m = [Machine(f"GT150-{i+1:02d}", "GT150") for i in range(CONFIG["gt150_units"])]
    adpt_m  = [Machine(f"ADPT-{i+1:02d}",  "ADPT")  for i in range(CONFIG.get("adpt_units", 2))]
    gt130_m = [Machine(f"GT130-{i+1:02d}", "GT130") for i in range(CONFIG["gt130_units"])]

    alloc_rows, acc_rows = [], []

    # === 按天循环排产 ===
    for day in days:
        # (1) 计算当天每台机的“剩余能力”
        rem_cap_150 = {m.name: m.available_capacity() for m in gt150_m}
        rem_cap_130 = {m.name: m.available_capacity() for m in gt130_m}
        rem_cap_adpt = {m.name: m.available_capacity() for m in adpt_m}

        # (2) 选出当日可排的订单（在窗口内且仍有未完成量）
        todays = df[
            (pd.to_datetime(df["earliest_start_date"]) <= day)
            & (pd.to_datetime(df["latest_finish_date"]) >= day)
            & (df["remain"] > 1e-9)
        ].sort_values(["latest_finish_date", "due_date"]).index

        # ① GT150-native：只能在 GT150 上做 150 模具
        for o in todays:
            mold_machine = str(df.at[o, "mold_machine"] or "")
            if "150" not in mold_machine:
                continue
            need = float(df.at[o, "remain"])
            if need <= 1e-9:
                continue
            for m in gt150_m:
                if need <= 1e-9:
                    break
                cap = rem_cap_150[m.name]
                if cap <= 1e-9:
                    continue
                take = min(need, cap)
                if take <= 1e-9:
                    continue
                m.assign(mold_machine)
                need -= take
                rem_cap_150[m.name] -= take
                alloc_rows.append({
                    "date": day.date(),
                    "pool": "GT150",
                    "machine_id": m.name,
                    "order_idx": df.at[o, "order_id"],
                    "client": df.at[o, "client_code"],
                    "product": df.at[o, "product_code"],
                    "mold": mold_machine,
                    "qty": float(take),
                })
            df.at[o, "remain"] = need

        # ② GT130-native：优先在 GT130 上做 130 模具
        for o in todays:
            mold_machine = str(df.at[o, "mold_machine"] or "")
            if "130" not in mold_machine:
                continue
            need = float(df.at[o, "remain"])
            if need <= 1e-9:
                continue
            mold = str(df.at[o, "mold_code"] or df.at[o, "product_code"])
            for m in gt130_m:
                if need <= 1e-9:
                    break
                cap = rem_cap_130[m.name]
                if cap <= 1e-9:
                    continue
                take = min(need, cap)
                if take <= 1e-9:
                    continue
                m.assign(mold)
                need -= take
                rem_cap_130[m.name] -= take
                alloc_rows.append({
                    "date": day.date(),
                    "pool": "GT130",
                    "machine_id": m.name,
                    "order_idx": df.at[o, "order_id"],
                    "client": df.at[o, "client_code"],
                    "product": df.at[o, "product_code"],
                    "mold": mold,
                    "qty": float(take),
                })
            df.at[o, "remain"] = need

        # ③ GT130 on GT150（ADPT）：用 ADPT 位兜底 130 模具
        for o in todays:
            mold_machine = str(df.at[o, "mold_machine"] or "")
            if "130" not in mold_machine:
                continue
            need = float(df.at[o, "remain"])
            if need <= 1e-9:
                continue
            mold = str(df.at[o, "mold_code"] or df.at[o, "product_code"])
            for m in adpt_m:
                if need <= 1e-9:
                    break
                cap = rem_cap_adpt[m.name]
                if cap <= 1e-9:
                    continue
                take = min(need, cap)
                if take <= 1e-9:
                    continue
                m.assign(mold)
                need -= take
                rem_cap_adpt[m.name] -= take
                alloc_rows.append({
                    "date": day.date(),
                    "pool": "ADPT",
                    "machine_id": m.name,
                    "order_idx": df.at[o, "order_id"],
                    "client": df.at[o, "client_code"],
                    "product": df.at[o, "product_code"],
                    "mold": mold,
                    "qty": float(take),
                })
            df.at[o, "remain"] = need

    # === 外包与迟期（仍按照原逻辑处理剩余量） ===
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

    # —— 分配表（即使空也带标准列） —— #
    alloc_cols = ["date","pool","machine_id","order_idx","client","product","mold","qty"]
    alloc_df = pd.DataFrame(alloc_rows, columns=alloc_cols)
    if not alloc_df.empty:
        alloc_df["date"] = pd.to_datetime(alloc_df["date"])

    # —— 完工汇总 —— #
    comp_rows = []
    for o in df.index:
        oid = df.at[o, "order_id"]
        qty = float(df.at[o, "qty"])
        outsourced = float(df.at[o, "outsourced_units"])
        need_internal = qty - outsourced
        o_hist = alloc_df[alloc_df["order_idx"] == oid].sort_values("date")
        done_date = None
        if not o_hist.empty:
            cum = o_hist["qty"].cumsum()
            for dt, val in zip(o_hist["date"], cum):
                if float(val) >= need_internal - 1e-6:
                    done_date = dt
                    break
        comp_rows.append({
            "order_idx": oid,
            "qty": qty,
            "client": df.at[o, "client_code"],
            "product": df.at[o, "product_code"],
            "due_date": pd.to_datetime(df.at[o, "due_date"]).date(),
            "latest_finish": pd.to_datetime(df.at[o, "latest_finish_date"]).date(),
            "done_date": (done_date.date() if done_date is not None else None),
            "outsourced_units": outsourced,
            "lateness_units": float(df.at[o, "lateness_units"]),
        })
    summary_df = pd.DataFrame(comp_rows)

    # —— 上线时间（首次开始生产的日期） —— #
    if not alloc_df.empty and not summary_df.empty:
        first_start_map = alloc_df.groupby("order_idx")["date"].min().dt.date.to_dict()
        summary_df["first_start_date"] = summary_df["order_idx"].map(first_start_map)
    else:
        if not summary_df.empty:
            summary_df["first_start_date"] = None

    # 占位（acc_rows 暂不使用）
    acc_df = pd.DataFrame(acc_rows)

    return alloc_df, acc_df, summary_df



if __name__ == "__main__":
    print("Module C standalone test...")
