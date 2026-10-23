#!/bin/bash
# 模型替换脚本 - 不需要重启服务
# 只在下一次运行时生效

echo "=========================================="
echo "🔄 开始替换模型配置"
echo "=========================================="

# 备份目录
BACKUP_DIR="/root/mix_project/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
echo "📁 备份目录: $BACKUP_DIR"

# 定义替换规则
# 阿里云: qwen-plus → qwen3.5-plus-2026-04-20
# DeepSeek: 使用阿里云端点的 deepseek-v4-pro

echo ""
echo "📋 替换计划:"
echo "  1. step2_generate_definition.py: qwen-plus → qwen3.5-plus-2026-04-20"
echo "  2. step3_match_industryry.py: qwen-plus → qwen3.5-plus-2026-04-20"
echo "  3. step4_5_bulk_name_completion.py: deepseek-chat → deepseek-v4-pro (阿里云)"
echo "  4. step6_top_company_match.py: qwen-plus → qwen3.5-plus-2026-04-20"
echo "  5. step6_5_company_name_completion.py: deepseek-chat → deepseek-v4-pro (阿里云)"

echo ""
read -p "确认执行替换? (y/n): " confirm
if [ "$confirm" != "y" ]; then
    echo "❌ 取消操作"
    exit 0
fi

echo ""
echo "=========================================="
echo "🔄 开始执行替换"
echo "=========================================="

# 1. step2_generate_definition.py
echo ""
echo "📝 处理 step2_generate_definition.py..."
cp /root/mix_project/steps/step2_generate_definition.py "$BACKUP_DIR/"
sed -i 's/model="qwen-plus"/model="qwen3.5-plus-2026-04-20"/g' /root/mix_project/steps/step2_generate_definition.py
echo "   ✅ 已替换"

# 2. step3_match_industryry.py
echo "📝 处理 step3_match_industryry.py..."
cp /root/mix_project/steps/step3_match_industryry.py "$BACKUP_DIR/"
sed -i 's/model="qwen-plus"/model="qwen3.5-plus-2026-04-20"/g' /root/mix_project/steps/step3_match_industryry.py
echo "   ✅ 已替换"

# 3. step4_5_bulk_name_completion.py - DeepSeek 需要特殊处理
echo "📝 处理 step4_5_bulk_name_completion.py..."
cp /root/mix_project/steps/step4_5_bulk_name_completion.py "$BACKUP_DIR/"
sed -i 's/model="deepseek-chat"/model="deepseek-v4-pro"/g' /root/mix_project/steps/step4_5_bulk_name_completion.py
# 需要添加阿里云的 base_url
sed -i 's/api_key='\''${DEEPSEEK_API_KEY}'\''/api_key='\''${DASHSCOPE_API_KEY}'\''\n            base_url='\''https:\/\/dashscope.aliyuncs.com\/compatible-mode\/v1'\''/g' /root/mix_project/steps/step4_5_bulk_name_completion.py
echo "   ✅ 已替换 (切换到阿里云端点)"

# 4. step6_top_company_match.py
echo "📝 处理 step6_top_company_match.py..."
cp /root/mix_project/steps/step6_top_company_match.py "$BACKUP_DIR/"
sed -i 's/model="qwen-plus"/model="qwen3.5-plus-2026-04-20"/g' /root/mix_project/steps/step6_top_company_match.py
echo "   ✅ 已替换"

# 5. step6_5_company_name_completion.py - DeepSeek 需要特殊处理
echo "📝 处理 step6_5_company_name_completion.py..."
cp /root/mix_project/steps/step6_5_company_name_completion.py "$BACKUP_DIR/"
sed -i 's/model="deepseek-chat"/model="deepseek-v4-pro"/g' /root/mix_project/steps/step6_5_company_name_completion.py
# 需要添加阿里云的 base_url
sed -i 's/api_key='\''${DEEPSEEK_API_KEY}'\''/api_key='\''${DASHSCOPE_API_KEY}'\''\n            base_url='\''https:\/\/dashscope.aliyuncs.com\/compatible-mode\/v1'\''/g' /root/mix_project/steps/step6_5_company_name_completion.py
echo "   ✅ 已替换 (切换到阿里云端点)"

echo ""
echo "=========================================="
echo "✅ 替换完成!"
echo "=========================================="
echo ""
echo "📊 替换汇总:"
echo "  • DeepSeek: deepseek-chat → deepseek-v4-pro (通过阿里云)"
echo "  • Qwen: qwen-plus → qwen3.5-plus-2026-04-20"
echo ""
echo "📁 备份位置: $BACKUP_DIR"
echo ""
echo "⚠️  注意: 更改将在下次运行这些步骤时生效"
echo "⚠️  无需重启服务"
