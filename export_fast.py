# -*- coding: utf-8 -*-
# 快模式导出: 不含成立时间(跳过RDS匹配), 秒级出 xlsx
import pymysql, pandas as pd
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)
DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4')
conn = pymysql.connect(**DB)
CHAINS = ['激光', '船舶海工', '工业元宇宙', '氢能产业', '低空经济']
import sys
if len(sys.argv) > 1:
    CHAINS = sys.argv[1:]
for ch in CHAINS:
    df_fin = pd.read_sql("SELECT company_name AS 企业名称, industry_name AS 产业链, nodes AS 节点, node_level AS 节点层级, parent_node AS 父节点, score AS 置信度 FROM company_nodes_finallist WHERE industry_name=%s ORDER BY id LIMIT 1000000", conn, params=(ch,))
    df_struct = pd.read_sql("SELECT id AS 编码, nodes AS 产业环节, parent_node AS 父节点, parent_id AS 父级id, node_level AS 级别 FROM industrial_chain.industrial_chain_structure WHERE chain_name=%s ORDER BY node_level, id", conn, params=(ch,))
    df_company = pd.read_sql("SELECT 层级1,层级2,层级3,层级4,层级5,层级6,供应商 FROM company_list_output WHERE industry_name=%s ORDER BY id LIMIT 1000000", conn, params=(ch,))
    df_company['成立时间'] = ''
    df_company['注册年份'] = ''
    df_company['匹配状态'] = '未匹配'
    f = f"/root/mix_project/产业链导出_快/{ch}_企业名单.xlsx"
    import os; os.makedirs('/root/mix_project/产业链导出_快', exist_ok=True)
    with pd.ExcelWriter(f, engine='openpyxl') as w:
        df_fin.to_excel(w, sheet_name='最终名单', index=False)
        df_struct.to_excel(w, sheet_name='结构表', index=False)
        df_company.to_excel(w, sheet_name='企业表', index=False)
    log(f"  ✅ {ch}: 最终{len(df_fin)}/结构{len(df_struct)}/企业{len(df_company)}")
conn.close()
log("快模式导出完成")