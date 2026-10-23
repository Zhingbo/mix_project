# -*- coding: utf-8 -*-
import os
# 对 9 条链统一剔除"明显无关"企业(按名称行业词)
# 合成生物用窄口径(食品/医药/生物是其下游, 不剔)
import pymysql

# 通用无关词(金融/地产/医疗机构/餐饮旅游/教育/食品纺织/文娱)
FULL = ("银行|证券|保险|典当|担保|融资租赁|小额贷款|信托|基金管理|期货|房地产|地产|物业|置业|"
        "医院|诊所|门诊|卫生院|口腔|牙科|眼科|骨科|妇幼|医药|医疗|医疗器械|大健康|康复|护理|养老|养生|"
        "餐饮|酒店|住宿|民宿|旅游|旅行社|教育|培训|学校|"
        "食品|饮料|酒业|乳业|粮油|养殖|饲料|屠宰|水产|茶|"
        "纺织|服装|皮革|鞋业|家纺|印染|"
        "游戏|传媒|影视|直播|出版|广告|动漫|零售|超市")

# 合成生物窄口径(只剔金融/地产/餐饮旅游/教育/文娱, 保留医药/食品/生物)
SYNBIO = ("银行|证券|保险|典当|担保|融资租赁|小额贷款|信托|基金管理|期货|房地产|地产|物业|置业|"
          "医院|诊所|门诊|卫生院|口腔|牙科|眼科|骨科|妇幼|"
          "餐饮|酒店|住宿|民宿|旅游|旅行社|教育|培训|学校|"
          "游戏|传媒|影视|直播|出版|广告|动漫|零售|超市")

CHAINS = ["工业元宇宙", "工业软件", "人工智能", "AI智能算力", "光伏产业", "储能", "氢能产业", "大飞机", "合成生物"]

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

print("=== 各链待删统计(去重) & 样例 ===")
for ch in CHAINS:
    reg = SYNBIO if ch == "合成生物" else FULL
    cur.execute("SELECT COUNT(DISTINCT company_name) FROM company_nodes_finallist WHERE industry_name=%s AND company_name REGEXP %s", (ch, reg))
    n = cur.fetchone()[0]
    cur.execute("SELECT DISTINCT company_name FROM company_nodes_finallist WHERE industry_name=%s AND company_name REGEXP %s LIMIT 4", (ch, reg))
    samples = [r[0] for r in cur.fetchall()]
    print(f"\n[{ch}] 待删 {n} 家")
    for s in samples:
        print(f"    {s}")

print("\n=== 执行删除 ===")
tot = 0
for ch in CHAINS:
    reg = SYNBIO if ch == "合成生物" else FULL
    for t, col in OUT:
        cur.execute(f"DELETE FROM {t} WHERE industry_name=%s AND {col} REGEXP %s", (ch, reg))
        conn.commit()
        tot += cur.rowcount
print(f"共删除 {tot} 行")

print("\n=== 各链 finallist 剩余 ===")
for ch in CHAINS:
    cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (ch,))
    print(f"  {ch}: {cur.fetchone()[0]}")

cur.close(); conn.close()
print("完成")