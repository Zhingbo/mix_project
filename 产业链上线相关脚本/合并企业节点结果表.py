"""
步骤九：合并企业挂接节点结果表 + 去重 + 清理无效节点

功能说明：
1. 合并：将步骤15的拆分结果合并到 company_nodes_mapping_0421
2. 去重：按 (company_name, industry_name, nodes) 分组去重
3. 清理：删除不在产业链节点表中的无效节点
"""
import os

import mysql.connector
from mysql.connector import Error

# ==================== 表名配置 ====================
SPLIT_TABLE = "company_nodes_info_result_0421_split"   # 步骤15的拆分表（源）
STEP5_TABLE = "company_nodes_mapping_0421"             # 步骤5的公司匹配节点结果
MAPPING_TABLE = "company_nodes_mapping_0421"           # 合并后的中间表
FINAL_TABLE = "company_nodes_results_final_0421"       # 最终去重表
CHAIN_TABLE = "chain_needcomp0421"                     # 节点信息表（用于验证）

# ==================== 数据库连接配置 ====================
db_config = {
    'host': '8.141.5.67',
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'port': 3306
}


def step1_merge_split_results():
    """
    步骤1：合并企业挂接节点结果表
    合并两个来源：
    1. 步骤五：全量企业匹配（certainty='强'/'弱'）
    2. 步骤十五：头部企业AI匹配（certainty=数字分数）
    """
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        print("=" * 60)
        print("步骤1：合并企业挂接节点结果表")
        print("=" * 60)

        # 确保 MAPPING_TABLE 存在
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {MAPPING_TABLE} (
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

        # 先清空 MAPPING_TABLE（确保每次都是全新合并）
        cursor.execute(f"TRUNCATE TABLE {MAPPING_TABLE}")
        conn.commit()
        print(f"已清空 {MAPPING_TABLE}")

        # 插入步骤五的数据（全量企业匹配，certainty='强'/'弱'）
        print(f"\n正在合并步骤五的数据: {STEP5_TABLE}")
        insert_step5_sql = f"""
        INSERT INTO {MAPPING_TABLE} (company_name, credit_code, certainty, industry_name, nodes, name, level, full_name, reason)
        SELECT company_name, credit_code, certainty, industry_name, nodes, name, level, full_name, reason
        FROM {STEP5_TABLE}
        """
        cursor.execute(insert_step5_sql)
        step5_count = cursor.rowcount
        conn.commit()
        print(f"插入步骤五数据: {step5_count} 条")

        # 插入步骤十五的数据（头部企业AI匹配，certainty=数字分数）
        print(f"\n正在合并步骤十五的数据: {SPLIT_TABLE}")
        insert_step15_sql = f"""
        INSERT INTO {MAPPING_TABLE} (company_name, certainty, industry_name, nodes, reason)
        SELECT company_name, score, industry_name, matched_node, match_reason
        FROM {SPLIT_TABLE}
        WHERE NOT EXISTS(
            SELECT 1
            FROM {MAPPING_TABLE} b
            WHERE {SPLIT_TABLE}.company_name = b.company_name
              AND {SPLIT_TABLE}.industry_name = b.industry_name
              AND {SPLIT_TABLE}.matched_node = b.nodes
        )
        """
        cursor.execute(insert_step15_sql)
        step15_count = cursor.rowcount
        conn.commit()
        print(f"插入步骤十五数据: {step15_count} 条（新增）")

        # 统计总记录数
        count_sql = f"SELECT COUNT(*) FROM {MAPPING_TABLE}"
        cursor.execute(count_sql)
        total_count = cursor.fetchone()[0]
        print(f"\n合并完成，{MAPPING_TABLE} 总记录数: {total_count}")

    except Error as e:
        print(f"步骤1执行出错: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def step2_deduplicate_results():
    """
    步骤2：对合并后的表进行去重处理
    按 (company_name, industry_name, nodes) 分组，优先保留头部企业（certainty为数字）> 强 > 弱
    """
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        print("\n" + "=" * 60)
        print("步骤2：对合并后的表进行去重处理")
        print("=" * 60)

        # 删除旧的 final 表
        cursor.execute(f"DROP TABLE IF EXISTS {FINAL_TABLE}")
        conn.commit()
        print(f"已删除旧的 {FINAL_TABLE}")

        # 创建去重后的 final 表
        # 排序规则：数字certainty(头部企业) > '强' > '弱' > 其他
        create_final_sql = f"""
        CREATE TABLE {FINAL_TABLE} AS
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
            FROM {MAPPING_TABLE}
        )
        SELECT company_name, credit_code, certainty, industry_name, nodes,
               name, level, full_name, reason
        FROM RankedData
        WHERE rn = 1
        """
        cursor.execute(create_final_sql)
        conn.commit()

        # 统计去重后的记录数
        count_sql = f"SELECT COUNT(*) FROM {FINAL_TABLE}"
        cursor.execute(count_sql)
        final_count = cursor.fetchone()[0]
        print(f"去重完成，最终表 {FINAL_TABLE} 记录数: {final_count}")

    except Error as e:
        print(f"步骤2执行出错: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def step3_clean_invalid_nodes():
    """
    步骤3：删除不在产业链节点中的但匹配上了其他名字的节点
    """
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        print("\n" + "=" * 60)
        print("步骤3：删除不在产业链节点中的无效节点")
        print("=" * 60)

        # 统计删除前的记录数
        count_before_sql = f"SELECT COUNT(*) FROM {FINAL_TABLE}"
        cursor.execute(count_before_sql)
        count_before = cursor.fetchone()[0]
        print(f"删除前记录数: {count_before}")

        # 删除无效节点
        delete_sql = f"""
        DELETE FROM {FINAL_TABLE} a
        WHERE NOT EXISTS(
            SELECT 1
            FROM {CHAIN_TABLE} b
            WHERE a.nodes = b.nodes COLLATE utf8mb4_unicode_ci
              AND a.industry_name = b.chain_name COLLATE utf8mb4_unicode_ci
        )
        """
        cursor.execute(delete_sql)
        deleted_rows = cursor.rowcount
        conn.commit()

        # 统计删除后的记录数
        count_after_sql = f"SELECT COUNT(*) FROM {FINAL_TABLE}"
        cursor.execute(count_after_sql)
        count_after = cursor.fetchone()[0]

        print(f"删除完成，删除了 {deleted_rows} 条无效记录")
        print(f"删除后记录数: {count_after}")

    except Error as e:
        print(f"步骤3执行出错: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def main():
    print("\n" + "=" * 60)
    print("合并企业节点结果表处理流程")
    print("=" * 60)
    print(f"\n配置信息:")
    print(f"  步骤五结果表: {STEP5_TABLE}")
    print(f"  步骤十五拆分表: {SPLIT_TABLE}")
    print(f"  合并中间表: {MAPPING_TABLE}")
    print(f"  最终结果表: {FINAL_TABLE}")
    print(f"  节点信息表: {CHAIN_TABLE}")

    # 执行三个步骤
    step1_merge_split_results()
    step2_deduplicate_results()
    step3_clean_invalid_nodes()

    print("\n" + "=" * 60)
    print("所有步骤执行完成！")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
