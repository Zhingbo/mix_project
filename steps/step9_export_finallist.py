"""
步骤9：输出最终名单

功能：将最终结果输出到 finallist 表和 Excel 文件
"""

import pandas as pd
import pymysql
from datetime import datetime
import os
import hashlib


def step9_export_finallist(industry_name, tables, whitelist_data=None, progress_callback=None):
    """
    输出最终名单

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
    source_table = 'company_nodes_final_' + hashlib.md5(str(industry_name).encode('utf-8')).hexdigest()[:12]
    target_table = tables['company_nodes_finallist']
    chain_table = tables['chain_needcomp']

    print(f"\n{'='*40}")
    print(f"步骤9：输出最终名单")
    print(f"产业链名称: {industry_name}")
    print(f"目标表: {target_table}")
    print(f"{'='*40}")

    conn = pymysql.connect(host=host, user=user, password=password, database=database, port=port)

    try:
        # 查询最终结果，带上节点层级信息
        # 只获取2级及以下节点的企业（过滤掉0级中心节点和1级上中下游节点）
        query = f"""
        SELECT DISTINCT
            a.company_name,
            a.industry_name,
            a.nodes,
            b.node_level,
            b.parent_node,
            a.certainty as score
        FROM {source_table} a
        LEFT JOIN {chain_table} b ON a.nodes COLLATE utf8mb4_unicode_ci = b.nodes AND b.chain_name = %s
        WHERE a.industry_name = %s
          AND (b.node_level IS NULL OR b.node_level >= 1)
        ORDER BY a.company_name, a.nodes
        """
        df = pd.read_sql_query(query, conn, params=(industry_name, industry_name))

        if df.empty:
            print(f"警告：产业链 '{industry_name}' 没有最终结果数据")
            return {"step": 9, "name": "输出最终名单", "status": "skipped", "reason": "无数据"}

        print(f"读取数据: {len(df)} 条")
        if progress_callback:
            progress_callback('progress', {'stage': 'reading', 'message': f'读取数据: {len(df)} 条'})

        # 创建目标表
        cursor = conn.cursor()
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {target_table} (
            id INT AUTO_INCREMENT PRIMARY KEY,
            company_name VARCHAR(255),
            industry_name VARCHAR(100),
            nodes VARCHAR(255),
            node_level INT,
            parent_node VARCHAR(255),
            score VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_company_name (company_name),
            INDEX idx_industry_name (industry_name),
            INDEX idx_nodes (nodes)
        )
        """
        cursor.execute(create_table_query)
        conn.commit()

        # 清空当前产业链的旧数据
        delete_sql = f"DELETE FROM {target_table} WHERE industry_name = %s"
        cursor.execute(delete_sql, (industry_name,))
        conn.commit()

        # 插入数据
        insert_query = f"""
        INSERT INTO {target_table} (company_name, industry_name, nodes, node_level, parent_node, score)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        data_to_insert = [
            (row['company_name'], row['industry_name'], row['nodes'],
             row['node_level'], row['parent_node'], ('1' if row['score'] is None or str(row['score']).strip() in ('', 'None', 'nan') else str(row['score'])))
            for _, row in df.iterrows()
        ]
        cursor.executemany(insert_query, data_to_insert)
        conn.commit()
        initial_count = cursor.rowcount
        print(f"插入数据: {initial_count} 条")
        if progress_callback:
            progress_callback('progress', {'stage': 'inserting', 'message': f'插入数据: {initial_count} 条'})

        print(f"步骤9完成，总计插入: {initial_count} 条")

        cursor.close()

        # 导出到 Excel
        output_dir = os.environ.get("FILLED_REPORTS_DIR", "/root/mix_project/filled_reports")
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"standard_{industry_name}_{timestamp}.xlsx"
        output_file = os.path.join(output_dir, filename)

        # Excel 单表上限 1048576 行, 超了截断导出(数据库仍保留全量)
        MAX_EXCEL_ROWS = 1000000
        if len(df) > MAX_EXCEL_ROWS:
            print(f"最终名单 {len(df)} 行超过 Excel 上限, 导出前 {MAX_EXCEL_ROWS} 行")
            df = df.head(MAX_EXCEL_ROWS)
        df.to_excel(output_file, index=False, engine='openpyxl')
        print(f"导出Excel: {output_file}")
        if progress_callback:
            progress_callback('progress', {'stage': 'exporting', 'message': f'导出Excel: {output_file}'})

        print(f"步骤9完成")
        return {"step": 9, "name": "输出最终名单", "status": "completed", "count": len(df), "file": output_file}

    except Exception as e:
        print(f"步骤9执行失败: {e}")
        return {"step": 9, "name": "输出最终名单", "status": "error", "error": str(e)}
    finally:
        conn.close()


if __name__ == "__main__":
    from auto_industry_chain_pipeline import TABLES
    step9_export_finallist("生物医药产业", TABLES)
