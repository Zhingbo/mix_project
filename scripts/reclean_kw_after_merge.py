# -*- coding: utf-8 -*-
import os
# 合并后又带回底表的 物流/10类 企业: 备份后删除(扣除养生大健康), 并删掉合并备份表
import pymysql

cfg = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
           database='business_data', charset='utf8mb4')
T = 'ent_industry_class_chain_scope_20260928_converted'
BK = '_backup_reclean_kw_20261012'

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

cond = f"(company_name REGEXP %s OR company_name REGEXP %s) AND company_name NOT REGEXP %s"

conn = pymysql.connect(**cfg)
cur = conn.cursor()
cur.execute(f"SELECT COUNT(*) FROM {T}")
print("删除前底表 =", cur.fetchone()[0])
cur.execute(f"SELECT COUNT(*) FROM {T} WHERE {cond}", (LOG, CAT, EXCL))
print("待删(物流+10类扣养生) =", cur.fetchone()[0])

cur.execute(f"DROP TABLE IF EXISTS {BK}")
cur.execute(f"CREATE TABLE {BK} AS SELECT * FROM {T} WHERE {cond}", (LOG, CAT, EXCL))
conn.commit()
cur.execute(f"SELECT COUNT(*) FROM {BK}")
print("已备份 =", cur.fetchone()[0])

cur.execute(f"DELETE FROM {T} WHERE {cond}", (LOG, CAT, EXCL))
conn.commit()
print("已删除 =", cur.rowcount)

cur.execute(f"SELECT COUNT(*) FROM {T}")
print("删除后底表 =", cur.fetchone()[0])

# 删掉合并备份表(用户明确要求)
cur.execute("DROP TABLE IF EXISTS _backup_new_overlap_20261012")
conn.commit()
print("已删除合并备份表 _backup_new_overlap_20261012")
cur.close(); conn.close()
print("done")
