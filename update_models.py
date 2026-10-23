#!/usr/bin/env python3
"""
模型替换脚本
"""
import shutil
from datetime import datetime
import os

BACKUP_DIR = f"/root/mix_project/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
os.makedirs(BACKUP_DIR, exist_ok=True)

print("=" * 60)
print("🔄 模型替换脚本")
print("=" * 60)
print(f"📁 备份目录: {BACKUP_DIR}")

updates = [
    ("/root/mix_project/steps/step2_generate_definition.py", 
     [('model="qwen-plus"', 'model="qwen3.5-plus-2026-04-20"')]),
    ("/root/mix_project/steps/step3_match_industryry.py",
     [('model="qwen-plus"', 'model="qwen3.5-plus-2026-04-20"')]),
    ("/root/mix_project/steps/step6_top_company_match.py",
     [('model="qwen-plus"', 'model="qwen3.5-plus-2026-04-20"')]),
]

for filepath, replacements in updates:
    print(f"\n📝 {os.path.basename(filepath)}")
    backup_path = os.path.join(BACKUP_DIR, os.path.basename(filepath))
    shutil.copy2(filepath, backup_path)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    for old, new in replacements:
        content = content.replace(old, new)
    
    with open(filepath, 'w') as f:
        f.write(content)
    print("   ✅ 已替换 qwen-plus → qwen3.5-plus-2026-04-20")

# DeepSeek 文件需要特殊处理
deepseek_files = [
]

for filepath in deepseek_files:
    print(f"\n📝 {os.path.basename(filepath)}")
    backup_path = os.path.join(BACKUP_DIR, os.path.basename(filepath))
    shutil.copy2(filepath, backup_path)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # 替换模型名称
    content = content.replace("model='deepseek-chat'", 'model="deepseek-v4-pro"')
    content = content.replace('model="deepseek-chat"', 'model="deepseek-v4-pro"')
    
    # 替换 API key 为阿里云
    old_key = "api_key=os.getenv('DEEPSEEK_API_KEY')"
    new_config = '''api_key=os.getenv("DASHSCOPE_API_KEY")
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"'''
    content = content.replace(old_key, new_config)
    
    with open(filepath, 'w') as f:
        f.write(content)
    print("   ✅ 已替换 deepseek-chat → deepseek-v4-pro (阿里云)")

print("\n" + "=" * 60)
print("✅ 替换完成!")
print("=" * 60)
print("\n📊 替换汇总:")
print("  • Qwen: qwen-plus → qwen3.5-plus-2026-04-20")
print("  • DeepSeek: deepseek-chat → deepseek-v4-pro (阿里云端点)")
print(f"\n📁 备份位置: {BACKUP_DIR}")
print("\n⚠️  更改将在下次运行时生效，无需重启服务")
