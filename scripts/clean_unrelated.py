# -*- coding: utf-8 -*-
import os
# 剔除 工业元宇宙/工业软件/人工智能 里明显无关的企业(按名称行业词)
import pymysql

WRONG_RE = ("银行|证券|保险|典当|担保|融资租赁|小额贷款|房地产|地产|物业|置业|"
            "医院|诊所|门诊|卫生院|口腔|牙科|眼科|骨科|妇幼|医药|医疗|医疗器械|大健康|康复|护理|养老|养生|"
            "餐饮|酒店|住宿|旅游|旅行社|"
            "食品|饮料|酒业|乳业|粮油|养殖|饲料|屠宰|"
            "纺织|服装|皮革|鞋业|家纺")

CH = ["工业元宇宙", "工业软件", "人工智能"]
OUT = [("company_nodes_finallist", "company_name"),
       ("company_list_output", "供应商"),
       ("company_nodes_final", "company_name"),
       ("company_nodes_mapping", "company_name"),
       ("company_nodes_info_result", "company_name"),
       ("company_nodes_info_split", "company_name")]

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
conn = pymysql.connect(**cfg)
cur = conn.cursor()

# 统计待删(以 finallist 去重为准)
print("=== 待删统计(按 finallist 去重) ===")
for ch in CH:
    cur.execute("SELECT COUNT(DISTINCT company_name) FROM company_nodes_finallist WHERE industry_name=%s AND company_name REGEXP %s",
                (ch, WRONG_RE))
    print(f"  {ch}: {cur.fetchone()[0]} 家")

# 样例(仅工业元宇宙 展示8条)
print("=== 工业元宇宙 待删样例 ===")
cur.execute("SELECT DISTINCT company_name FROM company_nodes_finallist WHERE industry_name='工业元宇宙' AND company_name REGEXP %s LIMIT 8", (WRONG_RE,))
for r in cur.fetchall():
    print("  ", r[0])

# 执行删除
print("=== 执行删除 ===")
tot = 0
for ch in CH:
    for t, col in OUT:
        cur.execute(f"DELETE FROM {t} WHERE industry_name=%s AND {col} REGEXP %s", (ch, WRONG_RE))
        conn.commit()
        tot += cur.rowcount
        if cur.rowcount:
            print(f"  {t}.{col} ({ch}) 删 {cur.rowcount}")
print(f"\n共删除 {tot} 行")

# 删除后每个链 finallist 行数
print("=== 删除后 finallist 行数 ===")
for ch in CH:
    cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (ch,))
    print(f"  {ch}: {cur.fetchone()[0]}")

cur.close(); conn.close()
print("完成")