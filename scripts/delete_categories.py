# -*- coding: utf-8 -*-
import os
# 删除 10 类消费/服务企业(餐饮住宿/旅游/教育/家政/美容/殡葬/宠物/婚纱摄影/花店/食品饮料)
import pymysql

REG = ("餐饮|酒店|饭店|旅馆|民宿|住宿|酒楼|火锅|烧烤|咖啡|奶茶|烘焙|茶饮"
       "|旅游|旅行社|景区|度假|游乐园|滑雪|漂流"
       "|教育|培训|学校|幼儿园|托育|驾校|艺考|留学|辅导|家教"
       "|家政|保洁|月嫂|保姆|干洗|洗衣|搬家公司"
       "|美容|美发|美甲|足浴|洗浴|推拿|按摩|养生|减肥|植发|纹身|洗脚"
       "|殡葬|公墓|墓园|寿衣"
       "|宠物|宠物医院|宠物食品|宠物美容|宠物用品"
       "|婚纱|婚庆|写真|影楼"
       "|花店|花卉|绿植|苗木|园艺"
       "|食品|饮料|白酒|啤酒|黄酒|红酒|葡萄酒|乳业|粮油|调味品|零食|屠宰|肉制品|水产|果蔬|糖果|蜜饯")

cfg = dict(host="8.141.5.67", port=3306, user="root", password=os.getenv("DB_PASSWORD"),
           database="business_data", charset="utf8mb4")
T = "ent_industry_class_chain_scope_20260928_converted"
BK = "_backup_categories_20261010"

conn = pymysql.connect(**cfg)
cur = conn.cursor()
cur.execute(f"SELECT COUNT(*) FROM {T}")
print(f"底表总行数 = {cur.fetchone()[0]}")
cur.execute(f"SELECT COUNT(*) FROM {T} WHERE company_name REGEXP %s", (REG,))
print(f"匹配删除词 = {cur.fetchone()[0]}")

cur.execute(f"DROP TABLE IF EXISTS {BK}")
cur.execute(f"CREATE TABLE {BK} AS SELECT * FROM {T} WHERE company_name REGEXP %s", (REG,))
conn.commit()
cur.execute(f"SELECT COUNT(*) FROM {BK}")
print(f"备份行数 = {cur.fetchone()[0]}")

cur.execute(f"DELETE FROM {T} WHERE company_name REGEXP %s", (REG,))
conn.commit()
print(f"删除行数 = {cur.rowcount}")

cur.execute(f"SELECT COUNT(*) FROM {T}")
print(f"删除后底表总行数 = {cur.fetchone()[0]}")
cur.close(); conn.close()
print("完成")