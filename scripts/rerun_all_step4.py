# -*- coding: utf-8 -*-
import os
# 批量重跑(放宽匹配 + 搜索头部企业): 直连SQL清 step4-10, 再 force 从 step4 重跑
import requests, pymysql, time, sys
from datetime import datetime

API = "http://127.0.0.1:8001"
LOG = "/root/mix_project/logs/rerun_all_step4.log"
DB = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4')

CHAINS = [
 "工业元宇宙","工业软件","人工智能","AI智能算力","光伏产业","储能","氢能产业","大飞机","合成生物",
 "可控核聚变","生命健康","量子科技","脑机接口","5G","低空经济","商业航天","人形机器人",
 "集成电路","卫星导航","新能源汽车产业链图谱","新能源汽车生态系统","自动驾驶","无人机",
 "工业机器人","工业母机产业链","船舶海工","激光","3D打印","跨境电商"
]

CLEAR = [
    ("company_nodes_mapping", "industry_name"),
    ("company_nodes_top", "industry_chain"),
    ("company_nodes_info_result", "industry_name"),
    ("company_nodes_info_split", "industry_name"),
    ("company_nodes_final", "industry_name"),
    ("company_nodes_finallist", "industry_name"),
    ("company_list_output", "industry_name"),
    ("company_nodes_merge_temp", "industry_name"),
    ("industry_structure_output", "industry_name"),
]

def log(m):
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    open(LOG, "a", encoding="utf-8").write(line + "\n")

def clear_chain(ch):
    c = pymysql.connect(**DB)
    cur = c.cursor()
    for t, col in CLEAR:
        try:
            cur.execute(f"DELETE FROM {t} WHERE {col} = %s", (ch,))
        except Exception as e:
            log(f"    clear {t} err {e}")
    c.commit(); cur.close(); c.close()

def main():
    chains = sys.argv[1:] if len(sys.argv) > 1 else CHAINS
    tok = requests.post(f"{API}/api/auth/login", json={"username":"admin","password":"admin123"}, timeout=15).json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}
    log(f"批量重跑 {len(chains)} 条链 (SQL清表 + step4 force)")
    for i, ch in enumerate(chains, 1):
        log(f"\n[{i}/{len(chains)}] {ch}")
        t0 = time.time()
        clear_chain(ch)
        log(f"    清表完成 {time.time()-t0:.0f}s")
        try:
            with requests.post(f"{API}/api/pipeline/process", json={"industry_name":ch,"start_step":4,"force":True}, headers=H, stream=True, timeout=None) as r:
                if r.status_code != 200:
                    log(f"    触发失败 HTTP {r.status_code}: {r.text[:150]}"); continue
                for raw in r.iter_lines(decode_unicode=True):
                    pass
        except Exception as e:
            log(f"    流失败 {e}")
        dt = time.time() - t0
        c = pymysql.connect(**DB); cur = c.cursor()
        cur.execute("SELECT status FROM pipeline_task_status WHERE industry_name=%s ORDER BY id DESC LIMIT 1",(ch,))
        row = cur.fetchone(); st = row[0] if row else "?"
        cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s",(ch,))
        fin = cur.fetchone()[0]
        c.close()
        log(f"    耗时{dt:.0f}s status={st} finallist={fin}")
    log("\n全部结束")

if __name__ == "__main__":
    main()
