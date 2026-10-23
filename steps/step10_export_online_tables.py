"""
步骤10：输出上线表

功能：输出两张上线表（结构表和企业表）
"""

import pandas as pd
import pymysql
from sqlalchemy import create_engine
from datetime import datetime
import os


def step10_export_online_tables(industry_name, tables, whitelist_data=None, progress_callback=None):
    """
    输出上线表

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
    finallist_table = tables['company_nodes_finallist']
    chain_table = tables['chain_needcomp']
    structure_output = tables['industry_structure_output']
    company_output = tables['company_list_output']

    print(f"\n{'='*40}")
    print(f"步骤10：输出上线表")
    print(f"产业链名称: {industry_name}")
    print(f"{'='*40}")

    conn = pymysql.connect(host=host, user=user, password=password, database=database, port=port,
                           connect_timeout=60, read_timeout=3600, write_timeout=3600)
    cursor = conn.cursor()

    try:
        # 读取数据并添加父节点列
        query = f"""
        SELECT a.id, a.company_name, a.industry_name, a.nodes,
               a.node_level, a.parent_node, a.score,
               b.parent_id
        FROM {finallist_table} a
        LEFT JOIN {chain_table} b ON a.nodes COLLATE utf8mb4_unicode_ci = b.nodes AND b.chain_name = %s
        WHERE a.industry_name = %s
        """
        df = pd.read_sql_query(query, conn, params=(industry_name, industry_name))

        if df.empty:
            print(f"警告：产业链 '{industry_name}' 没有最终名单数据")
            return {"step": 10, "name": "输出上线表", "status": "skipped", "reason": "无数据"}

        print(f"读取数据: {len(df)} 条")
        if progress_callback:
            progress_callback('progress', {'stage': 'reading', 'message': f'读取数据: {len(df)} 条'})

        # 添加父节点列
        def get_all_parents(node, parent_dict, level=0):
            parents = []
            current_node = node
            visited = set()  # 防止循环引用
            while current_node in parent_dict and current_node not in visited:
                visited.add(current_node)
                parent_list = parent_dict[current_node]
                if parent_list:  # 确保列表不为空
                    parent = parent_list[0]
                    parents.append((parent, level))
                    current_node = parent
                    level += 1
                else:
                    break
            return parents

        # 获取父节点映射
        parent_query = f"SELECT nodes, parent_node FROM {chain_table} WHERE chain_name = %s"
        parent_df = pd.read_sql_query(parent_query, conn, params=(industry_name,))
        parent_dict = {}
        for _, row in parent_df.iterrows():
            node = row['nodes']
            parent = row['parent_node']
            # 只为有父节点的节点创建条目
            if pd.notna(parent) and parent:
                if node not in parent_dict:
                    parent_dict[node] = []
                parent_dict[node].append(parent)

        # 添加所有父节点列
        df['所有父节点'] = df['nodes'].apply(lambda x: get_all_parents(x, parent_dict) if x in parent_dict else [])

        max_level = 6
        for i in range(max_level + 1):
            df[f'父节点_{i}'] = df['所有父节点'].apply(
                lambda x: next((p for p, l in x if l == i), None) if x else None
            )

        df.drop(columns=['所有父节点'], inplace=True)

        # 创建临时上传表
        upload_table = f"company_nodes_upload_temp_{industry_name.replace(' ', '_')}"
        engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}",
                               connect_args={'connect_timeout': 60, 'read_timeout': 3600, 'write_timeout': 3600})

        # 删除旧表
        cursor.execute(f"DROP TABLE IF EXISTS {upload_table}")
        conn.commit()

        # 上传数据到临时表
        df.to_sql(upload_table, engine, index=False, if_exists='fail')
        # 大数据量上传后重连，避免 wait_timeout 掐断后续查询连接
        conn.ping(reconnect=True)
        print(f"数据已上传到临时表: {upload_table}")
        if progress_callback:
            progress_callback('progress', {'stage': 'upload_temp', 'message': f'数据已上传到临时表'})

        # 步骤1：输出结构表
        print("\n[1/2] 创建结构表...")

        # 先获取最大层级数，用于动态生成列
        max_level_query = """
        SELECT MAX(node_level) as max_level
        FROM industrial_chain.industrial_chain_structure
        WHERE chain_name = %s AND status = 1
        """
        cursor.execute(max_level_query, (industry_name,))
        max_level_result = cursor.fetchone()
        max_node_level = max_level_result[0] if max_level_result and max_level_result[0] else 3
        print(f"最大层级数: {max_node_level}")

        # 创建表（如果不存在），添加 industry_name 字段
        create_structure_sql = f"""
        CREATE TABLE IF NOT EXISTS {structure_output} (
            id INT AUTO_INCREMENT PRIMARY KEY,
            编码 INT,
            产业环节 VARCHAR(255),
            父级id INT,
            级别 INT,
            industry_name VARCHAR(100) COMMENT '产业链名称',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_industry_name (industry_name),
            INDEX idx_产业环节 (产业环节)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
        cursor.execute(create_structure_sql)
        conn.commit()

        # 删除当前产业链的旧数据
        delete_structure_sql = f"DELETE FROM {structure_output} WHERE industry_name = %s"
        cursor.execute(delete_structure_sql, (industry_name,))
        conn.commit()

        # 使用 business_data 连接执行跨库查询获取结构数据
        # 获取根节点的ID（从 industrial_chain.industrial_chain_structure）
        root_id_query = """
        SELECT MIN(id) as id
        FROM industrial_chain.industrial_chain_structure
        WHERE chain_name = %s
          AND node_level = 0
          AND (status = 1 OR status IS NULL)
        """
        cursor.execute(root_id_query, (industry_name,))
        root_result = cursor.fetchone()
        root_id = root_result[0] if root_result and root_result[0] else None

        print(f"根节点ID: {root_id}")

        if not root_id:
            print(f"警告：未找到产业链 '{industry_name}' 的根节点")
            return {"step": 10, "name": "输出上线表", "status": "error", "error": "未找到根节点"}

        # 插入所有层级节点（统一使用原始节点名称，不添加"产业链"前缀）
        insert_all_levels_sql = f"""
        INSERT INTO {structure_output} (编码, 产业环节, 父级id, 级别, industry_name)
        SELECT MIN(ics.id) AS 编码,
               ics.nodes AS 产业环节,
               ics.parent_id AS 父级id,
               ics.node_level AS 级别,
               %s AS industry_name
        FROM industrial_chain.industrial_chain_structure ics
        WHERE ics.chain_name = %s AND ics.node_level >= 1 AND ics.status = 1
        GROUP BY ics.nodes, ics.node_level, ics.parent_id
        ORDER BY ics.node_level, ics.nodes
        """
        cursor.execute(insert_all_levels_sql, (industry_name, industry_name))
        conn.commit()
        all_levels_count = cursor.rowcount
        print(f"  所有层级节点: {all_levels_count} 条")

        # 验证结果
        verify_sql = f"""
        SELECT 级别, COUNT(*) as count,
               SUM(CASE WHEN 父级id IS NULL OR 父级id = 0 THEN 1 ELSE 0 END) as null_count
        FROM {structure_output}
        WHERE industry_name = %s
        GROUP BY 级别
        ORDER BY 级别
        """
        cursor.execute(verify_sql, (industry_name,))
        print("  结构表验证结果:")
        structure_count = 0
        has_null_parent = False
        for row in cursor.fetchall():
            level, count, null_count = row
            structure_count += count
            if null_count > 0:
                has_null_parent = True
            print(f"    级别 {level}: {count} 条, 父级id为空: {null_count}")

        # 修复parent_id为空的记录（从parent_node查找对应id）
        if has_null_parent:
            print("  修复parent_id为空的记录...")
            # 使用industrial_chain.industrial_chain_structure表更新parent_id
            fix_sql = f"""
            UPDATE {structure_output} iso
            INNER JOIN (
                SELECT ics1.id AS child_id, ics2.id AS correct_parent_id
                FROM industrial_chain.industrial_chain_structure ics1
                INNER JOIN industrial_chain.industrial_chain_structure ics2
                    ON ics1.parent_node = ics2.nodes
                    AND ics1.chain_name = ics2.chain_name
                WHERE ics1.chain_name = %s
                  AND ics1.parent_id IS NULL
                  AND ics2.id IS NOT NULL
                  AND (ics1.status = 1 OR ics1.status IS NULL)
                  AND (ics2.status = 1 OR ics2.status IS NULL)
            ) fix_data ON iso.编码 = fix_data.child_id
            SET iso.父级id = fix_data.correct_parent_id
            WHERE iso.industry_name = %s
            """
            try:
                cursor.execute(fix_sql, (industry_name, industry_name))
                conn.commit()
                if cursor.rowcount > 0:
                    print(f"    修复了 {cursor.rowcount} 条记录")
            except Exception as e:
                print(f"    修复parent_id时出错: {e}")

        if progress_callback:
            progress_callback('progress', {'stage': 1, 'total_stages': 2, 'structure_count': structure_count, 'message': f'结构表记录数: {structure_count}'})

        # 步骤2：输出企业表
        print("\n[2/2] 创建企业表...")

        # 动态创建企业表，根据最大层级数生成对应数量的列
        level_columns = []
        for i in range(1, max_node_level + 1):
            level_columns.append(f"层级{i} VARCHAR(255)")

        columns_def = ",\n            ".join(level_columns)

        # 删除当前产业链的旧数据（不能 DROP TABLE，会清掉所有产业链的数据）
        delete_company_sql = f"DELETE FROM {company_output} WHERE industry_name = %s"
        cursor.execute(delete_company_sql, (industry_name,))
        conn.commit()

        # 确保表存在（列结构不变，不需要每次重建）
        create_company_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {company_output} (
            id INT AUTO_INCREMENT PRIMARY KEY,
            {columns_def},
            供应商 VARCHAR(255),
            industry_name VARCHAR(100) COMMENT '产业链名称',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_industry_name (industry_name),
            INDEX idx_供应商 (供应商)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
        cursor.execute(create_company_table_sql)
        conn.commit()

        # 表已存在但可能缺少高层层级列(如层级4/5/6)，动态补齐，避免 Unknown column
        cursor.execute(f"SHOW COLUMNS FROM {company_output}")
        existing_cols = {r[0] for r in cursor.fetchall()}
        for i in range(1, max_node_level + 1):
            col = f"层级{i}"
            if col not in existing_cols:
                cursor.execute(f"ALTER TABLE {company_output} ADD COLUMN `{col}` VARCHAR(255) DEFAULT NULL")
                conn.commit()
                print(f"  已补充缺失列: {col}")

        # 构建动态插入SQL
        # 父节点_0是直接父节点，父节点_1是更上一级...
        # 对于3级产业链：父节点_2=层级1(上游)，父节点_1=层级2，父节点_0=层级3(最高层级的子节点)
        # 但实际上nodes才是最底层的节点，所以需要调整映射

        # 重新理解：nodes是企业所在的节点（最底层）
        # 父节点_0是nodes的直接父节点
        # 父节点_1是父节点_0的父节点
        # ...

        # 对于3级产业链（上游->氢气储运->储氢）：
        # - 层级1: 上游 (父节点_1)
        # - 层级2: 氢气储运 (父节点_0)
        # - 层级3: 储氢 (nodes)

        select_parts = []
        column_names = []

        # 从最高层级（层级1）开始，向下构建到最底层（层级max_node_level）
        for i in range(max_node_level):
            # 层级1对应父节点_(max_node_level-2)，层级2对应父节点_(max_node_level-3)，...
            # 最后层级max_node_level对应nodes
            parent_index = max_node_level - 2 - i
            if parent_index >= 0:
                select_parts.append(f"a.`父节点_{parent_index}` AS `层级{i+1}`")
            else:
                # 不应该到这里，但作为fallback
                select_parts.append(f"a.nodes AS `层级{i+1}`")
            column_names.append(f"`层级{i+1}`")

        # 最底层使用nodes
        if max_node_level >= 1:
            # 实际上nodes是层级max_node_level
            # 所以我们需要调整上面的逻辑
            pass

        # 重新构建：从最顶层父节点开始
        # 父节点链：[父节点_0, 父节点_1, 父节点_2, ...] 其中父节点_0是直接父节点
        # 对于层级1的节点，它的父节点链是空的
        # 对于层级2的节点，父节点_0是层级1
        # 对于层级3的节点，父节点_0是层级2，父节点_1是层级1

        # 重新构建查询逻辑
        select_parts = []
        column_names = []

        for i in range(max_node_level):
            # 层级i+1对应的父节点索引
            # 层级1: 父节点_(max_node_level-2)
            # 层级2: 父节点_(max_node_level-3)
            # ...
            # 层级max_node_level: nodes（不是父节点）
            level_num = i + 1
            if level_num == max_node_level:
                # 最底层使用nodes
                select_parts.append(f"a.`nodes` AS `层级{level_num}`")
            else:
                # 计算父节点索引：max_node_level - level_num - 1
                # 例如3级产业链：
                # - 层级1: 3-1-1=1，即父节点_1
                # - 层级2: 3-2-1=0，即父节点_0
                # - 层级3: nodes
                parent_index = max_node_level - level_num - 1
                if parent_index >= 0:
                    select_parts.append(f"COALESCE(a.`父节点_{parent_index}`, '') AS `层级{level_num}`")
                else:
                    select_parts.append(f"'' AS `层级{level_num}`")
            column_names.append(f"`层级{level_num}`")

        select_clause = ",\n            ".join(select_parts)
        columns_clause = ", ".join(column_names)

        insert_company_sql = f"""
        INSERT INTO {company_output} ({columns_clause}, 供应商, industry_name)
        SELECT DISTINCT
            {select_clause},
            a.company_name AS 供应商,
            %s AS industry_name
        FROM {upload_table} a
        WHERE a.nodes IS NOT NULL
        """
        cursor.execute(insert_company_sql, (industry_name,))
        conn.commit()

        cursor.execute(f"SELECT COUNT(*) FROM {company_output} WHERE industry_name = %s", (industry_name,))
        company_count = cursor.fetchone()[0]
        print(f"  企业表记录数: {company_count}")
        if progress_callback:
            progress_callback('progress', {'stage': 2, 'total_stages': 2, 'company_count': company_count, 'message': f'企业表记录数: {company_count}'})

        # 导出到 Excel
        output_dir = os.environ.get("FILLED_REPORTS_DIR", "/root/mix_project/filled_reports")
        os.makedirs(output_dir, exist_ok=True)

        current_date = datetime.now().strftime("%Y%m%d")
        filename = f"产业链上线结果_{industry_name}_{current_date}.xlsx"
        output_file = os.path.join(output_dir, filename)

        # 只导出当前产业链的数据
        df_structure = pd.read_sql(f"SELECT * FROM {structure_output} WHERE industry_name = %s", conn, params=(industry_name,))
        df_company = pd.read_sql(f"SELECT * FROM {company_output} WHERE industry_name = %s", conn, params=(industry_name,))

        # 超过100万行时截断为100万，避免超过 Excel 单表上限导致 sheet too large
        MAX_EXCEL_ROWS = 1000000
        if len(df_company) > MAX_EXCEL_ROWS:
            print(f"  企业表 {len(df_company)} 行超过100万，截断为前 100 万行导出")
            df_company = df_company.head(MAX_EXCEL_ROWS)

        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            df_structure.to_excel(writer, sheet_name='结构表', index=False)
            df_company.to_excel(writer, sheet_name='企业表', index=False)

        print(f"\n导出Excel: {output_file}")
        if progress_callback:
            progress_callback('info', f'导出Excel: {output_file}')

        # 清理临时表
        cursor.execute(f"DROP TABLE IF EXISTS {upload_table}")
        conn.commit()

        print(f"步骤10完成")
        return {
            "step": 10,
            "name": "输出上线表",
            "status": "completed",
            "structure_count": structure_count,
            "company_count": company_count,
            "file": output_file
        }

    except Exception as e:
        print(f"步骤10执行失败: {e}")
        return {"step": 10, "name": "输出上线表", "status": "error", "error": str(e)}
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    from auto_industry_chain_pipeline import TABLES
    step10_export_online_tables("生物医药产业", TABLES)
