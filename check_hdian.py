# -*- coding: utf-8 -*-
import os
import pymysql, re
c = pymysql.connect(host="127.0.0.1", user="root", password=os.getenv("DB_PASSWORD"), database="business_data", charset="utf8mb4")
cur = c.cursor()
key = "电子信息|电子设备|电子控制设备"
cur.execute("SELECT industry_class_third FROM ent_industry_class_chain_scope_20260928_converted WHERE industry_class_third LIKE %s", ("%" + key + "%",))
strong = mid = weak = other = 0
for (ic,) in cur:
    # 找到 key 后面的值: key 后跟 冒号/逗号引号 再跟 中文值
    m = re.search(re.escape(key) + r"[^\u4e00-\u9fa5]*[\x27\u2018\u2019\"\u300c\u300e]\s*([\u4e00-\u9fa5]{1,3})", ic)
    if m:
        v = m.group(1)
    else:
        v = ""
    if "强" in v:
        strong += 1
    elif "中" in v:
        mid += 1
    elif "弱" in v:
        weak += 1
    else:
        other += 1
print(f"电子控制设备: 强{strong} 中{mid} 弱{weak} 其他{other}")
# 同时看机载设备另一个可能产业
cur.execute("SELECT COUNT(*) FROM ent_industry_class_chain_scope_20260928_converted WHERE industry_class_third LIKE %s AND industry_class_third LIKE %s", ("%电子控制设备%", "%强%"))
print("含'电子控制设备'且全文含'强':", cur.fetchone()[0])
cur.close(); c.close()