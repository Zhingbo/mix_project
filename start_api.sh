#!/bin/bash
# 产业链自动化处理 API 启动脚本

cd /root/mix_project

echo "========================================="
echo "产业链自动化处理 API"
echo "========================================="
echo "启动中..."
echo ""

# 激活 anaconda 环境（如果需要）
# source /root/anaconda3/etc/profile.d/conda.sh
# conda activate your_env

# 启动 API
python3 -m uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
