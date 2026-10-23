#!/bin/bash
# 自动收尾: 等rerun全部结束 -> 重启服务(step9修复生效) -> 补跑机器人 -> 导出29链
PY=/root/acemcp/.venv/bin/python
LOG=/root/mix_project/logs/finalize_auto.log
runlog=/root/mix_project/logs/rerun_failed5_run.log
ts() { date "+%H:%M:%S"; }
echo "[$(ts)] finalize_auto 启动" > $LOG

# 1. 等 rerun_failed5 全部结束
n=0
while true; do
  if grep -q "全部结束" "$runlog" 2>/dev/null; then
    echo "[$(ts)] 检测到 rerun 全部结束" >> $LOG; break
  fi
  if ! ps aux | grep -q "[r]erun_29chains_full.py"; then
    sleep 30
    if ! ps aux | grep -q "[r]erun_29chains_full.py"; then
      echo "[$(ts)] rerun 进程已消失, 视为结束" >> $LOG; break
    fi
  fi
  n=$((n+1)); sleep 60
done

# 2. 重启服务使 step9(>=1) 生效
echo "[$(ts)] 重启 gunicorn ..." >> $LOG
bash /root/mix_project/fastapi_manager.sh restart >> $LOG 2>&1
sleep 15
for i in $(seq 1 40); do
  code=$(curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/ 2>/dev/null)
  if [ -n "$code" ] && [ "$code" != "000" ]; then echo "[$(ts)] 服务就绪 http=$code" >> $LOG; break; fi
  sleep 5
done

# 3. 补跑 机器人(新 step9)
echo "[$(ts)] 补跑 机器人 ..." >> $LOG
cd /root/mix_project
$PY scripts/rerun_29chains_full.py 机器人 >> $LOG 2>&1
echo "[$(ts)] 机器人补跑脚本结束" >> $LOG
fin=$(mysql -h127.0.0.1 -uroot -p"$DB_PASSWORD" business_data -N -e "SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name=\"机器人\";" 2>/dev/null)
lst=$(mysql -h127.0.0.1 -uroot -p"$DB_PASSWORD" business_data -N -e "SELECT COUNT(*) FROM company_list_output WHERE industry_name=\"机器人\";" 2>/dev/null)
echo "[$(ts)] 机器人校验 finallist=$fin list_output=$lst" >> $LOG

# 4. 导出全部29链
echo "[$(ts)] 开始导出29链 ..." >> $LOG
$PY /root/mix_project/export_29chains.py >> $LOG 2>&1
echo "[$(ts)] ====== finalize_auto ALL DONE ======" >> $LOG
