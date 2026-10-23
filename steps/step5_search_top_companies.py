"""
步骤5：搜索头部企业

功能：从白名单表读取头部企业数据，创建头部企业待处理表
"""

import os
import pymysql
import pandas as pd


def step5_search_top_companies(industry_name, tables, whitelist_data=None, progress_callback=None):
    """
    从白名单表读取头部企业数据

    Args:
        industry_name: 产业链名称
        tables: 表名配置字典
        whitelist_data: 白名单数据（如果提供则使用，否则从数据库读取）
    """
    # 数据库连接配置
    host = '8.141.5.67'
    user = 'root'
    password = os.getenv('DB_PASSWORD')
    database = 'business_data'
    port = 3306

    # 表名
    whitelist_table = tables['whitelist_company']
    company_nodes_mapping = tables['company_nodes_mapping']
    topcompany_table = tables.get('company_nodes_top', 'company_nodes_top')

    print(f"\n{'='*40}")
    print(f"步骤5：搜索头部企业")
    print(f"产业链名称: {industry_name}")
    print(f"目标表: {topcompany_table}")
    print(f"{'='*40}")

    conn = pymysql.connect(host=host, user=user, password=password, database=database, port=port)
    cursor = conn.cursor()

    try:
        # 创建头部企业表
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {topcompany_table} (
            id INT AUTO_INCREMENT PRIMARY KEY,
            industry_chain VARCHAR(100) NOT NULL COMMENT '产业链名称',
            company_name VARCHAR(255) NOT NULL COMMENT '企业名称',
            position VARCHAR(50) COMMENT '上游/中游/下游',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_industry_chain (industry_chain),
            INDEX idx_company_name (company_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='头部企业待处理表'
        """
        cursor.execute(create_table_sql)
        conn.commit()
        print(f"表 {topcompany_table} 已确保存在")

        # 清空当前产业链的旧数据
        delete_sql = f"DELETE FROM {topcompany_table} WHERE industry_chain = %s"
        cursor.execute(delete_sql, (industry_name,))
        conn.commit()
        print(f"已清空产业链 '{industry_name}' 的旧数据")

        # 获取白名单数据
        if whitelist_data:
            # 使用传入的白名单数据
            companies = whitelist_data
            print(f"使用传入的白名单数据: {len(companies)} 条")
        else:
            # 从数据库读取白名单
            query = f"""
            SELECT industry_name, position, company_name
            FROM {whitelist_table}
            WHERE industry_name = %s
            """
            cursor.execute(query, (industry_name,))
            companies = cursor.fetchall()
            print(f"从数据库读取白名单: {len(companies)} 条")

        if not companies:
            print(f"警告：产业链 '{industry_name}' 没有白名单数据，步骤6将通过AI搜索补充企业")
            # 无白名单不是错误，后续步骤会通过AI搜索补充
            return {"step": 5, "name": "搜索头部企业", "status": "completed", "count": 0, "note": "无白名单，步骤6将AI搜索"}

        # 过滤掉已经在 company_nodes_mapping 中的企业
        cursor.execute(
            f"SELECT DISTINCT company_name FROM {company_nodes_mapping} WHERE industry_name = %s",
            (industry_name,)
        )
        existing_companies = {row[0] for row in cursor.fetchall() if row and row[0]}

        filtered_companies = []
        for company in companies:
            company_name = company[2] if len(company) > 2 else company[0]
            position = company[1] if len(company) > 1 else None

            if company_name not in existing_companies:
                filtered_companies.append((industry_name, company_name, position))

        print(f"过滤后待处理企业: {len(filtered_companies)} 条")

        # 插入数据
        if filtered_companies:
            insert_sql = f"""
            INSERT INTO {topcompany_table} (industry_chain, company_name, position)
            VALUES (%s, %s, %s)
            """
            cursor.executemany(insert_sql, filtered_companies)
            conn.commit()
            print(f"成功插入 {cursor.rowcount} 条头部企业数据")

        print(f"步骤5完成，头部企业数据已准备")
        return {"step": 5, "name": "搜索头部企业", "status": "completed", "count": len(filtered_companies)}

    except Exception as e:
        print(f"步骤5执行失败: {e}")
        return {"step": 5, "name": "搜索头部企业", "status": "error", "error": str(e)}
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    from auto_industry_chain_pipeline import TABLES
    step5_search_top_companies("生物医药产业", TABLES)
