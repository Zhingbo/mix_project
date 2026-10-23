# -*- coding: utf-8 -*-
import os
# 清理磁盘: 删临时/源/旧生产表 + 日期后缀的旧备份表; 保留在用表
import pymysql, re

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
conn = pymysql.connect(**cfg)
cur = conn.cursor()

# 在用表(保留)
KEEP = {
    "ent_industry_class_chain_scope_20260928_converted",
    "chain_needcomp", "chain_need_company", "nodes_industry_mapping", "mapping_industry_info_new", "industry_structure_output",
    "company_nodes_mapping", "company_nodes_mapping_temp", "company_nodes_top",
    "company_nodes_info_result", "company_nodes_info_split", "company_nodes_final",
    "company_nodes_finallist", "company_list_output", "whitelist_company",
}

def is_backup(name):
    # 管道表的旧备份(日期后缀), 排除在用名
    pats = [
        ("company_nodes_finallist", "company_nodes_finallist"),
        ("company_nodes_mapping", "company_nodes_mapping"),
        ("company_nodes_info_result", "company_nodes_info_result"),
        ("company_nodes_top", "company_nodes_top"),
        ("company_nodes_results_final", None),
        ("company_nodes_upload_temp", None),
        ("chain_needcomp", "chain_needcomp"),
        ("chain_need_company", None),
        ("nodes_industry_mapping", "nodes_industry_mapping"),
        ("industry_chain_topcompanies", None),
        ("topcompany_filtered", None),
        ("industry_structure_output", "industry_structure_output"),
    ]
    for prefix, base in pats:
        if name.startswith(prefix):
            if base and name == base:
                return False
            return True
    return False

cur.execute("SHOW TABLES")
all_tables = [r[0] for r in cur.fetchall()]

to_drop = []
for t in all_tables:
    if t in ("company_nodes_merge_temp", "ent_industry_class_chain_scope_20260928",
             "ent_industry_class_new_converted"):
        to_drop.append(t)
    elif t not in KEEP and is_backup(t):
        to_drop.append(t)

print(f"待删 {len(to_drop)} 张表:")
for t in to_drop:
    print("  ", t)

confirm = len(to_drop)
for t in to_drop:
    cur.execute(f"DROP TABLE IF EXISTS `{t}`")
    conn.commit()
print(f"\n已删除 {confirm} 张表")

import subprocess
print("--- 磁盘 ---")
print(subprocess.getoutput("df -h / | tail -1"))

cur.close(); conn.close()
print("完成")