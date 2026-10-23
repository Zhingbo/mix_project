# -*- coding: utf-8 -*-
# 1) step7 9999 改为只对白名单
# 2) 删除当前生命健康结果里"明显非健康"企业(非健康关键词 且 不含健康词)
import os
import pymysql

# ----- 1) 修 step7 -----
p = "step7_split_results.py"
s = open(p, encoding="utf-8").read()
old = '        update_sql = f"UPDATE {temp_table} SET score = \'9999\' WHERE industry_name = %s"\n        cursor.execute(update_sql, (industry_name,))\n        conn.commit()\n        print(f"已更新 score 为 9999")'
new = ('        update_sql = f"UPDATE {temp_table} SET score = \'1\' WHERE industry_name = %s"\n'
       '        cursor.execute(update_sql, (industry_name,))\n'
       '        conn.commit()\n'
       '        update_sql2 = f"""\nUPDATE {temp_table} t\nJOIN whitelist_company w ON t.company_name = w.company_name AND w.industry_name = %s\nSET t.score = \'9999\'"""\n'
       '        cursor.execute(update_sql2, (industry_name,))\n'
       '        conn.commit()\n'
       '        print(f"白名单企业已标 9999，其它=1")')
if old in s:
    s = s.replace(old, new)
    open(p, "w", encoding="utf-8").write(s)
    print("step7 已改为: 9999 仅白名单, 其它=1")
else:
    print("step7 未找到目标代码, 跳过(需人工确认)")

# ----- 2) 删除非健康 -----
NON_HEALTH = ("保险|证券|银行|融资租赁|典当|担保|小额贷款|汽车|整车|汽配|轮胎|光伏|太阳能|储能|"
              "风电|氢能|燃料电池|半导体|集成电路|物流|快递|电商|电子商务|游戏|传媒|影视|直播|"
              "出版|矿业|矿山|钢铁|煤炭|石油|天然气|冶金|食品|饮料|白酒|啤酒|粮油|饲料|屠宰|"
              "养殖|种养殖|纺织|服装|面料|印染|皮革|鞋业|五金|模具|机床|铸造|轴承|减速机|液压|"
              "阀门|建材|水泥|照明|家电|家具|厨具|服饰|饰品|商贸|旅游|餐饮|酒店")
HEALTH = ("医药|医疗|医|药|生物|健康|康复|诊断|医院|诊所|基因|细胞|中药材|保健|卫生|口腔|眼科|"
          "疫苗|器械|制药|药业")

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
OUT = [("company_nodes_mapping", "company_name"), ("company_nodes_info_result", "company_name"),
       ("company_nodes_info_split", "company_name"), ("company_nodes_final", "company_name"),
       ("company_nodes_finallist", "company_name"), ("company_list_output", "供应商")]

conn = pymysql.connect(**cfg)
cur = conn.cursor()
WH = "industry_name='生命健康' AND {col} REGEXP '{NH}' AND {col} NOT REGEXP '{H}'"

total_del = 0
for t, col in OUT:
    # 备份(本次删除的行)
    cur.execute(f"DROP TABLE IF EXISTS _bk_nonhealth_20260929")
    cur.execute(f"CREATE TABLE _bk_nonhealth_20260929 AS SELECT * FROM {t} WHERE {WH.format(col=col, NH=NON_HEALTH, H=HEALTH)}")
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM _bk_nonhealth_20260929")
    bk = cur.fetchone()[0]
    cur.execute(f"DELETE FROM {t} WHERE {WH.format(col=col, NH=NON_HEALTH, H=HEALTH)}")
    conn.commit()
    print(f"{t}.{col}: 删除 {cur.rowcount} 条 (备份 {bk})")
    total_del += cur.rowcount

print(f"\n共删除非健康 = {total_del}")
cur.execute("SELECT company_name FROM _bk_nonhealth_20260929 LIMIT 40")
print("--- 删除样例(最后一张表的备份) ---")
for r in cur.fetchall():
    print("  ", r[0])
cur.close(); conn.close()
print("完成")