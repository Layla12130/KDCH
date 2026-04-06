# -*- coding: utf-8 -*-
"""
Module A - Data Ingestion & Preparation
读取基础数据、规范字段、建立订单与产品映射、计算排程窗口与配件需求。
输出：ord_df, clients, assets, products, materials, acc

修复要点：
1) 产品表 (product_code, client_code) 去重聚合，确保与订单多对一合并；
2) 更鲁棒的布尔解析（是否要安装散热环/支架）；
3) 优先从环境变量 APS_XLS_PATH 读取本次上传的 Excel（app.py 已设置），否则回退默认路径。
"""

import os
import pandas as pd
import numpy as np

# —— 默认本地路径（如果没有设置 APS_XLS_PATH 就用它）
DEFAULT_PATH = r".\手机壳工厂基础数据-更新1008.xlsx"

CONFIG = {
    "start_date": pd.Timestamp("2025-03-01"),
    "pack_days": 1,   # 完成后1天包装
    "ship_days": 1,   # 包装后1天出库
}

def _path_from_env() -> str:
    """优先用环境变量 APS_XLS_PATH（由 app.py 在上传后设置），否则回退默认路径。"""
    p = os.getenv("APS_XLS_PATH", "").strip()
    return p if p else DEFAULT_PATH

def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def _to_bool_series(s: pd.Series) -> pd.Series:
    m = {
        "是": True, "否": False,
        "1": True,  "0": False,
        "true": True, "false": False,
        "True": True, "False": False,
        "Y": True, "N": False, "y": True, "n": False,
    }
    return s.astype(str).str.strip().map(m).fillna(False)

def load_and_prepare():
    """加载并整合 Excel（来自 APS_XLS_PATH 或默认路径）"""
    path = _path_from_env()

    clients   = pd.read_excel(path, sheet_name="客户列表")
    assets    = pd.read_excel(path, sheet_name="资产列表")
    products  = pd.read_excel(path, sheet_name="产品列表")
    materials = pd.read_excel(path, sheet_name="原料价格表")
    acc       = pd.read_excel(path, sheet_name="配件列表")
    orders    = pd.read_excel(path, sheet_name="订单列表")

    # 统一列名
    clients   = normalize_cols(clients)
    assets    = normalize_cols(assets)
    products  = normalize_cols(products)
    materials = normalize_cols(materials)
    acc       = normalize_cols(acc)
    orders    = normalize_cols(orders)

    # 订单时间
    if "交期" in orders.columns:
        orders["交期"] = pd.to_datetime(orders["交期"])

    # ---------- 产品表标准化 & 去重聚合 ----------
    prod_attr = products.rename(columns={
        "产品代码": "product_code",
        "产品名称": "product_name",
        "客户代码": "client_code",
        "模具代码": "mold_code",
        "模具适配机型": "mold_machine",
        "原料": "material",
        "重量（克）": "weight_g",
        "是否要安装散热环": "need_ring",
        "是否要安装支架": "need_stand",
    }).copy()

    # 布尔列
    for c in ["need_ring", "need_stand"]:
        if c in prod_attr.columns:
            prod_attr[c] = _to_bool_series(prod_attr[c])
        else:
            prod_attr[c] = False

    # 同一 (product_code, client_code) 若出现多行，做“非空优先的一行聚合”
    # 规则：字符串列取第一个非空；数值列取第一个非空数值；布尔列取 OR。
    if not prod_attr.empty:
        keys = ["product_code", "client_code"]
        # 只保留我们要用到的字段
        keep_cols = keys + ["product_name","mold_code","mold_machine","material","weight_g","need_ring","need_stand"]
        prod_attr = prod_attr[keep_cols]

        def _first_nonnull(series):
            for v in series:
                if pd.notna(v) and v != "":
                    return v
            return np.nan

        agg_dict = {
            "product_name": _first_nonnull,
            "mold_code": _first_nonnull,
            "mold_machine": _first_nonnull,
            "material": _first_nonnull,
            "weight_g": _first_nonnull,
            "need_ring": "max",     # True/False → 取 OR
            "need_stand": "max",
        }

        prod_attr_unique = (prod_attr
                            .sort_values(keys)  # 保证稳定
                            .groupby(keys, as_index=False)
                            .agg(agg_dict))
    else:
        prod_attr_unique = prod_attr.copy()

    # ---------- 订单与产品关联（多对一） ----------
    ord_df = orders.rename(columns={
        "客户代码": "client_code",
        "产品代码": "product_code",
        "数量":     "qty",
        "交期":     "due_date",
        "订单编号":  "order_id",
    }).copy()

    # order_id 兜底；尽量保持为“原始编号”，若全是数字则转为整数
    if "order_id" not in ord_df.columns:
        ord_df["order_id"] = np.arange(len(ord_df)).astype(int)
    else:
        # 尝试数值化（失败则保留原样）
        try:
            ord_df["order_id"] = pd.to_numeric(ord_df["order_id"], errors="ignore")
        except Exception:
            pass

    # 避免重复订单行导致后续膨胀：对相同 order_id 的行保留第一条
    ord_df = ord_df.sort_index().drop_duplicates(subset=["order_id"], keep="first").copy()

    # 关键合并：现在右表键唯一，可安全 m:1
    ord_df = ord_df.merge(
        prod_attr_unique,
        on=["product_code","client_code"], how="left", validate="m:1"
    )

    # 生产窗口
    ord_df["latest_finish_date"]  = pd.to_datetime(ord_df["due_date"]) - pd.Timedelta(days=CONFIG["pack_days"]+CONFIG["ship_days"])
    ord_df["earliest_start_date"] = CONFIG["start_date"]

    # 配件需求（重量来自配件表，方便其它模块使用）
    if ("名称" in acc.columns) and ("重量（克）" in acc.columns):
        acc_map = acc.set_index("名称")["重量（克）"].to_dict()
        ring_w = float(acc_map.get("散热环", 0.0))
        stand_w = float(acc_map.get("支架", 0.0))
    else:
        ring_w, stand_w = 0.0, 0.0

    ord_df["need_ring_qty"]  = np.where(ord_df.get("need_ring", False), ord_df["qty"], 0.0)
    ord_df["need_stand_qty"] = np.where(ord_df.get("need_stand", False), ord_df["qty"], 0.0)

    return ord_df, clients, assets, products, materials, acc

if __name__ == "__main__":
    od, *_ = load_and_prepare()
    print("订单数:", len(od))
    print("时间范围:", od["earliest_start_date"].min(), "→", od["latest_finish_date"].max())
