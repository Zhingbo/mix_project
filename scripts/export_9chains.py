# -*- coding: utf-8 -*-
import os
# 导出 9 条链 -> 3 sheet xlsx(最终名单/结构表/企业表), 超100万截断, 放统一文件夹
import pymysql, pandas as pd, os

CHAINS = ["工业元宇宙", "工业软件", "人工智能", "AI智能算力",
          "光伏产业", "储能", "氢能产业", "大飞机", "合成生物"]
MAXR = 1000000

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
conn = pymysql.connect(**cfg)

outdir = "/root/mix_project/产业链导出_20261008"
os.makedirs(outdir, exist_ok=True)

for ch in CHAINS:
    print(f"=== 导出 {ch} ===")
    df_fin = pd.read_sql(
        "SELECT company_name AS 企业名称, industry_name AS 产业链, nodes AS 节点, "
        "node_level AS 节点层级, parent_node AS 父节点, score AS 置信度 "
        "FROM company_nodes_finallist WHERE industry_name=%s ORDER BY id LIMIT %s",
        conn, params=(ch, MAXR))

    df_struct = pd.read_sql(
        "SELECT id AS 编码, nodes AS 产业环节, parent_id AS 父级id, node_level AS 级别 "
        "FROM chain_needcomp WHERE chain_name=%s",
        conn, params=(ch,))

    df_company = pd.read_sql(
        "SELECT 层级1, 层级2, 层级3, 供应商 FROM company_list_output "
        "WHERE industry_name=%s ORDER BY id LIMIT %s",
        conn, params=(ch, MAXR))

    f = os.path.join(outdir, f"{ch}_企业名单.xlsx")
    with pd.ExcelWriter(f, engine='openpyxl') as w:
        df_fin.to_excel(w, sheet_name='最终名单', index=False)
        df_struct.to_excel(w, sheet_name='结构表', index=False)
        df_company.to_excel(w, sheet_name='企业表', index=False)
    print(f"  已导出: {f}  (最终名单{len(df_fin)}行, 结构{len(df_struct)}行, 企业表{len(df_company)}行)")

conn.close()
print("\n完成。目录:", outdir)