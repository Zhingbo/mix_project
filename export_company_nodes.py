"""
步骤十：输出最终结果交给产业研究院人员审核企业名单

功能说明：
1. 输出企业名单（合并最终表 + 节点信息表 + 计算分数）
2. 创建头部企业表（来自步骤14的拆分结果）
3. 建立索引加快查询速度
4. 更新头部企业分数为 9999
5. 删除不间断空格
6. 导出到 Excel
"""
import os

import pymysql
import pandas as pd

# ==================== 表名配置 ====================
RESULT_FINAL_TABLE = "company_nodes_results_final_0421"  # 步骤17的结果表
CHAIN_TABLE = "chain_needcomp0421"                        # 步骤5的节点信息表
SPLIT_TABLE = "company_nodes_info_result_0421_split"      # 步骤14的拆分结果表
FINALLIST_TABLE = "company_nodes_finallist_0421"          # 最终输出名单表
TOPLIST_TABLE = "company_nodes_top_0421"                  # 头部企业表

# ==================== 其他配置 ====================
INDUSTRY_NAME = "氢能产业"                                  # 产业链名称
OUTPUT_PATH = '/root/mix_project/company_nodes_finallist.xlsx'  # Excel 输出路径

# ==================== 数据库连接配置 ====================
db_config = {
    'host': '8.141.5.67',
    'port': 3306,
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'charset': 'utf8mb4'
}


def step1_create_finallist():
    """
    步骤1：输出企业名单
    合并最终结果表 + 节点信息表，计算分数
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    print("=" * 60)
    print("步骤1：创建最终企业名单表")
    print("=" * 60)

    # 删除旧表
    cursor.execute(f"DROP TABLE IF EXISTS {FINALLIST_TABLE}")
    conn.commit()

    # 创建新表
    create_sql = f"""
    CREATE TABLE {FINALLIST_TABLE} AS
    SELECT DISTINCT company_name, industry_name, a.nodes, node_level, parent_node,
                    CASE
                        WHEN certainty = 4 THEN 25
                        WHEN certainty = 3 THEN 50
                        WHEN certainty = 2 THEN 75
                        WHEN certainty = 1 THEN 99
                        WHEN company_name IN (SELECT DISTINCT company_name FROM {SPLIT_TABLE}) THEN 9999
                        WHEN certainty = 'None' THEN 25
                        ELSE certainty
                    END AS score,
                    nodes_definition
    FROM {RESULT_FINAL_TABLE} a
    INNER JOIN {CHAIN_TABLE} b
        ON a.industry_name = b.chain_name COLLATE utf8mb4_unicode_ci
        AND a.nodes = b.nodes COLLATE utf8mb4_unicode_ci
    WHERE industry_name = '{INDUSTRY_NAME}'
    ORDER BY industry_name, a.nodes, score DESC
    """
    cursor.execute(create_sql)
    conn.commit()

    # 统计记录数
    cursor.execute(f"SELECT COUNT(*) FROM {FINALLIST_TABLE}")
    count = cursor.fetchone()[0]
    print(f"表 {FINALLIST_TABLE} 创建完成，共 {count} 条记录")

    cursor.close()
    conn.close()


def step2_create_toplist():
    """
    步骤2：创建头部企业表
    从步骤14的拆分结果中筛选头部企业
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("步骤2：创建头部企业表")
    print("=" * 60)

    # 删除旧表
    cursor.execute(f"DROP TABLE IF EXISTS {TOPLIST_TABLE}")
    conn.commit()

    # 创建新表
    create_sql = f"""
    CREATE TABLE {TOPLIST_TABLE} AS
    SELECT * FROM {SPLIT_TABLE}
    WHERE industry_name = '{INDUSTRY_NAME}'
    """
    cursor.execute(create_sql)
    conn.commit()

    # 统计记录数
    cursor.execute(f"SELECT COUNT(*) FROM {TOPLIST_TABLE}")
    count = cursor.fetchone()[0]
    print(f"表 {TOPLIST_TABLE} 创建完成，共 {count} 条头部企业记录")

    cursor.close()
    conn.close()


def step3_create_indexes():
    """
    步骤3：建立索引加快查询速度
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("步骤3：建立索引")
    print("=" * 60)

    # 为最终名单表创建索引
    index_sql_1 = f"CREATE INDEX idx_company_name ON {FINALLIST_TABLE} (company_name(255))"
    index_sql_2 = f"CREATE INDEX idx_score ON {FINALLIST_TABLE} (score)"
    index_sql_3 = f"CREATE INDEX idx_company_name_top ON {TOPLIST_TABLE} (company_name(255))"

    for sql in [index_sql_1, index_sql_2, index_sql_3]:
        try:
            cursor.execute(sql)
            print(f"索引创建成功: {sql.split('ON')[1].strip() if 'ON' in sql else sql}")
        except Exception as e:
            if "Duplicate key name" in str(e):
                print(f"索引已存在，跳过")
            else:
                print(f"索引创建失败: {e}")

    conn.commit()
    print("索引创建完成")

    cursor.close()
    conn.close()


def step4_update_top_score():
    """
    步骤4：更新头部企业分数为 9999
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("步骤4：更新头部企业分数")
    print("=" * 60)

    # 统计更新前的记录数
    cursor.execute(f"SELECT COUNT(*) FROM {FINALLIST_TABLE} WHERE score = '9999'")
    count_before = cursor.fetchone()[0]
    print(f"更新前分数为 9999 的记录数: {count_before}")

    # 更新头部企业分数
    update_sql = f"""
    UPDATE {FINALLIST_TABLE} AS b
    JOIN {TOPLIST_TABLE} AS a
        ON b.company_name = a.company_name
    SET b.score = '9999'
    WHERE b.score <> '9999'
    """
    cursor.execute(update_sql)
    affected_rows = cursor.rowcount
    conn.commit()

    # 统计更新后的记录数
    cursor.execute(f"SELECT COUNT(*) FROM {FINALLIST_TABLE} WHERE score = '9999'")
    count_after = cursor.fetchone()[0]

    print(f"更新了 {affected_rows} 条记录")
    print(f"更新后分数为 9999 的记录数: {count_after}")

    cursor.close()
    conn.close()


def step5_remove_nbsp():
    """
    步骤5：删除不间断空格
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("步骤5：删除不间断空格")
    print("=" * 60)

    # 统计包含不间断空格的记录数
    cursor.execute(f"SELECT COUNT(*) FROM {FINALLIST_TABLE} WHERE company_name LIKE '% %'")
    count_before = cursor.fetchone()[0]
    print(f"包含不间断空格的记录数: {count_before}")

    if count_before > 0:
        # 删除不间断空格
        update_sql = f"""
        UPDATE {FINALLIST_TABLE}
        SET company_name = REPLACE(company_name, ' ', '')
        WHERE company_name LIKE '% %'
        """
        cursor.execute(update_sql)
        affected_rows = cursor.rowcount
        conn.commit()

        # 统计处理后的记录数
        cursor.execute(f"SELECT COUNT(*) FROM {FINALLIST_TABLE} WHERE company_name LIKE '% %'")
        count_after = cursor.fetchone()[0]

        print(f"处理了 {affected_rows} 条记录")
        print(f"处理后剩余不间断空格的记录数: {count_after}")
    else:
        print("无需处理，没有发现不间断空格")

    cursor.close()
    conn.close()


def step6_export_to_excel():
    """
    步骤6：导出到 Excel
    """
    conn = pymysql.connect(**db_config)

    print("\n" + "=" * 60)
    print("步骤6：导出到 Excel")
    print("=" * 60)

    sql = f"""
    SELECT DISTINCT company_name, industry_name, nodes, node_level, parent_node, score
    FROM {FINALLIST_TABLE}
    ORDER BY score DESC
    """

    df = pd.read_sql(sql, conn)
    conn.close()

    df.to_excel(OUTPUT_PATH, index=False, engine='openpyxl')
    print(f"导出完成，共 {len(df)} 条记录")
    print(f"文件路径: {OUTPUT_PATH}")


def main():
    print("\n" + "=" * 60)
    print("输出最终企业名单处理流程")
    print("=" * 60)
    print(f"\n配置信息:")
    print(f"  产业链名称: {INDUSTRY_NAME}")
    print(f"  最终结果表: {RESULT_FINAL_TABLE}")
    print(f"  节点信息表: {CHAIN_TABLE}")
    print(f"  拆分结果表: {SPLIT_TABLE}")
    print(f"  输出名单表: {FINALLIST_TABLE}")
    print(f"  头部企业表: {TOPLIST_TABLE}")
    print(f"  Excel路径: {OUTPUT_PATH}")

    # 执行六个步骤
    step1_create_finallist()
    step2_create_toplist()
    step3_create_indexes()
    step4_update_top_score()
    step5_remove_nbsp()
    step6_export_to_excel()

    print("\n" + "=" * 60)
    print("所有步骤执行完成！")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
