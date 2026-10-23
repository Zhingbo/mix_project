# -*- coding: utf-8 -*-
# 导出 9 条链 -> 3 sheet xlsx(最终名单/结构表/企业表), 并在企业表携带成立时间(来自阿里云RDS)
import pymysql
import pandas as pd
import os
from datetime import datetime

CHAINS = ["工业元宇宙", "工业软件", "人工智能", "AI智能算力",
          "光伏产业", "储能", "氢能产业", "大飞机", "合成生物"]
MAXR = 1000000
BATCH = 500

LOCAL = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
             database="business_data", charset="utf8mb4", connect_timeout=60)
RDS = dict(host="rm-2zej668f34v6xr91wdo.mysql.rds.aliyuncs.com", port=3306,
           user="root", password=os.getenv("DB_PASSWORD_ZS"), database="zs_digital_staff_db",
           charset="utf8mb4", connect_timeout=60, read_timeout=60)
RDS_TABLE = "enterprise_establish_time_chain_scope_20260928"

OUTDIR = "/root/mix_project/产业链导出_20261012"
os.makedirs(OUTDIR, exist_ok=True)


def build_est_map(companies):
    """把一批企业名在RDS里匹配成立时间, 返回 {company: (establish_time, establish_year)}"""
    m = {}
    if not companies:
        return m
    rdb = pymysql.connect(**RDS)
    rc = rdb.cursor()
    for i in range(0, len(companies), BATCH):
        b = companies[i:i + BATCH]
        ph = ",".join(["%s"] * len(b))
        rc.execute(f"SELECT company_name, establish_time, establish_year "
                   f"FROM {RDS_TABLE} WHERE company_name IN ({ph})", b)
        for n, t, y in rc.fetchall():
            m[n] = (t, y)
    rc.close(); rdb.close()
    return m


def fmt(t):
    if t is None:
        return ""
    if hasattr(t, "strftime"):
        return t.strftime("%Y-%m-%d")
    return str(t).strip()[:10]


def main():
    conn = pymysql.connect(**LOCAL)
    print(f"开始导出 {len(CHAINS)} 条链 -> {OUTDIR}")
    for ch in CHAINS:
        print(f"\n=== {ch} ===")
        # 1) 最终名单
        df_fin = pd.read_sql(
            "SELECT company_name AS 企业名称, industry_name AS 产业链, nodes AS 节点, "
            "node_level AS 节点层级, parent_node AS 父节点, score AS 置信度 "
            "FROM company_nodes_finallist WHERE industry_name=%s ORDER BY id LIMIT %s",
            conn, params=(ch, MAXR))
        # 2) 结构表
        df_struct = pd.read_sql(
            "SELECT id AS 编码, nodes AS 产业环节, parent_id AS 父级id, node_level AS 级别 "
            "FROM chain_needcomp WHERE chain_name=%s",
            conn, params=(ch,))
        # 3) 企业表(含成立时间)
        df_company = pd.read_sql(
            "SELECT 层级1, 层级2, 层级3, 供应商 FROM company_list_output "
            "WHERE industry_name=%s ORDER BY id LIMIT %s",
            conn, params=(ch, MAXR))

        companies = [str(x) for x in df_company["供应商"].tolist() if x]
        uniq = list(dict.fromkeys(companies))
        print(f"  企业表 {len(df_company)} 行, 去重供应商 {len(uniq)} 个, 开始匹配成立时间...")
        emap = build_est_map(uniq)

        def match_est(sup):
            if not sup:
                return ("", "", "未匹配")
            r = emap.get(str(sup))
            if r and (r[0] or r[1]):
                return (fmt(r[0]), r[1] or "", "已匹配")
            return ("", "", "未匹配")

        est_cols = df_company["供应商"].map(match_est)
        df_company["成立时间"] = [x[0] for x in est_cols]
        df_company["注册年份"] = [x[1] for x in est_cols]
        df_company["匹配状态"] = [x[2] for x in est_cols]
        matched = (df_company["匹配状态"] == "已匹配").sum()
        print(f"  匹配到成立时间: {matched} / {len(df_company)}")

        f = os.path.join(OUTDIR, f"{ch}_企业名单.xlsx")
        with pd.ExcelWriter(f, engine='openpyxl') as w:
            df_fin.to_excel(w, sheet_name='最终名单', index=False)
            df_struct.to_excel(w, sheet_name='结构表', index=False)
            df_company.to_excel(w, sheet_name='企业表', index=False)
        print(f"  已导出: {f} (最终名单{len(df_fin)}, 结构{len(df_struct)}, 企业表{len(df_company)})")

    conn.close()
    print(f"\n全部完成. 目录: {OUTDIR}")


if __name__ == "__main__":
    main()