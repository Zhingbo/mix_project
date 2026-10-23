"""
步骤7：拆分结果

功能：��匹配结果按分号拆分，每个节点一行
"""

import os
import pandas as pd
import pymysql
import time


def step7_split_results(industry_name, tables, whitelist_data=None, progress_callback=None):
    """
    拆分匹配结果

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
    source_table = tables.get('company_nodes_info_result', 'company_nodes_info_result')
    target_table = tables.get('company_nodes_info_split', 'company_nodes_info_split')

    print(f"\n{'='*40}")
    print(f"步骤7：拆分结果")
    print(f"产业链名称: {industry_name}")
    print(f"源表: {source_table}")
    print(f"目标表: {target_table}")
    print(f"{'='*40}")

    conn = pymysql.connect(host=host, user=user, password=password, database=database, port=port)

    try:
        # 查询数据
        query = f"""
        SELECT company_name, industry_name, matched_nodes, match_reason, score
        FROM {source_table}
        WHERE industry_name = %s
        """
        df = pd.read_sql_query(query, conn, params=(industry_name,))

        if df.empty:
            print(f"警告：产业链 '{industry_name}' 没有待拆分的数据")
            if progress_callback:
                progress_callback('warning', f'产业链 {industry_name} 没有待拆分的数据（步骤6无数据）')
            return {"step": 7, "name": "拆分结果", "status": "skipped", "reason": "无数据"}

        print(f"读取数据: {len(df)} 条")

        # 清理数据
        df['matched_nodes'] = df['matched_nodes'].astype(str).str.replace('"', '').str.replace("'", "")
        df['match_reason'] = df['match_reason'].astype(str).str.replace('"', '').str.replace("'", "")
        df['score'] = df['score'].astype(str).str.replace('"', '').str.replace("'", "")

        # 拆分函数
        def split_columns(row):
            matched_nodes = row['matched_nodes'].replace(", ", ";").replace('；', ';').split(';') if row['matched_nodes'] and row['matched_nodes'] != 'nan' else []
            match_reason = row['match_reason'].replace(", ", ";").replace('；', ';').split(';') if row['match_reason'] and row['match_reason'] != 'nan' else []
            score = row['score'].replace(", ", ";").replace('；', ';').split(';') if row['score'] and row['score'] != 'nan' else []

            max_length = max(len(matched_nodes), len(match_reason), len(score))

            if len(matched_nodes) < max_length:
                matched_nodes += [matched_nodes[-1] if matched_nodes else ''] * (max_length - len(matched_nodes))
            if len(match_reason) < max_length:
                match_reason += [match_reason[-1] if match_reason else ''] * (max_length - len(match_reason))
            if len(score) < max_length:
                score += [score[-1] if score else ''] * (max_length - len(score))

            rows = []
            for i in range(max_length):
                rows.append({
                    'company_name': row['company_name'],
                    'industry_name': row['industry_name'],
                    'matched_node': matched_nodes[i].strip() if matched_nodes else '',
                    'match_reason': match_reason[i].strip() if match_reason else '',
                    'score': score[i].strip() if score else ''
                })
            return rows

        # 应用拆分
        all_rows = []
        for _, row in df.iterrows():
            all_rows.extend(split_columns(row))

        result_df = pd.DataFrame(all_rows)
        print(f"拆分后数据: {len(result_df)} 条")

        # 创建目标表
        cursor = conn.cursor()
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {target_table} (
            company_name VARCHAR(255),
            industry_name VARCHAR(255),
            matched_node VARCHAR(255),
            match_reason TEXT,
            score TEXT
        )
        """
        cursor.execute(create_table_query)
        cursor.execute(f"ALTER TABLE {target_table} MODIFY COLUMN score TEXT")
        conn.commit()

        temp_table = f"{target_table}_tmp_{int(time.time())}"
        create_temp_query = f"""
        CREATE TABLE {temp_table} (
            company_name VARCHAR(255),
            industry_name VARCHAR(255),
            matched_node VARCHAR(255),
            match_reason TEXT,
            score TEXT
        )
        """
        cursor.execute(create_temp_query)
        conn.commit()

        # 先写入临时表，全部成功后再替换正式表，避免失败时清空旧结果。
        insert_query = f"""
        INSERT INTO {temp_table} (company_name, industry_name, matched_node, match_reason, score)
        VALUES (%s, %s, %s, %s, %s)
        """
        data_to_insert = [tuple(row) for row in result_df.values]
        cursor.executemany(insert_query, data_to_insert)
        conn.commit()
        print(f"插入数据: {cursor.rowcount} 条")

        # 更新 score 为 9999
        update_sql = f"UPDATE {temp_table} SET score = '1' WHERE industry_name = %s"
        cursor.execute(update_sql, (industry_name,))
        conn.commit()
        update_sql2 = f"""
UPDATE {temp_table} t
JOIN whitelist_company w ON t.company_name = w.company_name COLLATE utf8mb4_unicode_ci AND w.industry_name = %s
SET t.score = '9999'"""
        cursor.execute(update_sql2, (industry_name,))
        conn.commit()
        print(f"白名单企业已标 9999，其它=1")

        delete_sql = f"DELETE FROM {target_table} WHERE industry_name = %s"
        cursor.execute(delete_sql, (industry_name,))
        cursor.execute(f"""
            INSERT INTO {target_table} (company_name, industry_name, matched_node, match_reason, score)
            SELECT company_name, industry_name, matched_node, match_reason, score
            FROM {temp_table}
        """)
        cursor.execute(f"DROP TABLE {temp_table}")
        conn.commit()

        cursor.close()

        print(f"步骤7完成")
        return {"step": 7, "name": "拆分结果", "status": "completed", "count": len(result_df)}

    except Exception as e:
        print(f"步骤7执行失败: {e}")
        try:
            if 'cursor' in locals() and 'temp_table' in locals():
                cursor.execute(f"DROP TABLE IF EXISTS {temp_table}")
                conn.commit()
        except Exception:
            pass
        return {"step": 7, "name": "拆分结果", "status": "error", "error": str(e)}
    finally:
        conn.close()


if __name__ == "__main__":
    from auto_industry_chain_pipeline import TABLES
    step7_split_results("生物医药产业", TABLES)
