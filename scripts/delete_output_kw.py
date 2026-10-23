# -*- coding: utf-8 -*-
import os
# 从输出表(最终名单/企业表)删除 物流 + 10类 关键词企业(保留"养生"大健康类), 先备份再删
import pymysql

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")

LOG = "运输|货运|配送|仓储|搬家|快递|快运|速递|货代|装箱"
CAT = ("餐饮|酒店|饭店|旅馆|民宿|住宿|酒楼|火锅|烧烤|咖啡|奶茶|烘焙|茶饮"
       "|旅游|旅行社|景区|度假|游乐园|滑雪|漂流"
       "|教育|培训|学校|幼儿园|托育|驾校|艺考|留学|辅导|家教"
       "|家政|保洁|月嫂|保姆|干洗|洗衣|搬家公司"
       "|美容|美发|美甲|足浴|洗浴|推拿|按摩|养生|减肥|植发|纹身|洗脚"
       "|殡葬|公墓|墓园|寿衣"
       "|宠物|宠物医院|宠物食品|宠物美容|宠物用品"
       "|婚纱|婚庆|写真|影楼"
       "|花店|花卉|绿植|苗木|园艺"
       "|食品|饮料|白酒|啤酒|黄酒|红酒|葡萄酒|乳业|粮油|调味品|零食|屠宰|肉制品|水产|果蔬|糖果|蜜饯")
EXCL = "养生(堂|药业|制药|医药|生物|保健|食品)"

# (表名, 企业名列[含反引号], 备份表名)
TASKS = [
    ("company_nodes_finallist", "company_name", "_backup_finallist_kw_20261010"),
    ("company_list_output",   "`供应商`",      "_backup_listoutput_kw_20261010"),
]

conn = pymysql.connect(**cfg)
cur = conn.cursor()
for T, COL, BK in TASKS:
    where = f"({COL} REGEXP %s OR {COL} REGEXP %s) AND {COL} NOT REGEXP %s"
    print(f"===== {T} ({COL}) =====")
    cur.execute(f"SELECT COUNT(*) FROM {T}")
    print("  删除前总数 =", cur.fetchone()[0])

    cur.execute(f"SELECT COUNT(*) FROM {T} WHERE {where}", (LOG, CAT, EXCL))
    print("  将删除(物流+10类-养生大健康) =", cur.fetchone()[0])

    cur.execute(f"DROP TABLE IF EXISTS {BK}")
    cur.execute(f"CREATE TABLE {BK} AS SELECT * FROM {T} WHERE {where}", (LOG, CAT, EXCL))
    conn.commit()
    cur.execute(f"SELECT COUNT(*) FROM {BK}")
    print("  已备份到", BK, "=", cur.fetchone()[0])

    cur.execute(f"DELETE FROM {T} WHERE {where}", (LOG, CAT, EXCL))
    conn.commit()
    print("  已删除行数 =", cur.rowcount)

    cur.execute(f"SELECT COUNT(*) FROM {T}")
    print("  删除后总数 =", cur.fetchone()[0])

cur.close(); conn.close()
print("全部完成")
