# -*- coding: utf-8 -*-
import os
# 无人机 全量重跑(清空2-10 + force 从 step2)。因改节点层级触发了结构变更清理, 需重新跑
import requests, pymysql, time, re
from datetime import datetime

API = "http://127.0.0.1:8001"
DB = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4')
ind = "无人机"

def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)

tok = requests.post(f"{API}/api/auth/login", json={"username":"admin","password":"admin123"}, timeout=15).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}

# 1) 清空步骤2-10
r = requests.post(f"{API}/api/pipeline/delete_steps", json={"industry_name": ind, "steps":[2,3,4,5,6,7,8,9,10]}, headers=h, timeout=120)
log(f"delete_steps(2-10) -> HTTP {r.status_code}")
conn = pymysql.connect(**DB)
cur = conn.cursor()
for t, col in [("company_nodes_merge_temp","industry_name"), ("industry_structure_output","industry_name")]:
    cur.execute(f"DELETE FROM {t} WHERE {col} = %s", (ind,))
conn.commit(); cur.close(); conn.close()

# 2) force 从 step2 全量重跑
log(f"触发 {ind} 从 step2 全量重跑")
t0 = time.time()
seen = set()
with requests.post(f"{API}/api/pipeline/process",
                   json={"industry_name": ind, "start_step": 2, "force": True},
                   headers=h, timeout=None, stream=True) as r:
    if r.status_code != 200:
        log(f"HTTP {r.status_code}: {r.text[:200]}")
    else:
        for line in r.iter_lines(decode_unicode=True):
            if not line: continue
            m = re.search(r"开始执行步骤(\d+)", line)
            if m and m.group(1) not in seen:
                log(f"  进入 step{m.group(1)}"); seen.add(m.group(1))
            elif "Traceback" in line or ("失败" in line and "已有数据" not in line):
                log(f"  {line[:160]}")

dt = time.time() - t0
conn = pymysql.connect(**DB)
cur = conn.cursor()
cur.execute("SELECT status,current_step FROM pipeline_task_status WHERE industry_name=%s ORDER BY id DESC LIMIT 1",(ind,))
st = cur.fetchone()
cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s",(ind,))
fin = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s",(ind,))
lo = cur.fetchone()[0]
cur.close(); conn.close()
log(f"状态={st} | finallist={fin} | list_output={lo} | 耗时{dt:.0f}s")
log("DONE")