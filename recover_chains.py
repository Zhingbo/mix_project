# -*- coding: utf-8 -*-
import os
# 串行恢复指定链(可指定 start_step): clear 对应步骤 + process(force)
# 用法: python recover_chains.py "链名:start_step" "链名" ...
#   - "AI智能算力:10"  -> 只重跑 step10 (finallist 已存在, 仅补 list_output)
#   - "工业元宇宙"     -> 默认从 step2 全量重跑
import requests, pymysql, time, sys, re
from datetime import datetime

API_BASE = "http://127.0.0.1:8001"
LOGIN_URL = f"{API_BASE}/api/auth/login"
PROCESS_URL = f"{API_BASE}/api/pipeline/process"
DELETE_URL = f"{API_BASE}/api/pipeline/delete_steps"
DB = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4')
LOG_FILE = "/root/mix_project/logs/recover_chains.log"


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def login():
    r = requests.post(LOGIN_URL, json={"username": "admin", "password": "admin123"}, timeout=20)
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError(f"登录失败: {r.text[:200]}")
    return tok


def clear_steps(token, ind, start_step):
    headers = {"Authorization": f"Bearer {token}"}
    steps = list(range(start_step, 11))
    try:
        r = requests.post(DELETE_URL, json={"industry_name": ind, "steps": steps},
                          headers=headers, timeout=600)
        log(f"    [{ind}] delete_steps({steps}) -> HTTP {r.status_code}")
    except Exception as e:
        log(f"    [{ind}] delete_steps 超时/失败(继续): {e}")
    if start_step <= 2:
        conn = pymysql.connect(**DB)
        cur = conn.cursor()
        for t, col in [("company_nodes_merge_temp", "industry_name"),
                       ("industry_structure_output", "industry_name")]:
            try:
                cur.execute(f"DELETE FROM {t} WHERE {col} = %s", (ind,))
            except Exception:
                pass
        conn.commit()
        cur.close(); conn.close()


def trigger_and_wait(token, ind, start_step):
    headers = {"Authorization": f"Bearer {token}"}
    body = {"industry_name": ind, "start_step": start_step, "force": True}
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
                m = re.search(r"处理步骤(\d+)", line)
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


def db_status(ind, poll=540, interval=30):
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
    specs = sys.argv[1:]
    if not specs:
        print("usage: recover_chains.py '链:start_step' ...")
        return
    log("=" * 60)
    log(f"恢复任务: {specs}")
    log("=" * 60)
    token = login()
    log("登录成功")
    ok, bad = [], []
    for spec in specs:
        if ":" in spec:
            ind, ss = spec.rsplit(":", 1)
            ss = int(ss)
        else:
            ind, ss = spec, 2
        t0 = time.time()
        log(f"\n>>> {ind} 从 step{ss} 开始")
        try:
            clear_steps(token, ind, ss)
        except Exception as e:
            log(f"  ⚠️ {ind} 清空失败 {e}")
        trig_ok, msg = trigger_and_wait(token, ind, ss)
        if not trig_ok:
            log(f"  ❌ {ind} 流失败: {msg}")
            bad.append(ind)
            continue
        terminal, fin, lst = db_status(ind)
        st = terminal[0] if terminal else "unknown"
        err = (terminal[3] or "")[:200] if terminal else ""
        log(f"  [{ind}] 状态={st} finallist={fin} list_output={lst} 耗时{time.time()-t0:.0f}s")
        if st == "completed" and lst > 0:
            log(f"  ✅ {ind} 完成")
            ok.append(ind)
        else:
            log(f"  ⚠️ {ind} 未确认: {st} {err}")
            bad.append(ind)
        time.sleep(3)
    log("\n" + "=" * 60)
    log(f"恢复结束: 成功 {len(ok)} / 存疑 {len(bad)}")
    if bad:
        log(f"存疑: {bad}")
    log("=" * 60)


if __name__ == "__main__":
    main()