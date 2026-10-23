#!/usr/bin/env python3
"""
直接启动华为眼镜第二阶段（步骤2-10）
"""
import sys
sys.path.append('/root/mix_project')

import logging

# 导入步骤函数
from steps.step2_generate_definition import step2_generate_definition

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_step2():
    """运行步骤2"""
    logger.info("🚀 开始华为眼镜步骤2: 生成节点定义")
    
    tables = {
        'chain_needcomp': 'business_data.chain_needcomp',
        'industrial_chain_structure': 'industrial_chain.industrial_chain_structure',
    }
    
    try:
        result = step2_generate_definition("华为眼镜", tables)
        logger.info(f"✅ 步骤2完成")
        return result
    except Exception as e:
        logger.error(f"❌ 步骤2失败: {e}")
        raise

if __name__ == "__main__":
    run_step2()
