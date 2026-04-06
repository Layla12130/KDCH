
# -*- coding: utf-8 -*-
"""
Module E - Economics (Cost & Profit) Analysis (unit-safe + configurable labor + product pricing)
- 兼容三种方案（B/C/D），只计 材料+人工；外包默认同价销售（收入按销售价），成本为材料+人工（若无“外协单价”可用）。
- 原料价格：价格（元/吨）或（元/千克/kg），自动换算为 元/千克；若异常自动纠偏。
- 产品计量：重量（克）；配件：重量（克）+ 材质（可选）。
- 单位人工成本：可由外部传入 labor_unit（元/件）。
- 新增：若“产品列表”或“客户列表/价格表”存在单价列（含“售价/报价/单价/价格/Price”等关键词，单位按件），则优先按数据定价；否则退回“毛利率参数”定价。
"""

from __future__ import annotations
import os, re, math
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import rcParams

rcParams['font.sans-serif'] = ['SimHei', 'Arial', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False

# ---------------------- helpers ----------------------
def _get_margin(margin_arg):
    try:
        m = float(margin_arg)
        if 0 < m < 1: return m
    except Exception:
        pass
    try:
        m = float(os.environ.get("ECON_MARGIN", "0.25"))
        return m if 0 < m < 1 else 0.25
    except Exception:
        return 0.25

def _canon(s: str) -> str:
    return re.sub(r'[\s_（）()]+', '', str(s).lower())

def _to_float(x, default=0.0):
    try:
        if isinstance(x, str):
            x = x.replace(',', '')
        return float(x)
    except Exception:
        return float(default)

def _pick(df: pd.DataFrame, *names):
    cols = list(df.columns)
    low = [_canon(c) for c in cols]
    for n in names:
        cn = _canon(n)
        if cn in low:
            return cols[low.index(cn)]
    return None

# ---------------------- price utils ----------------------
def build_price_map(materials: pd.DataFrame) -> dict:
    """返回：{原料名 -> 元/千克}（允许“价格（元/吨）/（元/千克）”等多种表头）"""
    if materials is None or materials.empty:
        return {}
    name_col = _pick(materials, "原料", "材料", "材质", "原料名称", "material", "name")
    # 价格列：只要包含 价/单价/price，且列名里出现 元/吨/千克/kg 等字样
    price_col = None
    for c in materials.columns:
        cl = _canon(c)
        if ("价" in c or "单价" in c or "price" in cl) and any(u in cl for u in ["元吨","元/吨","/吨","元千克","元/千克","kg","公斤","千克"]):
            price_col = c
            break
    if price_col is None:
        # 退而求其次：找第一列之外的数值列
        for c in materials.columns[1:]:
            if pd.api.types.is_numeric_dtype(materials[c]):
                price_col = c
                break
    if not name_col or not price_col:
        return {}

    unit = "per_ton"
    pcl = _canon(price_col)
    if any(u in pcl for u in ["千克","公斤","kg","元千克","元/千克"]):
        unit = "per_kg"

    mp = {}
    for _, r in materials.iterrows():
        k = str(r.get(name_col, "")).strip()
        if not k: continue
        v = _to_float(r.get(price_col, 0.0))
        if unit == "per_ton":
            v = v / 1000.0  # → 元/千克
        mp[k] = v
    return mp

def _find_product_unit_price_columns(df: pd.DataFrame) -> str | None:
    """从产品表中猜测“按件销售价”列名"""
    if df is None or df.empty: 
        return None
    candidates = [c for c in df.columns if any(k in _canon(c) for k in [
        "售价","报价","单价","销售价","价格","price","unitprice","含税售价","出厂价","客户单价"
    ])]
    if not candidates:
        return None
    # 选择数值化程度高的列
    best, best_ratio = None, -1.0
    for c in candidates:
        try:
            ratio = pd.to_numeric(df[c], errors="coerce").notna().mean()
        except Exception:
            ratio = 0.0
        if ratio > best_ratio:
            best, best_ratio = c, ratio
    return best

def _maybe_fix_unit_price(series: pd.Series) -> pd.Series:
    """如果单价离谱（疑似“元/千克”或“元/吨”），尝试修正为“元/件”
       策略：若单价中位数 > 1e4 → 认为是“元/吨”（×产品重量(kg)/1000）；
            若 50 < 中位数 < 1e4 → 直接认为是元/件；
            若 中位数 < 0.2 → 认为是“元/千克”（×产品重量kg）。
       最终修正仍依赖 compute_unit_material_cost 中的重量，故这里只简单判断。
    """
    # 简化：先直接返回；如需更复杂逻辑，可在将来根据样本再细化。
    return pd.to_numeric(series, errors="coerce")

# ---------------------- data loader ----------------------
def load_core_data():
    from module_a_data import load_and_prepare
    ord_df, clients, assets, products, materials, acc = load_and_prepare()
    return ord_df, materials, acc, products

# ---------------------- material cost ----------------------
def compute_unit_material_cost(ord_df, materials, acc, auto_fix=True):
    # 价格表 → 元/千克
    price_map = build_price_map(materials)

    # 配件重量与材质（可选）
    ring_w, stand_w = 0.0, 0.0
    ring_mat, stand_mat = None, None
    if acc is not None and not acc.empty:
        ncol = _pick(acc, "名称","name")
        wcol = _pick(acc, "重量（克）","重量(克)","重量g","重量","weight_g","weight")
        mcol = _pick(acc, "材质","原料","材料","material")
        if ncol and wcol:
            acc = acc.copy()
            acc["w"] = acc[wcol].apply(_to_float)
            amap = {str(r[ncol]).strip(): r["w"] for _,r in acc.iterrows()}
            ring_w  = _to_float(amap.get("散热环", 0.0))
            stand_w = _to_float(amap.get("支架", 0.0))
            if mcol:
                mm = {str(r[ncol]).strip(): str(r[mcol]).strip() for _,r in acc.iterrows()}
                ring_mat  = mm.get("散热环")
                stand_mat = mm.get("支架")

    # 主体材料 + 配件材料（若有材质就按其材质；否则回退铝）
    def per_row_cost(row):
        cost = 0.0
        wkg = _to_float(row.get("weight_g"))/1000.0
        mat = str(row.get("material","")).strip()
        if wkg>0 and mat in price_map:
            cost += wkg*price_map[mat]
        # 配件
        def add_part(need_flag, add_w, mat_hint=None):
            nonlocal cost
            if not bool(need_flag) or add_w<=0: return
            key = None
            # 优先配件材质
            if mat_hint and mat_hint in price_map:
                key = mat_hint
            else:
                # 回退铝/铝合金/AL
                for k in ["铝","铝材","铝合金","AL","Al","aluminium","aluminum"]:
                    if k in price_map: key=k; break
            if key:
                cost += (add_w/1000.0)*price_map[key]

        add_part(row.get("need_ring", False), ring_w, ring_mat)
        add_part(row.get("need_stand", False), stand_w, stand_mat)
        return float(cost)

    ord_df["unit_material_cost"] = ord_df.apply(per_row_cost, axis=1)

    # —— 自动纠偏（根据反推的 元/千克 中位数判断是否×1000/÷1000） ——
    if auto_fix:
        tmp = ord_df.copy()
        tmp["wkg"] = tmp["weight_g"].apply(_to_float)/1000.0
        tmp = tmp[(tmp["wkg"]>0) & (tmp["unit_material_cost"]>0)]
        if not tmp.empty:
            back_price = (tmp["unit_material_cost"]/tmp["wkg"]).replace([np.inf,-np.inf], np.nan).dropna()
            if not back_price.empty:
                med = float(back_price.median())
                if med > 500:  # 过高：把元/吨当成了元/千克 → ÷1000
                    ord_df["unit_material_cost"] = ord_df["unit_material_cost"]/1000.0
                elif med < 0.5:  # 过低：把元/千克当成了元/吨 → ×1000
                    ord_df["unit_material_cost"] = ord_df["unit_material_cost"]*1000.0

    return ord_df

# ---------------------- main ----------------------
def main(margin=None, labor_unit=None, auto_unit_fix=True):
    # 1) 数据
    ord_df, materials, acc, products = load_core_data()

    # 2) 单位材料成本（含自动纠偏）
    ord_df = compute_unit_material_cost(ord_df, materials, acc, auto_fix=auto_unit_fix)

    # 3) 单位人工成本（元/件，可配置）
    if labor_unit is None:
        labor_unit = _to_float(os.environ.get("ECON_LABOR_UNIT", 0.6))  # 默认 0.6 元/件
    else:
        labor_unit = _to_float(labor_unit, 0.6)
    ord_df["unit_labor_cost_baseline"] = float(labor_unit)

    # 4) 内部售价（优先用产品/客户单价；否则用毛利率反推）
    MARGIN = _get_margin(margin)

    # 4.1 从产品表尽量识别“单价/售价/报价(元/件)”
    unit_price_map_pc = {}    # (product_code, client_code) -> price
    unit_price_map_p  = {}    # product_code -> price（无客户维度时）
    vendor_price_map  = {}    # 外协单价（若有）

    if products is not None and not products.empty:
        price_col = _find_product_unit_price_columns(products)
        if price_col:
            # 客户维度+产品维度都尝试建立
            pcol = _pick(products, "产品代码", "product_code")
            ccol = _pick(products, "客户代码", "client_code")
            ser = _maybe_fix_unit_price(products[price_col])
            if pcol and ccol:
                for _, r in products.iterrows():
                    p = r[pcol]; c = r[ccol]
                    val = _to_float(r.get(price_col))
                    if pd.notna(p) and pd.notna(c) and val>0:
                        unit_price_map_pc[(str(p), str(c))] = val
            if pcol:
                g = products.groupby(pcol)[price_col].median(numeric_only=True)
                for k, v in g.items():
                    if pd.notna(v) and v>0: unit_price_map_p[str(k)] = float(v)

        # 外协单价（可选）
        for c in products.columns:
            cl = _canon(c)
            if any(k in cl for k in ["外协单价","外包单价","代工单价","加工费"]):
                pcol = _pick(products, "产品代码","product_code")
                if pcol:
                    s = pd.to_numeric(products[c], errors="coerce")
                    for k, v in s.groupby(products[pcol]).median(numeric_only=True).items():
                        if pd.notna(v) and v>0: vendor_price_map[str(k)] = float(v)
                break

    # 4.2 决定每行的“销售单价”
    def get_unit_price(row):
        # 先 (product, client) 精确；再仅 product；最后用毛利率反推
        key = (str(row.get("product_code")), str(row.get("client_code")))
        if key in unit_price_map_pc:
            return float(unit_price_map_pc[key])
        if str(row.get("product_code")) in unit_price_map_p:
            return float(unit_price_map_p[str(row.get("product_code"))])
        # 退回：成本/(1-毛利率)
        unit_cost = _to_float(row.get("unit_material_cost")) + _to_float(row.get("unit_labor_cost_baseline"))
        return unit_cost / max(1e-9, (1.0 - MARGIN))

    ord_df["unit_price_internal"] = ord_df.apply(get_unit_price, axis=1)

    # 5) 读排程结果，映射数量（不同方案→不同“内部/外包/超期”分解）
    alloc, summary, tag = read_schedule()
    if "order_idx" not in summary.columns:
        for c in ["订单编号","订单id","order_id"]:
            if c in summary.columns:
                summary = summary.rename(columns={c:"order_idx"})
                break
    if "qty" not in summary.columns:
        for c in ["完成数量","总量","产量","quantity"]:
            if c in summary.columns:
                summary = summary.rename(columns={c:"qty"})
                break
    if "outsourced_units" not in summary.columns:
        summary["outsourced_units"] = 0.0

    qty_map  = summary.set_index("order_idx")["qty"].to_dict()
    outs_map = summary.set_index("order_idx")["outsourced_units"].to_dict()
    ord_df["internal_qty"]   = ord_df["order_id"].map(lambda k: _to_float(qty_map.get(k, 0.0)))
    ord_df["outsourced_qty"] = ord_df["order_id"].map(lambda k: _to_float(outs_map.get(k, 0.0)))
    ord_df["internal_qty"]   = (ord_df["internal_qty"] - ord_df["outsourced_qty"]).clip(lower=0.0)

    # 6) 订单级经济性（外包收入按销售价；外包成本可用“外协单价”，否则材料+人工）
    unit_vendor_cost = ord_df["product_code"].map(lambda p: _to_float(vendor_price_map.get(str(p), np.nan)))
    unit_cost_internal = ord_df["unit_material_cost"] + ord_df["unit_labor_cost_baseline"]
    unit_cost_outsourced = unit_vendor_cost.fillna(unit_cost_internal)

    ord_df["internal_material"] = ord_df["internal_qty"]  * ord_df["unit_material_cost"]
    ord_df["internal_labor"]    = ord_df["internal_qty"]  * ord_df["unit_labor_cost_baseline"]
    ord_df["outsourced_cost"]   = ord_df["outsourced_qty"] * unit_cost_outsourced
    # 客户收入：内制与外包均以销售价结算（客户不关心是内制还是外包）
    ord_df["internal_revenue"]  = ord_df["internal_qty"]  * ord_df["unit_price_internal"]
    ord_df["outsourced_revenue"]= ord_df["outsourced_qty"] * ord_df["unit_price_internal"]

    keep_cols = ["order_id","client_code","product_code","internal_qty","outsourced_qty",
                 "unit_material_cost","unit_labor_cost_baseline","unit_price_internal",
                 "internal_material","internal_labor","internal_revenue",
                 "outsourced_cost","outsourced_revenue"]
    econ = ord_df[[c for c in keep_cols if c in ord_df.columns]].copy()
    econ["revenue_total"] = econ.get("internal_revenue",0)+econ.get("outsourced_revenue",0)
    econ["cost_total"]    = econ.get("internal_material",0)+econ.get("internal_labor",0)+econ.get("outsourced_cost",0)
    econ["profit"]        = econ["revenue_total"] - econ["cost_total"]
    econ["profit_rate"]   = np.where(econ["revenue_total"]>1e-9, econ["profit"]/econ["revenue_total"], 0.0)

    # 7) 导出
    econ.to_csv("经济性分析_订单级.csv", index=False, encoding="utf-8-sig")
    summary_rows = {
        "订单数": int((econ["internal_qty"]+econ["outsourced_qty"]>0).sum()),
        "内制总量": float(econ["internal_qty"].sum()),
        "外包总量": float(econ["outsourced_qty"].sum()),
        "总收入": float(econ["revenue_total"].sum()),
        "总成本": float(econ["cost_total"].sum()),
        "总利润": float(econ["profit"].sum()),
        "整体利润率": float(econ["profit"].sum())/float(econ["revenue_total"].sum()) if econ["revenue_total"].sum()>1e-9 else 0.0,
        "毛利润率参数": float(MARGIN),
        "数据来源": tag,
    }
    pd.DataFrame([summary_rows]).to_csv("经济性分析_汇总.csv", index=False, encoding="utf-8-sig")

    # 8) 出图（即使为0也生成）
    try:
        parts = {
            "材料": float(econ["internal_material"].sum()),
            "人工": float(econ["internal_labor"].sum()),
            "外包": float(econ["outsourced_cost"].sum()),
        }
        sizes = list(parts.values())
        if sum(sizes) <= 0:
            sizes = [1,1,1]
        fig1, ax1 = plt.subplots(figsize=(6,6))
        ax1.pie(sizes, labels=list(parts.keys()), autopct='%1.1f%%')
        ax1.set_title("成本结构（材料/人工/外包）")
        fig1.tight_layout()
        fig1.savefig("成本结构_饼图.png", dpi=150); plt.close(fig1)

        top = econ.sort_values("profit_rate", ascending=False).head(10)
        fig2, ax2 = plt.subplots(figsize=(9,4))
        vals = top["profit_rate"].values if "profit_rate" in top else []
        ax2.bar(range(len(top)), vals)
        ax2.set_xticks(range(len(top)))
        labels = []
        for _, r in top.iterrows():
            c = str(r.get("client_code",""))[:6]; p = str(r.get("product_code",""))[:12]
            labels.append(f"{c}-{p}")
        ax2.set_xticklabels(labels, rotation=40, ha="right")
        ax2.set_ylabel("利润率"); ax2.set_title("Top10 订单利润率")
        fig2.tight_layout(); fig2.savefig("利润率_柱状图.png", dpi=150); plt.close(fig2)
    except Exception as e:
        print("绘图失败：", repr(e))

# ---------------------- schedule readers ----------------------
def read_schedule():
    # B
    if os.path.exists("主生产计划_日粒度_启发式.csv") and os.path.exists("订单完成情况_启发式.csv"):
        alloc = pd.read_csv("主生产计划_日粒度_启发式.csv")
        summary = pd.read_csv("订单完成情况_启发式.csv")
        if "date" in alloc.columns:
            alloc["date"] = pd.to_datetime(alloc["date"])
        return alloc, summary, "B"
    # C
    if os.path.exists("主生产计划_机台_含换模.csv") and os.path.exists("订单完成情况_机台_含换模.csv"):
        alloc = pd.read_csv("主生产计划_机台_含换模.csv").rename(columns={"qty":"x150"})
        for c in ["x130","x150_adapter"]:
            if c not in alloc.columns: alloc[c]=0.0
        if "date" in alloc.columns:
            alloc["date"] = pd.to_datetime(alloc["date"])
        summary = pd.read_csv("订单完成情况_机台_含换模.csv")
        return alloc, summary, "C"
    # D
    if os.path.exists("订单完成情况_一日一模.csv"):
        summary = pd.read_csv("订单完成情况_一日一模.csv")
        if os.path.exists("订单分配_一日一模.csv"):
            alloc = pd.read_csv("订单分配_一日一模.csv").rename(columns={"qty":"x150"})
            for c in ["x130","x150_adapter"]:
                if c not in alloc.columns: alloc[c]=0.0
            if "date" in alloc.columns:
                alloc["date"] = pd.to_datetime(alloc["date"])
            return alloc, summary, "D-alloc"
        else:
            alloc = pd.DataFrame(columns=["date","order_idx","x150","x130","x150_adapter"])
            return alloc, summary, "D-summary"
    raise FileNotFoundError("未找到排产结果，请先运行方案B/C/D（任一）。")

if __name__ == "__main__":
    main()
