# -*- coding: utf-8 -*-
import os
# 无人机 修复根节点后, 从 step10 续跑
import requests, pymysql, time
from datetime import datetime

API = "http://127.0.0.1:8001"
tok = requests.post(f"{API}/api/auth/login", json={"username":"admin","password":"admin123"}, timeout=15).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}

ind = "无人机"
print(f"[{datetime.now():%H:%M:%S}] 触发 {ind} 从 step10 续跑", flush=True)
t0 = time.time()
with requests.post(f"{API}/api/pipeline/process",
                   json={"industry_name": ind, "start_step": 10, "force": True},
                   headers=h, timeout=None, stream=True) as r:
    if r.status_code != 200:
        print("HTTP", r.status_code, r.text[:300], flush=True)
    else:
        for line in r.iter_lines(decode_unicode=True):
            if line and ("开始执行步骤" in line or "处理完成" in line or "Traceback" in line or "失败" in line or "根节点" in line):
                print(f"  [{datetime.now():%H:%M:%S}] {line[:160]}", flush=True)

dt = time.time() - t0
conn = pymysql.connect(host='8.141.5.67',port=3306,user='root',password=os.getenv('DB_PASSWORD'),database='business_data',charset='utf8mb4')
cur = conn.cursor()
cur.execute("SELECT status,current_step FROM pipeline_task_status WHERE industry_name=%s ORDER BY id DESC LIMIT 1",(ind,))
st = cur.fetchone()
cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s",(ind,))
lo = cur.fetchone()[0]
cur.close(); conn.close()
print(f"[{datetime.now():%H:%M:%S}] 状态={st} | list_output={lo} | 耗时{dt:.0f}s", flush=True)
print("DONE", flush=True)