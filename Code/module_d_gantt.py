# -*- coding: utf-8 -*-
"""
方案D：一机一日一模（含甘特）
修正版：稳定使用 order_id + ADPT 作为 GT130 的适配产能（不依赖“ADPT订单”）
"""

from __future__ import annotations
import os
import numpy as np
import pandas as pd
import datetime as dt
import matplotlib.pyplot as plt
from matplotlib import rcParams

rcParams["font.sans-serif"] = ["SimHei", "Arial", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False

DEFAULT_COUNTS = {"GT150": 8, "GT130": 4, "ADPT": 2}
CAP_PER_DAY    = {"GT150": 4800.0, "GT130": 3000.0, "ADPT": 3000.0}
CHANGEOVER_H   = {"GT150": 2.0, "GT130": 2.0, "ADPT": 1.5}


def _safe_date(x, default=None):
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return default


def _load_assets_counts():
    """从资产表推断各机型台数；失败则采用默认台数"""
    try:
        from module_a_data import load_and_prepare
        _, _clients, assets, _products, _materials, _acc = load_and_prepare()
        df = assets.copy()
        cand_cols = ["机型", "设备型号", "设备机型", "asset_type", "type", "model"]
        col = next((c for c in cand_cols if c in df.columns), None)
        if col is None:
            return DEFAULT_COUNTS.copy()
        cnts = {}
        u = df[col].astype(str).str.upper()
        for k in ["GT150", "GT130", "ADPT"]:
            cnts[k] = int(u.str.contains(k).sum())
        # 兜底：缺失时回退默认
        for k, v in DEFAULT_COUNTS.items():
            if cnts.get(k, 0) <= 0:
                cnts[k] = v
        return cnts
    except Exception:
        return DEFAULT_COUNTS.copy()


def _normalize_pool(mold_machine: str) -> str:
    s = str(mold_machine).upper().strip() if pd.notnull(mold_machine) else ""
    if "150" in s: return "GT150"
    if "130" in s: return "GT130"
    if "ADPT" in s or "ADAPTER" in s or "配件" in s: return "ADPT"
    return "GT150"


def _make_machine_list(counts):
    return {pool: [f"{pool}-{i+1}" for i in range(int(max(0, n)))] for pool, n in counts.items()}


def run_schedule_and_gantt(ord_df: pd.DataFrame):
    if ord_df is None or ord_df.empty:
        empty = pd.DataFrame()
        return empty, empty, 0.0, empty, empty

    df = ord_df.copy()

    # 统一主键
    if "order_id" not in df.columns:
        df["order_id"] = np.arange(len(df)).astype(int)

    # 基本时间
    df["due_date"] = df["due_date"].apply(lambda x: _safe_date(x))
    if "latest_finish_date" in df.columns:
        df["latest_finish"] = df["latest_finish_date"].apply(lambda x: _safe_date(x))
    else:
        df["latest_finish"] = df["due_date"].apply(lambda d: (d - dt.timedelta(days=2)) if d else None)

    if "earliest_start_date" in df.columns:
        df["earliest_start"] = df["earliest_start_date"].apply(lambda x: _safe_date(x))
    else:
        global_min_due = min([d for d in df["due_date"].tolist() if d is not None] + [dt.date.today()])
        df["earliest_start"] = global_min_due - dt.timedelta(days=14)

    # 机型归类（GT150 / GT130；ADPT 在本方案中仅作为 GT130 的适配机台）
    df["pool_primary"] = df["mold_machine"].apply(_normalize_pool)

    # 机台清单
    machine_counts = _load_assets_counts()
    machines = _make_machine_list(machine_counts)

    # 计划范围
    max_due = max([d for d in df["due_date"].tolist() if d is not None] + [dt.date.today()])
    horizon_end = max_due + dt.timedelta(days=60)

    # ===== 订单队列：仅 GT150 与 GT130（ADPT 不单独作为订单机型） =====
    orders_main = []
    for _, r in df.iterrows():
        pool = r["pool_primary"]
        if pool not in ["GT130", "GT150"]:
            continue
        orders_main.append({
            "order_id": r["order_id"],
            "qty": float(r.get("qty", 0.0) or 0.0),
            "due_date": r["due_date"],
            "latest_finish": r["latest_finish"],
            "earliest_start": r["earliest_start"],
            "pool_primary": pool,
            "remain": float(r.get("qty", 0.0) or 0.0),
        })

    # ===== 调度：GT130 → 优先 GT130 机台，其次 ADPT；GT150 → 仅 GT150 =====
    sched_rows, order_rows = [], []
    cur_day = min([o["earliest_start"] for o in orders_main] + [dt.date.today()])

    def _pick(queue, cond):
        q = sorted(queue, key=lambda x: (x["latest_finish"], x["due_date"], -x["remain"]))
        for item in q:
            if item["remain"] > 1e-9 and cond(item):
                return item
        return None

    while cur_day <= horizon_end:
        if all(o["remain"] <= 1e-9 for o in orders_main):
            break

        # 1) GT130 机台先排 GT130 订单
        for m_id in machines.get("GT130", []):
            item = _pick(orders_main, lambda it: it["pool_primary"] == "GT130" and (it["earliest_start"] is None or cur_day >= it["earliest_start"]))
            if item is None:
                continue
            produced = min(CAP_PER_DAY["GT130"], item["remain"])
            item["remain"] -= produced
            sched_rows.append({"date": cur_day, "pool": "GT130", "machine_type": "GT130", "machine_id": m_id,
                               "order_idx": item["order_id"], "qty": produced})
            order_rows.append({"date": cur_day, "order_idx": item["order_id"], "qty": produced})

        # 2) ADPT 机台承接剩余的 GT130 订单（适配）
        for m_id in machines.get("ADPT", []):
            item = _pick(orders_main, lambda it: it["pool_primary"] == "GT130" and it["remain"] > 1e-9 and (it["earliest_start"] is None or cur_day >= it["earliest_start"]))
            if item is None:
                continue
            produced = min(CAP_PER_DAY["ADPT"], item["remain"])
            item["remain"] -= produced
            sched_rows.append({"date": cur_day, "pool": "ADPT", "machine_type": "ADPT", "machine_id": m_id,
                               "order_idx": item["order_id"], "qty": produced})
            order_rows.append({"date": cur_day, "order_idx": item["order_id"], "qty": produced})

        # 3) GT150 机台排 GT150 订单
        for m_id in machines.get("GT150", []):
            item = _pick(orders_main, lambda it: it["pool_primary"] in ["GT150"] and (it["earliest_start"] is None or cur_day >= it["earliest_start"]))
            if item is None:
                continue
            produced = min(CAP_PER_DAY["GT150"], item["remain"])
            item["remain"] -= produced
            sched_rows.append({"date": cur_day, "pool": "GT150", "machine_type": "GT150", "machine_id": m_id,
                               "order_idx": item["order_id"], "qty": produced})
            order_rows.append({"date": cur_day, "order_idx": item["order_id"], "qty": produced})

        cur_day += dt.timedelta(days=1)

    schedule_df = pd.DataFrame(sched_rows)
    if not schedule_df.empty:
        schedule_df["date"] = pd.to_datetime(schedule_df["date"])

    order_alloc_df = pd.DataFrame(order_rows)
    if not order_alloc_df.empty:
        order_alloc_df["date"] = pd.to_datetime(order_alloc_df["date"])

    # ===== 完成情况汇总 =====
    need_map   = df.set_index("order_id")["qty"].to_dict()
    latest_map = df.set_index("order_id")["latest_finish"].to_dict()
    due_map    = df.set_index("order_id")["due_date"].to_dict()

    done_map = {}
    if not order_alloc_df.empty:
        for oid, g in order_alloc_df.sort_values(["order_idx","date"]).groupby("order_idx"):
            need = float(need_map.get(oid, 0.0) or 0.0)
            cum = 0.0; finish = None
            for _, row in g.iterrows():
                cum += float(row["qty"] or 0.0)
                if cum >= need - 1e-6:
                    finish = row["date"].date()
                    break
            done_map[oid] = finish

    rows_sum = []
    for _, r in df.iterrows():
        oid = r["order_id"]
        qty = float(r.get("qty", 0.0) or 0.0)
        latest = latest_map.get(oid)
        due = due_map.get(oid)
        within_qty = 0.0
        if not order_alloc_df.empty and latest is not None:
            g = order_alloc_df[
                (order_alloc_df["order_idx"] == oid) & (order_alloc_df["date"] <= pd.to_datetime(latest))]
            within_qty = float(g["qty"].sum())
        lateness_units = max(0.0, qty - within_qty)
        rows_sum.append({
            "order_idx": oid,
            "qty": qty,
            "latest_finish": latest,
            "due_date": due,
            "done_date": done_map.get(oid, None),
            "outsourced_units": 0.0,
            "lateness_units": lateness_units
        })
    summary_df = pd.DataFrame(rows_sum)
    if not summary_df.empty:
        for c in ["latest_finish", "due_date", "done_date"]:
            summary_df[c] = pd.to_datetime(summary_df[c]).dt.date
    # —— 上线时间（首次开始生产的日期） —— #
    if not order_alloc_df.empty and not summary_df.empty:
        first_map = order_alloc_df.groupby("order_idx")["date"].min().to_dict()
        summary_df["first_start_date"] = summary_df["order_idx"].map(first_map)
        summary_df["first_start_date"] = pd.to_datetime(summary_df["first_start_date"]).dt.date
    else:
        if not summary_df.empty:
            summary_df["first_start_date"] = None

    total_outsourced = float(summary_df["outsourced_units"].sum()) if not summary_df.empty else 0.0

    # ===== 换模统计（按机台每日订单变化近似） =====
    chg_rows = []
    if not schedule_df.empty:
        for pool in ["GT150", "GT130", "ADPT"]:
            sub = schedule_df[schedule_df["pool"] == pool].copy()
            if sub.empty:
                continue
            for mid, g in sub.sort_values(["date"]).groupby("machine_id"):
                g = g.sort_values("date")
                changes = 0
                last_order = None
                used_days = 0
                for _, row in g.iterrows():
                    used_days += 1
                    cur_order = int(row.get("order_idx", -1))
                    if last_order is None:
                        last_order = cur_order
                        continue
                    if cur_order != last_order:
                        changes += 1
                    last_order = cur_order
                chg_time = changes * CHANGEOVER_H.get(pool, 2.0)
                ratio = (chg_time / (max(used_days, 1) * 24.0)) if used_days > 0 else 0.0
                chg_rows.append({
                    "machine_type": pool,
                    "machine_id": mid,
                    "changeovers": changes,
                    "changeover_time_h": chg_time,
                    "changeover_ratio": ratio
                })
    chg_df = pd.DataFrame(chg_rows)

    # ===== 甘特图 =====
    for pool in ["GT150", "GT130", "ADPT"]:
        sub = schedule_df[schedule_df["pool"] == pool]
        if sub.empty:
            continue
        dfp = sub.copy()
        dfp["date"] = pd.to_datetime(dfp["date"])
        machines_order = sorted(dfp["machine_id"].unique().tolist())
        m_index = {m: i for i, m in enumerate(machines_order)}
        fig, ax = plt.subplots(figsize=(10, max(4, len(machines_order) * 0.5)))
        for _, row in dfp.iterrows():
            y = m_index[row["machine_id"]]
            ax.barh(y, 1, left=row["date"], align="center")
        ax.set_yticks(range(len(machines_order)))
        ax.set_yticklabels(machines_order)
        ax.set_xlabel("日期")
        ax.set_title(f"{pool} Gantt (one mold/day)")
        ax.grid(axis="x", linestyle="--", alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(f"{pool}_gantt.png", dpi=150)
        plt.close(fig)

    return schedule_df, chg_df, total_outsourced, summary_df, order_alloc_df


if __name__ == "__main__":
    print("Module D standalone test...")
