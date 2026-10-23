# -*- coding: utf-8 -*-
import os
import pymysql, pandas as pd
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)
DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4')
conn = pymysql.connect(**DB); cur = conn.cursor()
f = '/tmp/工业元宇宙_企业名单.xlsx'
chain = '工业元宇宙'
log(f"读 {chain} xlsx")
df_fin = pd.read_excel(f, sheet_name='最终名单')
df_comp = pd.read_excel(f, sheet_name='企业表')
log(f"  最终名单 {len(df_fin)}, 企业表 {len(df_comp)}")
cur.execute("DELETE FROM company_nodes_finallist WHERE industry_name=%s", (chain,))
cur.execute("DELETE FROM company_list_output WHERE industry_name=%s", (chain,))
conn.commit()
# finallist
rows = []
for _, r in df_fin.iterrows():
    name = r['企业名称']
    if name is None or str(name).strip() in ('', 'nan'): continue
    try: nl = int(r['节点层级']) if r['节点层级'] is not None else 0
    except: nl = 0
    rows.append((str(name).strip(), chain, str(r['节点'] or ''), nl,
                 str(r['父节点'] or '') if r['父节点'] is not None else '',
                 str(r['置信度'] or '') if r['置信度'] is not None else ''))
for i in range(0, len(rows), 5000):
    cur.executemany("INSERT IGNORE INTO company_nodes_finallist (company_name,industry_name,nodes,node_level,parent_node,score) VALUES (%s,%s,%s,%s,%s,%s)", rows[i:i+5000])
    conn.commit()
log(f"  finallist 插入 {len(rows)}")
# list_output
lvl_cols = ['层级1','层级2','层级3','层级4','层级5','层级6']
orows = []
for _, r in df_comp.iterrows():
    sup = r['供应商']
    if sup is None or str(sup).strip() in ('', 'nan'): continue
    vals = [str(r[c] if c in r and r[c] is not None and str(r[c]).lower()!='nan' else '') for c in lvl_cols]
    orows.append([str(sup).strip(), chain] + vals)
for i in range(0, len(orows), 5000):
    cur.executemany("INSERT IGNORE INTO company_list_output (供应商,industry_name,层级1,层级2,层级3,层级4,层级5,层级6) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", orows[i:i+5000])
    conn.commit()
log(f"  list_output 插入 {len(orows)}")
cur.close(); conn.close()
log("===== 工业元宇宙导入完成 =====")