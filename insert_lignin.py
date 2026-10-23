# -*- coding: utf-8 -*-
import os
# 木质素企业入库: 在营→活跃底表, 非在营→非活跃底表, 行业挂 新材料|生物基材料|生物基高分子材料制造
import openpyxl, pymysql
from datetime import datetime
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

DB = dict(host='127.0.0.1', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=30,
          read_timeout=3600, write_timeout=3600)
conn = pymysql.connect(**DB)
cur = conn.cursor()

XLSX = '/root/mix_project/木质素_企业_经营范围_三级分类_20261023.xlsx'
ACTIVE_TBL = 'ent_industry_class_chain_scope_20260928_converted'
NONACTIVE_TBL = 'ent_industry_class_chain_scope_20260928_converted_nonactive_bak'

L1 = '新材料'
L2 = '新材料|生物基材料'
L3 = "{'新材料|生物基材料|生物基高分子材料制造': '强'}"

wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
ws = wb['Sheet1']
rows = list(ws.iter_rows(values_only=True))[1:]

seen = set()
a_ins = a_dup = n_ins = n_dup = 0
for r in rows:
    eid, name, status, zaiying, business, ind1, ind2, ind3code, ind3 = r
    name = (name or '').strip()
    if not name or name in seen:
        continue
    seen.add(name)
    business = (business or '').strip()
    ind_ori = f"{ind1}|{ind2}|{ind3}" if ind3 else f"{ind1}|{ind2}"
    is_active = (zaiying == '在营')
    if is_active:
        cur.execute(f"""INSERT IGNORE INTO {ACTIVE_TBL}
          (company_name, company_name_full, entity_id, business, industry,
           industry_class_first, industry_class_second, industry_class_third, certainty, version)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (name, name, str(eid or ''), business, ind_ori, L1, L2, L3, '4', '20261023'))
        if cur.rowcount:
            a_ins += 1
        else:
            a_dup += 1
    else:
        cur.execute(f"""INSERT IGNORE INTO {NONACTIVE_TBL}
          (company_name, company_name_full, entity_id, business, industry,
           industry_class_first, industry_class_second, industry_class_third, certainty, version, status_bucket)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (name, name, str(eid or ''), business, ind_ori, L1, L2, L3, '4', '20261023', status or '非在营'))
        if cur.rowcount:
            n_ins += 1
        else:
            n_dup += 1
conn.commit()
cur.close(); conn.close()

log(f"去重后处理 {len(seen)} 家")
log(f"活跃底表: 新增 {a_ins}, 已存在跳过 {a_dup}")
log(f"非活跃底表: 新增 {n_ins}, 已存在跳过 {n_dup}")
log("===== 木质素企业入库完成 =====")