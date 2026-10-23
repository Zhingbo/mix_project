# -*- coding: utf-8 -*-
import os
# 底表企业名称按"消费/服务类目"统计
import pymysql

CATEGORIES = [
    ("金融", "银行|证券|保险|典当|担保|小额贷款|融资租赁|信托|期货|基金管理|财富管理|支付"),
    ("地产", "房地产|地产|物业|置业|房产|售楼|中介"),
    ("餐饮住宿", "餐饮|酒店|饭店|旅馆|民宿|住宿|酒楼|火锅|烧烤|咖啡|奶茶|烘焙|茶饮"),
    ("旅游", "旅游|旅行社|景区|度假|游乐园|滑雪|漂流"),
    ("教育", "教育|培训|学校|幼儿园|托育|驾校|艺考|留学|辅导|家教"),
    ("文娱", "游戏|直播|短视频|影视|电影院|传媒|出版|广告|动漫|网吧|剧本杀|KTV|酒吧|娱乐|演艺|经纪"),
    ("电商", "电商|电子商务|网店|淘宝|天猫|网商"),
    ("物流", "物流|快递|货运|仓储|搬家|配送|供应链"),
    ("家政", "家政|保洁|月嫂|保姆|干洗|洗衣|搬家公司"),
    ("美容", "美容|美发|美甲|SPA|足浴|洗浴|推拿|按摩|养生|减肥|植发|纹身|洗脚"),
    ("殡葬", "殡葬|公墓|墓园|寿衣"),
    ("宠物", "宠物|宠物医院|宠物食品|宠物美容|宠物用品"),
    ("婚纱摄影", "婚纱|婚庆|写真|影楼"),
    ("花店", "花店|花卉|绿植|苗木|园艺"),
    ("食品饮料", "食品|饮料|白酒|啤酒|黄酒|红酒|葡萄酒|乳业|粮油|调味品|零食|屠宰|肉制品|水产|果蔬|糖果|蜜饯"),
]

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
T = "ent_industry_class_chain_scope_20260928_converted"

# 构造单条条件聚合 SQL
sums = "".join(f"SUM(company_name REGEXP '{re}') AS `{name}`" for name, re in CATEGORIES)
# 注意: SUM 之间要逗号, 上面写法缺逗号, 重新构造
parts = []
for name, re in CATEGORIES:
    # 转义单引号(关键词里无单引号)
    parts.append(f"SUM(company_name REGEXP '{re}') AS `{name}`")
sql = "SELECT " + ",\n       ".join(parts) + f"\nFROM {T}"

conn = pymysql.connect(**cfg)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM %s" % T)
total = cur.fetchone()[0]
print(f"底表总行数: {total}")
cur.execute(sql)
row = cur.fetchone()
cols = [d[0] for d in cur.description]
for c, v in zip(cols, row):
    print(f"  {c}: {v}")
cur.close(); conn.close()
print("完成")