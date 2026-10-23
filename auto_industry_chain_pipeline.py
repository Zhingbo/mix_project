"""
产业链自动化处理主脚本

功能：
1. 接收产业链名称参数
2. 自动执行步骤2-10
3. 实时推送进度
4. 处理完成后返回结果

使用方式：
    python auto_industry_chain_pipeline.py 氢能产业
    或通过API调用
"""
import os

import sys
import asyncio
import pymysql
import json
import time
from datetime import datetime
from typing import Dict, Any, List

# ==================== 配置参数 ====================
INDUSTRY_NAME = sys.argv[1] if len(sys.argv) > 1 else "氢能产业"

# ==================== 统一表名配置 ====================
TABLES = {
    'source_chain': 'industrial_chain.industrial_chain_structure',
    'whitelist_company': 'business_data.whitelist_company',
    'chain_needcomp': 'business_data.chain_needcomp',
    'company_nodes_mapping': 'business_data.company_nodes_mapping',
    'company_nodes_info_result': 'business_data.company_nodes_info_result',
    'company_nodes_info_split': 'business_data.company_nodes_info_split',
    'company_nodes_top': 'business_data.company_nodes_top',
    'company_nodes_final': 'business_data.company_nodes_final',
    'company_nodes_finallist': 'business_data.company_nodes_finallist',
    'industry_structure_output': 'business_data.industry_structure_output',
    'company_list_output': 'business_data.company_list_output',
    'mapping_industry_info_new': 'business_data.mapping_industry_info_new',
    'ent_industry_class_old': 'business_data.ent_industry_class_chain_scope_20260928_converted',
    'nodes_industry_mapping': 'business_data.nodes_industry_mapping',
    'company_nodes_mapping_temp': 'business_data.company_nodes_mapping_temp',
}

# ==================== 步骤配置 ====================
STEPS = [
    {
        'step': 2,
        'name': '生成节点定义',
        'description': '使用AI为产业链节点生成定义',
        'function': 'step2_generate_definition',
    },
    {
        'step': 3,
        'name': '节点匹配行业',
        'description': '将节点匹配到行业分类',
        'function': 'step3_match_industry',
    },
    {
        'step': 4,
        'name': '公司匹配节点',
        'description': '将公司匹配到产业链节点',
        'function': 'step4_company_match_nodes',
    },
    {
        'step': 5,
        'name': '搜索头部企业',
        'description': '从白名单搜索头部企业',
        'function': 'step5_search_top_companies',
        'need_whitelist': True,
    },
    {
        'step': 6,
        'name': '头部企业匹配节点',
        'description': '将头部企业匹配到节点',
        'function': 'step6_top_company_match',
    },
    {
        'step': 7,
        'name': '拆分结果',
        'description': '拆分匹配结果',
        'function': 'step7_split_results',
    },
    {
        'step': 8,
        'name': '合并去重清理',
        'description': '合并表并去重',
        'function': 'step8_merge_and_clean',
    },
    {
        'step': 9,
        'name': '输出最终名单',
        'description': '输出最终企业名单',
        'function': 'step9_export_finallist',
    },
    {
        'step': 10,
        'name': '输出上线表',
        'description': '输出上线所需的两张表',
        'function': 'step10_export_online_tables',
    },
]

# ==================== 数据库配置 ====================
DB_CONFIG = {
    'host': '8.141.5.67',
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'charset': 'utf8mb4'
}


def ensure_tables_exist():
    """确保所有表存在"""
    print("\n检查并创建表...")
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # 创建白名单表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS whitelist_company (
            id INT AUTO_INCREMENT PRIMARY KEY,
            industry_name VARCHAR(100) NOT NULL COMMENT '产业链名称',
            position VARCHAR(50) NOT NULL COMMENT '上游/中游/下游',
            company_name VARCHAR(255) NOT NULL COMMENT '企业名称',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_industry_name (industry_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产业链头部企业白名单'
        """)
        conn.commit()
        print("✓ whitelist_company")

        # 创建 chain_needcomp 表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chain_needcomp (
            id bigint NOT NULL AUTO_INCREMENT,
            chain_name varchar(255) NOT NULL COMMENT '产业链名称',
            nodes varchar(255) NOT NULL COMMENT '节点名称',
            parent_node varchar(255) COMMENT '父节点',
            parent_id bigint COMMENT '父节点ID',
            node_level int COMMENT '节点层级',
            create_time timestamp,
            update_time timestamp,
            chain_id int COMMENT '产业链ID',
            status int COMMENT '状态',
            nodes_definition text COMMENT '节点定义',
            PRIMARY KEY (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产业链节点信息表'
        """)
        conn.commit()
        print("✓ chain_needcomp")

        # 其他表的创建逻辑在各个步骤中处理

    except Exception as e:
        print(f"创建表时出错: {e}")
    finally:
        cursor.close()
        conn.close()


def execute_steps():
    """执行所有步骤"""
    print(f"\n{'='*60}")
    print(f"开始处理产业链: {INDUSTRY_NAME}")
    print(f"{'='*60}")

    results = []

    for step_info in STEPS:
        print(f"\n{'='*40}")
        print(f"步骤 {step_info['step']}: {step_info['name']}")
        print(f"说明: {step_info['description']}")
        print(f"{'='*40}")

        try:
            # 动态导入并执行步骤函数
            module = __import__(f"steps.step{step_info['step']}")

            # 根据是否有白名单选择是否需要先加载白名单
            if step_info.get('need_whitelist', False):
                # 加载白名单数据
                whitelist_data = load_whitelist_data()
            else:
                whitelist_data = None

            # 执行步骤函数
            if hasattr(module, step_info['function']):
                result = getattr(module, step_info['function'])(INDUSTRY_NAME, TABLES, whitelist_data)
                results.append({
                    'step': step_info['step'],
                    'name': step_info['name'],
                    'status': 'completed',
                    'result': result
                })
            else:
                print(f"警告：步骤{step_info['step']}未找到函数: {step_info['function']}")

        except Exception as e:
            results.append({
                'step': step_info['step'],
                'name': step_info['name'],
                'status': 'error',
                'error': str(e)
            })
            print(f"✗ 步骤{step_info['step']}失败: {e}")
            # 失败即停止
            break

    return results


def load_whitelist_data():
    """从 MySQL 读取白名单数据"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT industry_name, position, company_name
            FROM whitelist_company
            WHERE industry_name = %s
        """, (INDUSTRY_NAME))
        results = cursor.fetchall()
        cursor.close()
        conn.close()

        print(f"从数据库加载了 {len(results)} 条白名单数据")
        return results
    except Exception as e:
        print(f"加载白名单失败: {e}")
        return []


def main():
    print("=" * 60)
    print("产业链自动化处理流程")
    print("=" * 60)
    print(f"产业链名称: {INDUSTRY_NAME}")

    # 确保表存在
    ensure_tables_exist()

    # 执行步骤2-10
    results = execute_steps()

    # 输出结果
    print("\n" + "=" * 60)
    print("执行完成")
    print("=" * 60)

    # 统计结果
    completed = [r for r in results if r['status'] == 'completed']
    errors = [r for r in results if r['status'] == 'error']

    print(f"完成: {len(completed)} 个步骤")
    if errors:
        print(f"失败: {len(errors)} 个步骤")
        for e in errors:
            print(f"  - 步骤{e['step']}: {e.get('error', '')}")

    print(f"\n最终结果:")
    print(f"  - 总步骤数: {len(results)}")
    print(f"  - 成功: {len(completed)}")
    print(f"  - 失败: {len(errors)}")

    return {
        'industry_name': INDUSTRY_NAME,
        'status': 'completed' if len(errors) == 0 else 'error',
        'total_steps': len(STEPS),
        'completed': len(completed),
        'errors': errors
    }


if __name__ == "__main__":
    main()
