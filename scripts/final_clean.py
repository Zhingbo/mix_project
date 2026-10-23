# -*- coding: utf-8 -*-
import os
# 删除生命健康输出表里的: 纯英文外企 + 明显非健康(与"10外企+114非健康"一致)
# 并从底表删除"物业"企业
import pymysql

NONHEALTH = ["保险","证券","银行","金融","融资租赁","典当","担保","信托","基金",
"汽车","整车","轮胎","汽配","光伏","太阳能","储能","电池","风电","氢能","燃料电池","新能源",
"半导体","芯片","集成电路","光模块","通信","物流","快递","仓储","货运","电商","电子商务","游戏","传媒","影视","直播","出版","广告","网络科技","互联网",
"矿业","矿山","钢铁","煤炭","石油","天然气","冶金","焦化","水泥","建材","混凝土","装修","照明","家电","卫浴","瓷砖",
"食品","饮料","酒业","酿酒","白酒","啤酒","贡酒","黄酒","粮油","养殖","饲料","屠宰","乳业","水产","茶业","米业","面业",
"纺织","服装","面料","印染","皮革","鞋业","制衣","针织","家纺","服饰","饰品",
"五金","模具","机床","铸造","焊接","轴承","减速机","液压","阀门","锻压","齿轮","钣金","冲压",
"家具","厨具","商贸","旅游","餐饮","酒店","房地产","置业","物业","教育","培训"]

HOME = ["医药","医疗","医","药","生物","健康","康复","诊断","医院","诊所","基因","细胞","中药材","保健","卫生","口腔","眼科","疫苗","器械","制药","药业","养生","护理","养老"]

def is_foreign(n):
    return n and all(not ('\u4e00' <= c <= '\u9fff') for c in n)

def is_nonhealth(n):
    return any(k in n for k in NONHEALTH) and not any(k in n for k in HOME)

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
BASE = "ent_industry_class_chain_scope_20260928_converted"
OUT = [("company_nodes_mapping","company_name"), ("company_nodes_info_result","company_name"),
       ("company_nodes_info_split","company_name"), ("company_nodes_final","company_name"),
       ("company_nodes_finallist","company_name"), ("company_list_output","供应商")]

conn = pymysql.connect(**cfg)
cur = conn.cursor()

cur.execute("SELECT DISTINCT company_name FROM company_nodes_finallist WHERE industry_name='生命健康'")
names = [r[0] for r in cur.fetchall() if r[0]]
foreign = [n for n in names if is_foreign(n)]
nonhealth = [n for n in names if is_nonhealth(n)]
to_del = list(dict.fromkeys(foreign + nonhealth))
print(f"外企={len(foreign)}, 非健康={len(nonhealth)}, 合计待删={len(to_del)}")

cur.execute("DROP TABLE IF EXISTS _tmp_del_names")
cur.execute("CREATE TABLE _tmp_del_names (name VARCHAR(255) COLLATE utf8mb4_unicode_ci PRIMARY KEY)")
cur.executemany("INSERT IGNORE INTO _tmp_del_names VALUES (%s)", [(n,) for n in to_del])
conn.commit()

cur.execute("DROP TABLE IF EXISTS _bk_finalclean_20260929")
cur.execute("""CREATE TABLE _bk_finalclean_20260929 AS
    SELECT * FROM company_nodes_finallist WHERE industry_name='生命健康'
    AND company_name IN (SELECT name FROM _tmp_del_names)""")
conn.commit()
cur.execute("SELECT COUNT(*) FROM _bk_finalclean_20260929")
print(f"finallist 备份行数 = {cur.fetchone()[0]}")

for t, col in OUT:
    cur.execute(f"""DELETE t FROM {t} t JOIN _tmp_del_names d ON t.{col} COLLATE utf8mb4_unicode_ci = d.name
                    WHERE t.industry_name='生命健康'""")
    conn.commit()
    print(f"  {t}.{col} 删除 = {cur.rowcount}")

# 底表删物业
cur.execute("DROP TABLE IF EXISTS _bk_property_20260929")
cur.execute(f"CREATE TABLE _bk_property_20260929 AS SELECT * FROM {BASE} WHERE company_name LIKE '%物业%'")
conn.commit()
cur.execute("SELECT COUNT(*) FROM _bk_property_20260929")
print(f"底表物业(备份) = {cur.fetchone()[0]}")
cur.execute(f"DELETE FROM {BASE} WHERE company_name LIKE '%物业%'")
conn.commit()
print(f"底表删除物业 = {cur.rowcount}")

cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name='生命健康'")
print(f"删除后 finallist 总行数 = {cur.fetchone()[0]}")

cur.close(); conn.close()
print("完成")