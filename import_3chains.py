# -*- coding: utf-8 -*-
import os
import pymysql, pandas as pd, sys
from datetime import datetime

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4')

CHAINS = [
    ('AI智能算力', '/tmp/AI智能算力_企业名单.xlsx'),
    ('人工智能', '/tmp/人工智能_企业名单.xlsx'),
    ('工业元宇宙', '/tmp/工业元宇宙_企业名单.xlsx'),
]

def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

conn = pymysql.connect(**DB)
cur = conn.cursor()

for chain, f in CHAINS:
    log(f"===== {chain}: 读xlsx =====")
    df_fin = pd.read_excel(f, sheet_name='最终名单')
    df_comp = pd.read_excel(f, sheet_name='企业表')
    log(f"  最终名单 {len(df_fin)} 行, 企业表 {len(df_comp)} 行")

    # 清空该链旧数据(安全起见)
    cur.execute("DELETE FROM company_nodes_finallist WHERE industry_name=%s", (chain,))
    cur.execute("DELETE FROM company_list_output WHERE industry_name=%s", (chain,))
    conn.commit()
    log(f"  已清空 {chain} 旧数据")

    # ---- finallist 导入 ----
    # 列: 企业名称,产业链,节点,节点层级,父节点,置信度
    cols_fin = ['企业名称','产业链','节点','节点层级','父节点','置信度']
    rows_fin = []
    for _, r in df_fin.iterrows():
        name = r['企业名称']
        if name is None or str(name).strip() == '' or str(name).strip().lower() == 'nan':
            continue
        nl = r['节点层级']
        try:
            nl = int(nl) if nl is not None else 0
        except Exception:
            nl = 0
        rows_fin.append((str(name).strip(), chain, str(r['节点'] or ''), nl,
                         str(r['父节点'] or '') if r['父节点'] is not None else '',
                         str(r['置信度'] or '') if r['置信度'] is not None else ''))
    # 批量插入 finallist
    B = 5000
    for i in range(0, len(rows_fin), B):
        cur.executemany(
            "INSERT IGNORE INTO company_nodes_finallist "
            "(company_name, industry_name, nodes, node_level, parent_node, score) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            rows_fin[i:i+B])
        conn.commit()
    log(f"  finallist 已插入 {len(rows_fin)} 行")

    # ---- list_output 导入 ----
    # 列: 层级1..层级6, 供应商, 成立时间, 注册年份, 匹配状态
    lvl_cols = ['层级1','层级2','层级3','层级4','层级5','层级6']
    rows_out = []
    for _, r in df_comp.iterrows():
        sup = r['供应商']
        if sup is None or str(sup).strip() == '' or str(sup).strip().lower() == 'nan':
            continue
        vals = [r[c] if (c in r and r[c] is not None and str(r[c]).lower()!='nan') else '' for c in lvl_cols]
        rows_out.append([str(sup).strip(), chain] + [str(v) for v in vals])
    B = 5000
    for i in range(0, len(rows_out), B):
        cur.executemany(
            "INSERT IGNORE INTO company_list_output "
            "(供应商, industry_name, 层级1, 层级2, 层级3, 层级4, 层级5, 层级6) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            rows_out[i:i+B])
        conn.commit()
    log(f"  list_output 已插入 {len(rows_out)} 行")

cur.close(); conn.close()
log("===== 导入全部完成 =====")