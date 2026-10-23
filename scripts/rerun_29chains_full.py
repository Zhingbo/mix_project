# -*- coding: utf-8 -*-
import os
# 串行重跑 29 条产业链(新逻辑: 双底表step4 + 无LLM搜索step6), 每条 clear 2-10 + force
import requests
import pymysql
import time
import sys
import re
from datetime import datetime

API_BASE = "http://127.0.0.1:8001"
LOGIN_URL = f"{API_BASE}/api/auth/login"
PROCESS_URL = f"{API_BASE}/api/pipeline/process"
DELETE_URL = f"{API_BASE}/api/pipeline/delete_steps"

DB = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4')

ALL = ["3D打印", "5G", "AI智能算力", "人工智能", "人形机器人", "仪器仪表", "低空经济",
       "储能", "光伏产业", "卫星导航", "可控核聚变", "合成生物", "商业航天", "大飞机",
       "工业元宇宙", "工业母机产业链", "工业软件", "新能源汽车", "无人机", "机器人",
       "检验检测", "氢能产业", "激光", "脑机接口", "船舶海工", "跨境电商", "量子科技",
       "集成电路", "自动驾驶"]

LOG_FILE = "/root/mix_project/logs/rerun_29chains_full.log"


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def login():
    r = requests.post(LOGIN_URL, json={"username": "admin", "password": "admin123"}, timeout=15)
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError(f"登录失败: {r.text[:200]}")
    return tok


def clear_steps(token, ind):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(DELETE_URL, json={"industry_name": ind,
                                        "steps": [2, 3, 4, 5, 6, 7, 8, 9, 10]},
                      headers=headers, timeout=180)
    log(f"    [{ind}] delete_steps(2-10) -> HTTP {r.status_code}")
    conn = pymysql.connect(**DB)
    cur = conn.cursor()
    for t, col in [("company_nodes_merge_temp", "industry_name"),
                   ("industry_structure_output", "industry_name")]:
        cur.execute(f"DELETE FROM {t} WHERE {col} = %s", (ind,))
    conn.commit()
    cur.close(); conn.close()


def trigger_and_wait(token, ind):
    headers = {"Authorization": f"Bearer {token}"}
    body = {"industry_name": ind, "start_step": 2, "force": True}
    seen = set()
    try:
        with requests.post(PROCESS_URL, json=body, headers=headers,
                           timeout=None, stream=True) as resp:
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                m = re.search(r"开始执行步骤(\d+)", line)
                if m:
                    k = f"step{m.group(1)}"
                    if k not in seen:
                        log(f"    [{ind}] 进入 {k}")
                        seen.add(k)
                elif "处理完成" in line:
                    log(f"    [{ind}] 处理完成")
                elif "Traceback" in line or "失败" in line or "错误" in line:
                    log(f"    [{ind}] {line[:160]}")
        return True, "stream ended"
    except Exception as e:
        return False, str(e)


def db_status(ind, poll=360, interval=20):
    conn = pymysql.connect(**DB)
    cur = conn.cursor()
    terminal = None
    for _ in range(poll):
        cur.execute("SELECT status, current_step, progress, error_message "
                    "FROM pipeline_task_status WHERE industry_name=%s "
                    "ORDER BY id DESC LIMIT 1", (ind,))
        row = cur.fetchone()
        if row and row[0] in ("completed", "error", "cancelled"):
            terminal = row
            break
        time.sleep(interval)
    cur.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=%s", (ind,))
    fin = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name=%s", (ind,))
    lst = cur.fetchone()[0]
    cur.close(); conn.close()
    return terminal, fin, lst


def main():
    inds = sys.argv[1:] if len(sys.argv) > 1 else ALL
    log("=" * 60)
    log(f"串行重跑 {len(inds)} 条链(新逻辑): {inds}")
    log("=" * 60)
    token = login()
    log("登录成功")
    ok, bad = [], []
    for i, ind in enumerate(inds, 1):
        t_start = time.time()
        log(f"\n[{i}/{len(inds)}] {ind} 开始")
        try:
            clear_steps(token, ind)
        except Exception as e:
            log(f"  ⚠️ {ind} 清空步骤失败 {e}")
        trig_ok, msg = trigger_and_wait(token, ind)
        if not trig_ok:
            log(f"  ❌ {ind} 流失败: {msg} (耗时{time.time()-t_start:.0f}s)")
            bad.append(ind)
            continue
        terminal, fin, lst = db_status(ind)
        st = terminal[0] if terminal else "unknown"
        err = (terminal[3] or "")[:200] if terminal else ""
        dt = time.time() - t_start
        log(f"  [{i}] 状态={st} | finallist={fin} | list_output={lst} | 耗时{dt:.0f}s")
        if st == "completed" and lst > 0:
            log(f"  ✅ {ind} 完成 ({(dt/60):.1f} min)")
            ok.append(ind)
        else:
            log(f"  ⚠️ {ind} 未确认: {st} {err}")
            bad.append(ind)
        time.sleep(3)
    log("\n" + "=" * 60)
    log(f"全部结束: 成功 {len(ok)} / 存疑 {len(bad)}")
    if bad:
        log(f"存疑: {bad}")
    log("=" * 60)


if __name__ == "__main__":
    main()