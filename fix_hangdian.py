# -*- coding: utf-8 -*-
import os
# 单独给"大飞机->航电系统"节点直配企业: 按公司名关键词从活跃底表捞取
import pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()

IND = '大飞机'
NODE = '航电系统'
PARENT = '机载设备'
GRAND = '产业链中游'
KEYWORDS = ['航电', '航空电子', '机载电子', '飞控', '飞行控制', '惯导', '惯性导航']

# 1. 从活跃底表捞匹配公司
where = " OR ".join(["COALESCE(company_name_full, company_name) LIKE %s"] * len(KEYWORDS))
sql = f"SELECT COALESCE(company_name_full, company_name) AS cn, credit_code FROM ent_industry_class_chain_scope_20260928_converted WHERE {where}"
params = tuple("%" + k + "%" for k in KEYWORDS)
log("查询航电系统关键词公司...")
cur.execute(sql, params)
rows = cur.fetchall()
log(f"  底表关键词命中: {len(rows)} 家 (去重前)")

# 去重
seen = {}
for cn, cc in rows:
    if cn and cn.strip() and cn not in seen:
        seen[cn] = cc
log(f"  去重后: {len(seen)} 家")

# 2. 排除已在大飞机 finallist 里的公司(避免重复挂)
cur.execute("SELECT company_name FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
existing = set(r[0] for r in cur.fetchall())
new = {cn: cc for cn, cc in seen.items() if cn not in existing}
log(f"  排除已在大飞机名单后的新增: {len(new)} 家")

# 3. 插入 mapping / finallist / list_output
FULL = '电子信息|电子设备|电子控制设备'
REASON = '航电系统关键词直配(单独补挂)'
inserted = 0
for cn, cc in new.items():
    try:
        cur.execute("""INSERT IGNORE INTO company_nodes_mapping
          (company_name, credit_code, certainty, industry_name, nodes, name, level, full_name, reason)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (cn, cc, '4', IND, NODE, NODE, '3', FULL, REASON))
        cur.execute("""INSERT IGNORE INTO company_nodes_finallist
          (company_name, industry_name, nodes, node_level, parent_node, score)
          VALUES (%s,%s,%s,%s,%s,%s)""",
          (cn, IND, NODE, 3, PARENT, '4'))
        cur.execute("""INSERT IGNORE INTO company_list_output
          (层级1, 层级2, 层级3, 供应商, industry_name)
          VALUES (%s,%s,%s,%s,%s)""",
          (GRAND, PARENT, NODE, cn, IND))
        inserted += 1
    except Exception as e:
        log(f"  跳过 {cn}: {e}")
conn.commit()
log(f"  实际新增插入: {inserted} 家")

# 4. 校验
cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s AND nodes=%s", (IND, NODE))
log(f"校验 航电系统 finallist: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (IND,))
log(f"校验 大飞机 finallist 总量: {cur.fetchone()[0]}")

cur.close(); conn.close()
log("===== 航电系统补挂完成 =====")