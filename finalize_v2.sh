#!/bin/bash
# 恢复4条失败链 -> 导出29链 (nohup 后台运行)
PY=/root/acemcp/.venv/bin/python
LOG=/root/mix_project/logs/finalize_v2.log
cd /root/mix_project
echo "[$(date +%H:%M:%S)] finalize_v2 启动" > $LOG
$PY recover_chains.py "AI智能算力:10" "工业元宇宙:2" "机器人:2" "跨境电商:8" >> $LOG 2>&1
echo "[$(date +%H:%M:%S)] 恢复阶段结束, 开始导出29链" >> $LOG
$PY export_29chains.py >> $LOG 2>&1
echo "[$(date +%H:%M:%S)] ====== finalize_v2 ALL DONE ======" >> $LOG