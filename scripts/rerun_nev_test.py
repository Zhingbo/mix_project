# -*- coding: utf-8 -*-
import os
import requests, pymysql, time
from datetime import datetime
API="http://127.0.0.1:8001"
tok=requests.post(f"{API}/api/auth/login",json={"username":"admin","password":"admin123"},timeout=15).json()["access_token"]
H={"Authorization":f"Bearer {tok}"}
CH="新能源汽车"
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}",flush=True)

log("清空 step4-10")
r=requests.post(f"{API}/api/pipeline/delete_steps",json={"industry_name":CH,"steps":[4,5,6,7,8,9,10]},headers=H,timeout=120)
log(f"delete_steps HTTP {r.status_code}")

log("触发从 step4 重跑(force)")
t0=time.time()
r=requests.post(f"{API}/api/pipeline/process",json={"industry_name":CH,"start_step":4,"force":True},headers=H,stream=True,timeout=None)
last=""
for raw in r.iter_lines(decode_unicode=True):
    if raw and ("处理完成" in raw or "步骤10" in raw or "Traceback" in raw):
        log(f"  {raw[-160:]}")
log(f"SSE结束 耗时{time.time()-t0:.0f}s")

c=pymysql.connect(host='8.141.5.67',port=3306,user='root',password=os.getenv('DB_PASSWORD'),database='business_data',charset='utf8mb4')
cur=c.cursor()
for t,col in [('company_nodes_mapping','industry_name'),('company_nodes_finallist','industry_name'),('company_list_output','industry_name')]:
    cur.execute(f"SELECT COUNT(*) FROM {t} WHERE {col}=%s",(CH,)); print(f"{t} = {cur.fetchone()[0]}")
cur.execute("SELECT nodes,COUNT(*) FROM company_nodes_mapping WHERE industry_name=%s GROUP BY nodes ORDER BY 2 DESC",(CH,))
for row in cur.fetchall(): print(f"  {row[0]} = {row[1]}")
c.close()
log("done")
