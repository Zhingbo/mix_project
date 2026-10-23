"""
步骤8：合并去重清理

功能：合并企业节点结果表，去重，清理无效节点
"""

import os
import pymysql



def _final_table_name(industry_name):
    """每链独立 final 表名(稳定后缀, 支持并行)"""
    import hashlib
    return "company_nodes_final_" + hashlib.md5(str(industry_name).encode("utf-8")).hexdigest()[:12]

def _get_node_standard_mapping(industry_name, conn, chain_table):
    """
    获取节点名称标准化映射表

    从chain_needcomp表中读取正确的节点名称，并建立映射关系
    处理以下情况：
    1. 简化名称 -> 完整名称 (如: 上游 -> 产业链上游)
    2. 错误名称 -> 正确名称 (如: 下游应用 -> 产业链下游)
    3. 别名 -> 标准名称

    Args:
        industry_name: 产业���名称
        conn: 数据库连接
        chain_table: chain_needcomp表名

    Returns:
        dict: 标准化映射表 {旧名称: 新名称}
    """
    cursor = conn.cursor()

    # 读取正确的节点名称
    cursor.execute(f"""
        SELECT DISTINCT nodes, parent_node
        FROM {chain_table}
        WHERE chain_name = %s
    """, (industry_name,))

    correct_nodes = {}
    for row in cursor.fetchall():
        node_name, parent_node = row
        correct_nodes[node_name] = node_name
        # 同时记录父节点，用于映射简化名称
        if parent_node:
            correct_nodes[parent_node] = parent_node

    # 建立标准化映射规则
    mapping_rules = {
        # 规则1: 简化的上中下游 -> 完整名称
        '上游': '产业链上游',
        '中游': '产业链中游',
        '下游': '产业链下游',

        # 规则2: 常见的错误名称 -> 正确名称
        '下游应用': '产业链下游',
        '氢气应用': '产业链下游',
        '制氢': '氢气制备',
        '氢气纯化': '氢气制备',
        '氢气储存': '氢气储运',
        '储氢容器': '储氢',
        '氢气运输': '氢气储运',
        '氢气运输设备': '氢气储运',
    }

    # 动态发现映射：如果简化名称是正确名称的子串，则映射
    for old_name in mapping_rules.keys():
        new_name = mapping_rules[old_name]
        # 验证新名称是否存在
        if new_name not in correct_nodes:
            # 尝试在正确节点中查找包含新名称的节点
            for correct_name in correct_nodes.keys():
                if old_name in correct_name or correct_name in old_name:
                    mapping_rules[old_name] = correct_name
                    break

    return mapping_rules


def _standardize_node_names(industry_name, conn, tables):
    """
    标准化company_nodes_info_split表中的节点名称

    Args:
        industry_name:产业链名称
        conn: 数据库连接
        tables: 表名配置字典
    """
    chain_table = tables['chain_needcomp']
    split_table = tables.get('company_nodes_info_split', 'company_nodes_info_split')

    # 获取标准化映射表
    mapping = _get_node_standard_mapping(industry_name, conn, chain_table)

    if not mapping:
        return 0

    cursor = conn.cursor()

    # 应用标准化映射
    for old_name, new_name in mapping.items():
        update_sql = f"""
        UPDATE {split_table}
        SET matched_node = %s
        WHERE industry_name = %s
          AND matched_node = %s
        """
        cursor.execute(update_sql, (new_name, industry_name, old_name))

    affected_rows = cursor.rowcount
    conn.commit()
    cursor.close()

    return affected_rows


def step8_merge_and_clean(industry_name, tables, whitelist_data=None, progress_callback=None):
    """
    合并去重清理

    Args:
        industry_name: 产业链名称
        tables: 表名配置字典
        whitelist_data: 白名单数据（本步骤不使用）
    """
    # 数据库连接配置
    host = '8.141.5.67'
    user = 'root'
    password = os.getenv('DB_PASSWORD')
    database = 'business_data'
    port = 3306

    # 表名
    split_table = tables.get('company_nodes_info_split', 'company_nodes_info_split')
    step5_table = tables['company_nodes_top']  # 从步骤5获取数据
    step4_table = tables.get('company_nodes_mapping', 'company_nodes_mapping')  # 步骤4的输出
    merge_table = 'company_nodes_merge_temp'  # 临时合并表（不覆盖步骤4的输出）
    final_table = _final_table_name(industry_name)
    chain_table = tables['chain_needcomp']

    print(f"\n{'='*40}")
    print(f"步骤8：合并去重清理")
    print(f"产业链名称: {industry_name}")
    print(f"{'='*40}")

    conn = pymysql.connect(host=host, user=user, password=password, database=database, port=port)
    cursor = conn.cursor()

    try:
        # 步骤0：标准化节点名称（在合并之前）
        print("\n[0/4] 标准化节点名称...")
        standardized_count = _standardize_node_names(industry_name, conn, tables)
        print(f"  标准化了 {standardized_count} 条节点名称记录")

        # 步骤1：创建合并表
        print("\n[1/4] 创建合并表...")
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {merge_table} (
            company_name TEXT,
            credit_code TEXT,
            certainty TEXT,
            industry_name TEXT,
            nodes TEXT,
            name TEXT,
            level TEXT,
            full_name TEXT,
            reason TEXT
        )
        """
        cursor.execute(create_table_sql)
        conn.commit()

        # 清空当前产业链的旧数据
        cursor.execute(f"DELETE FROM {merge_table} WHERE industry_name = %s", (industry_name,))
        conn.commit()

        # 插入步骤4的数据（从ent_industry_class_old匹配的企业）
        insert_step4_sql = f"""
        INSERT INTO {merge_table} (company_name, credit_code, certainty, industry_name, nodes, name, level, full_name, reason)
        SELECT company_name, credit_code, certainty, industry_name, nodes, name, level, full_name, reason
        FROM {step4_table}
        WHERE industry_name = %s
        """
        cursor.execute(insert_step4_sql, (industry_name,))
        step4_count = cursor.rowcount
        conn.commit()
        print(f"  插入步骤4数据: {step4_count} 条")

        # Step 5 records are merged only when they already contain a valid detail node.
        insert_step5_sql = f"""
        INSERT INTO {merge_table} (company_name, certainty, industry_name, nodes, reason)
        SELECT COALESCE(t.company_name_full, t.company_name), '3', %s, t.position, '白名单企业'
        FROM {step5_table} t
        JOIN {chain_table} b
          ON t.position COLLATE utf8mb4_unicode_ci = b.nodes COLLATE utf8mb4_unicode_ci
         AND b.chain_name = %s
         AND b.node_level >= 2
        WHERE t.industry_chain = %s
        """
        cursor.execute(insert_step5_sql, (industry_name, industry_name, industry_name))
        step5_count = cursor.rowcount
        conn.commit()
        print(f"  插入步骤5有效节点数据: {step5_count} 条")

        # 插入步骤7的数据（头部企业AI匹配）
        # company_nodes_info_split表结构: company_name, industry_name, matched_node, match_reason, score
        insert_split_sql = f"""
        INSERT INTO {merge_table} (company_name, certainty, industry_name, nodes, reason)
        SELECT company_name, score, industry_name, matched_node, match_reason
        FROM {split_table}
        WHERE industry_name = %s
        """
        cursor.execute(insert_split_sql, (industry_name,))
        split_count = cursor.rowcount
        conn.commit()
        print(f"  插入头部企业数据: {split_count} 条")

        # 统计总记录数
        count_sql = f"SELECT COUNT(*) FROM {merge_table} WHERE industry_name = %s"
        cursor.execute(count_sql, (industry_name,))
        total_count = cursor.fetchone()[0]
        print(f"  合并完成，总记录数: {total_count}")

        if progress_callback:
            progress_callback('progress', {'stage': 1, 'total_stages': 4, 'message': f'合并完成，总记录数: {total_count}'})

        # 步骤2：去重
        print("\n[2/4] 去重处理...")
        # 删除旧的 final 表
        cursor.execute(f"DROP TABLE IF EXISTS {final_table}")
        conn.commit()

        # 创建去重后的 final 表
        create_final_sql = f"""
        CREATE TABLE {final_table} AS
        WITH RankedData AS (
            SELECT company_name, credit_code, certainty, industry_name, nodes,
                   name, level, full_name, reason,
                   ROW_NUMBER() OVER (
                       PARTITION BY company_name, industry_name, nodes
                       ORDER BY
                           CASE
                               WHEN certainty REGEXP '^[0-9]+$' THEN CAST(certainty AS SIGNED)
                               WHEN certainty = '强' THEN 50
                               WHEN certainty = '弱' THEN 25
                               ELSE 0
                           END DESC
                   ) AS rn
            FROM {merge_table}
            WHERE industry_name = %s
        )
        SELECT company_name, credit_code, certainty, industry_name, nodes,
               name, level, full_name, reason
        FROM RankedData
        WHERE rn = 1
        """
        cursor.execute(create_final_sql, (industry_name,))
        conn.commit()

        # 统计去重后的记录数
        cursor.execute(f"SELECT COUNT(*) FROM {final_table}")
        final_count = cursor.fetchone()[0]
        print(f"  去重完成，记录数: {final_count}")

        if progress_callback:
            progress_callback('progress', {'stage': 2, 'total_stages': 4, 'message': f'去重完成，记录数: {final_count}'})

        # 步骤3：清理无效节点
        print("\n[3/4] 清理无效节点...")
        delete_sql = f"""
        DELETE FROM {final_table} a
        WHERE NOT EXISTS(
            SELECT 1
            FROM {chain_table} b
            WHERE a.nodes = b.nodes COLLATE utf8mb4_unicode_ci
              AND b.chain_name = %s
        )
        """
        cursor.execute(delete_sql, (industry_name,))
        deleted_rows = cursor.rowcount
        conn.commit()
        print(f"  删除无效记录: {deleted_rows} 条")

        # 统计最终记录数
        cursor.execute(f"SELECT COUNT(*) FROM {final_table}")
        final_count_after = cursor.fetchone()[0]
        print(f"  最终记录数: {final_count_after}")

        if progress_callback:
            progress_callback('progress', {'stage': 3, 'total_stages': 4, 'message': f'最终记录数: {final_count_after}'})

        print(f"\n步骤8完成")
        return {"step": 8, "name": "合并去重清理", "status": "completed", "count": final_count_after}

    except Exception as e:
        print(f"步骤8执行失败: {e}")
        conn.rollback()
        return {"step": 8, "name": "合并去重清理", "status": "error", "error": str(e)}
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    from auto_industry_chain_pipeline import TABLES
    step8_merge_and_clean("生物医药产业", TABLES)
