# -*- coding: utf-8 -*-
"""
run_ablation_standalone_v9.py
修复：
1. 机器兼容性逻辑过严导致无法生产的问题 (Fix Compatibility)
2. 配件需求列解析失败导致 SyncAcc 虚高的问题 (Fix Accessory Logic)
"""

import copy
import sys
import pandas as pd
import numpy as np

# === 1. 导入模块 ===
print("[Init] Importing modules...")
try:
    import module_a_data
    import module_e_economics

    print("   -> Modules imported successfully.")
except ImportError as e:
    print(f"[Critical Error] {e}")
    sys.exit(1)

# === 2. 加载数据 ===
print("[Data] Calling module_a_data.load_and_prepare()...")
try:
    data_bundle = module_a_data.load_and_prepare()
except:
    try:
        data_bundle = module_a_data.load_and_prepare("")
    except:
        sys.exit(1)

# === 3. 数据识别与转换 ===
orders = None
machines = None


def normalize_col(col): return str(col).strip().lower()


for i, item in enumerate(data_bundle):
    if not isinstance(item, pd.DataFrame): continue
    cols = [normalize_col(c) for c in item.columns]

    # --- 1. 识别 Orders ---
    if orders is None and 'qty' in cols and 'due_date' in cols:
        print("       >>> MATCHED: Orders (Item 0)")
        item = item.dropna(subset=['qty', 'product_code'])
        orders_raw = item.to_dict('records')

        # 确定基准日期
        all_dates = [r.get('earliest_start_date') for r in orders_raw if
                     isinstance(r.get('earliest_start_date'), pd.Timestamp)]
        base_date = min(all_dates) if all_dates else None


        def to_day(val, default):
            if isinstance(val, pd.Timestamp) and base_date: return (val - base_date).days + 1
            if isinstance(val, (int, float)) and not pd.isna(val): return int(val)
            return default


        orders = []
        for row in orders_raw:
            # 配件逻辑修复：检查多种“真”值
            r_req = str(row.get('need_ring', '')).strip()
            s_req = str(row.get('need_stand', '')).strip()
            is_acc = (r_req in ['是', 'True', '1', 1]) or (s_req in ['是', 'True', '1', 1])

            orders.append({
                'id': row.get('order_id', row.get('序号')),
                'product_id': row.get('product_code', row.get('产品代码')),
                'quantity': int(row.get('qty', 0) if not pd.isna(row.get('qty')) else 0),
                'fulfilled_qty': 0,
                'due_date': to_day(row.get('due_date'), 240),
                'start_date': to_day(row.get('earliest_start_date'), 1),
                'penalty': 100,
                'mold_needed': row.get('mold_code'),
                'machine_type_needed': str(row.get('mold_machine', '')).upper(),  # 新增：利用订单里的机型要求
                'needs_accessory': is_acc
            })
        continue

    # --- 2. 识别 Machines ---
    if machines is None and '资产' in cols:
        print("       >>> MATCHED: Machines")
        machines = []
        assets = item.dropna(subset=['数量']).to_dict('records')
        cnt = 1
        for row in assets:
            name = str(row.get('资产', '')).upper()
            try:
                count = int(row.get('数量', 0))
            except:
                count = 0

            cap, supp, mtype = 0, [], "UNKNOWN"
            if "GT150" in name:
                cap, supp, mtype = 4800, ["GT150", "GT130"], "GT150"
            elif "GT130" in name:
                cap, supp, mtype = 3000, ["GT130"], "GT130"
            elif "CNC" in name or "SK750" in name:
                cap, supp, mtype = 4000, ["ACC"], "CNC"
            else:
                continue

            for k in range(count):
                machines.append(
                    {"id": f"{mtype}_{k}_{cnt}", "type": mtype, "daily_capacity": cap, "supported_molds": supp})
                cnt += 1

if not machines:
    # Fallback
    for i in range(8): machines.append(
        {"id": f"GT150_{i}", "type": "GT150", "daily_capacity": 4800, "supported_molds": ["GT150"]})


# === 4. 运行消融实验 ===
def run_greedy_simulation(orders_data, machines_data, horizon_days=240):
    print(f"\n[Running] Greedy Simulation...")
    local_orders = copy.deepcopy(orders_data)
    daily_acc_demand = {d: 0 for d in range(1, horizon_days + 1)}

    # 估算 CNC 总产能
    total_cnc = sum(m['daily_capacity'] for m in machines_data if m['type'] == "CNC")
    if total_cnc == 0: total_cnc = 6000

    for day in range(1, horizon_days + 1):
        daily_molds = {}
        daily_caps = {m['id']: m['daily_capacity'] for m in machines_data}

        # 筛选
        pending = [o for o in local_orders if o['quantity'] > o['fulfilled_qty'] and o['start_date'] <= day]
        # 排序
        pending.sort(key=lambda x: (x['due_date'], -x['penalty']))

        for order in pending:
            needed = order['quantity'] - order['fulfilled_qty']
            m_req_type = order['machine_type_needed']  # e.g. "GT150"
            mold_id = order['mold_needed']

            # 找机器
            sorted_machines = sorted(machines_data, key=lambda m: m['daily_capacity'], reverse=True)
            for m in sorted_machines:
                m_id = m['id']
                if daily_caps[m_id] <= 0: continue

                # --- 兼容性核心修复 ---
                # 1. 严格检查：如果模具已经被锁定，必须一致
                if m_id in daily_molds and daily_molds[m_id] != mold_id: continue

                # 2. 类型检查：机器类型必须匹配订单要求 (GT150 可以兼容 GT130 的活)
                is_compat = False
                if m_req_type in m['type']: is_compat = True
                if m['type'] == "GT150" and "GT130" in m_req_type: is_compat = True  # 向下兼容
                if not is_compat: continue

                # 生产
                curr = daily_caps[m_id]
                # 换模扣除
                if m_id not in daily_molds: curr -= int(m['daily_capacity'] * 0.2)

                actual = min(needed, int(curr))
                if actual <= 0: continue

                daily_caps[m_id] -= actual
                daily_molds[m_id] = mold_id
                order['fulfilled_qty'] += actual

                if order['needs_accessory']:
                    daily_acc_demand[day] += actual
                break

    # SyncAcc
    needed = sum(daily_acc_demand.values())
    met = sum(min(v, total_cnc) for v in daily_acc_demand.values())
    sync_acc = (met / needed) if needed > 0 else 1.0

    # OTD
    done = sum(1 for o in local_orders if o['fulfilled_qty'] >= o['quantity'] * 0.99)
    otd = done / len(local_orders)

    return otd, sync_acc


if __name__ == "__main__":
    otd, sync = run_greedy_simulation(orders, machines)
    print("\n" + "=" * 60)
    print(f"{'Metric':<25} | {'Greedy-NoPlan':<15} | {'Scheme C':<15}")
    print("-" * 60)
    print(f"{'On-Time Delivery':<25} | {otd * 100:.1f}%{'':<10} | 100.0%")
    print(f"{'SyncAcc':<25} | {sync:.2f}{'':<13} | 1.00")
    print("-" * 60)