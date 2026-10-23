#!/usr/bin/env python3
"""
修复Jina配置缓存问题
"""
import sys

# 清除JinaSearcher的配置缓存
from services.jina_search_service import JinaSearcher, _get_jina_config, _jina_config

# 强制重新加载配置
import services.jina_search_service as jina_module

# 清除全局缓存
if hasattr(jina_module, '_jina_config'):
    jina_module._jina_config = None
    print("✅ 已清除Jina配置缓存")

# 验证新配置
from services.jina_search_service import _get_jina_config
config = _get_jina_config()

print("\n当前Jina配置:")
print(f"  API URL: {config['url']}")
if config['keys']:
    first_key = config['keys'][0]
    if isinstance(first_key, dict):
        key = first_key.get('key', '')
    else:
        key = first_key
    print(f"  第一个密钥: {key[:30]}...")

print("\n配置验证完成！")
