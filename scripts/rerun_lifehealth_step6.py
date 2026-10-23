# -*- coding: utf-8 -*-
import os
# 生命健康 step6 续跑(药房/药铺修复后): delete 6-10 + process start_step=6 force
import requests
import pymysql
import time
from datetime import datetime

API = "http://127.0.0.1:8001"
ind = "生命健康"
LOG = "/root/mix_project/logs/rerun_lifehealth_step6.log"


def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


tok = requests.post(f"{API}/api/auth/login",
                    json={"username": "admin", "password": "admin123"},
                    timeout=15).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
log(f"触发 {ind} 从 step6 重跑(药房/药铺修复)")

r = requests.post(f"{API}/api/pipeline/delete_steps",
                  json={"industry_name": ind, "steps": [6, 7, 8, 9, 10]},
                  headers=h, timeout=120)
log(f"delete_steps(6-10) -> HTTP {r.status_code}")

conn = pymysql.connect(host='8.141.5.67', port=3306, user='root',
                       password=os.getenv('DB_PASSWORD'), database='business_data',
                       charset='utf8mb4')
cur = conn.cursor()
for t in ["company_nodes_merge_temp", "industry_structure_output"]:
    cur.execute(f"DELETE FROM {t} WHERE industry_name=%s", (ind,))
conn.commit()
cur.close()
conn.close()
log("清空 merge_temp / structure_output 完成")

t0 = time.time()
with requests.post(f"{API}/api/pipeline/process",
                   json={"industry_name": ind, "start_step": 6, "force": True},
                   headers=h, timeout=None, stream=True) as resp:
    if resp.status_code != 200:
        log(f"HTTP {resp.status_code}: {resp.text[:200]}")
    else:
        for line in resp.iter_lines(decode_unicode=True):
            if line and ("开始执行步骤" in line or "处理完成" in line
                         or "Traceback" in line or "失败" in line or "错误" in line):
                log(f"  {line[:160]}")

log(f"SSE结束 耗时{time.time() - t0:.0f}s")

conn = pymysql.connect(host='8.141.5.67', port=3306, user='root',
                       password=os.getenv('DB_PASSWORD'), database='business_data',
                       charset='utf8mb4')
cur = conn.cursor()
cur.execute("SELECT status,current_step FROM pipeline_task_status "
            "WHERE industry_name=%s ORDER BY id DESC LIMIT 1", (ind,))
st = cur.fetchone()
cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (ind,))
fin = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (ind,))
lo = cur.fetchone()[0]
cur.close()
conn.close()
log(f"状态={st} finallist={fin} list_output={lo}")
log("DONE")