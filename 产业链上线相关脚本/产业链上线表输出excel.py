"""
步骤十一：上传Excel到MySQL + 输出两张上线表

功能说明：
1. 读取步骤十的Excel并上传到MySQL
2. 添加父节点列（父节点_0 到 父节点_6）
3. 执行更新规则（调整父节点关系）
4. 输出两张表：
   - 结构表：产业链层级结构
   - 企业表：应用更新规则后的企业名单
"""

import pandas as pd
import pymysql
from sqlalchemy import create_engine
import os
from datetime import datetime

# ==================== 表名配置 ====================
EXCEL_INPUT = "/root/mix_project/company_nodes_finallist0421.xlsx"         # 步骤十输出
UPLOAD_TABLE = "company_nodes_finallist_upload_0421"                   # 上传后的表
CHAIN_TABLE = "chain_needcomp0421"                                     # 节点信息表
INDUSTRY_NAME = "氢能产业"                                              # 产业链名称

# ==================== 输出配置 ====================
OUTPUT_STRUCTURE_TABLE = "industry_structure_output_0421"              # 输出结构表
OUTPUT_COMPANY_TABLE = "company_list_output_0421"                      # 输出企业表

# ==================== 数据库连接配置 ====================
db_config = {
    'host': '8.141.5.67',
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'charset': 'utf8mb4'
}


def step1_upload_excel_to_mysql():
    """
    步骤1：读取Excel并上传到MySQL
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    print("=" * 60)
    print("步骤1：上传Excel到MySQL")
    print("=" * 60)

    # 读取Excel
    print(f"正在读取Excel: {EXCEL_INPUT}")
    df = pd.read_excel(EXCEL_INPUT)
    print(f"读取完成，共 {len(df)} 行数据")

    # 删除旧表
    cursor.execute(f"DROP TABLE IF EXISTS {UPLOAD_TABLE}")
    conn.commit()

    # 创建新表并上传数据
    engine = create_engine(f"mysql+pymysql://{db_config['user']}:{db_config['password']}@"
                           f"{db_config['host']}:3306/{db_config['database']}")
    df.to_sql(UPLOAD_TABLE, engine, index=False, if_exists='fail')

    print(f"数据已上传到表: {UPLOAD_TABLE}")

    cursor.close()
    conn.close()

    return df


def step2_add_parent_columns(df):
    """
    步骤2：为数据添加父节点列（父节点_0 到 父节点_6）
    """
    print("\n" + "=" * 60)
    print("步骤2：添加父节点列")
    print("=" * 60)

    # 构建父节点字典
    parent_dict = {}
    for _, row in df.iterrows():
        node = row['nodes']
        parent = row['parent_node']
        if node not in parent_dict:
            parent_dict[node] = []
        parent_dict[node].append(parent)

    # 递归获取所有父节点及其层级
    def get_all_parents(node, parent_dict, level=0):
        parents = []
        current_node = node
        while current_node in parent_dict:
            parent = parent_dict[current_node][0]
            parents.append((parent, level))
            current_node = parent
            level += 1
        return parents

    # 添加所有父节点列
    df['所有父节点'] = df['nodes'].apply(lambda x: get_all_parents(x, parent_dict))

    max_level = 6
    for i in range(max_level + 1):
        df[f'父节点_{i}'] = df['所有父节点'].apply(lambda x: next((p for p, l in x if l == i), None))

    df.drop(columns=['所有父节点'], inplace=True)

    # 添加 node_level 列（从 node_level 列获取）
    if 'node_level' in df.columns:
        df['node_level_temp'] = df['node_level']
    else:
        df['node_level_temp'] = 3  # 默认值

    print(f"父节点列添加完成，共 {len(df.columns)} 列")

    return df


def step3_update_parent_relationships():
    """
    步骤3：执行更新规则（调整父节点关系）
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("步骤3：执行更新规则")
    print("=" * 60)

    # 更新规则列表
    update_rules = [
        # 规则组1：根据node_level调整父节点
        f"UPDATE {UPLOAD_TABLE} SET 父节点_6=nodes, 父节点_5=node_level_temp, nodes=父节点_0, node_level_temp=3 WHERE node_level_temp=4",
        f"UPDATE {UPLOAD_TABLE} SET 父节点_6=nodes, 父节点_5=node_level_temp, nodes=父节点_1, node_level_temp=3 WHERE node_level_temp=5",
        f"UPDATE {UPLOAD_TABLE} SET 父节点_6=nodes, 父节点_5=node_level_temp, nodes=父节点_2, node_level_temp=3 WHERE node_level_temp=6",
        f"UPDATE {UPLOAD_TABLE} SET 父节点_6=node_level_temp, nodes=父节点_3, node_level_temp=3 WHERE node_level_temp=7",

        # 规则组2：调整父节点_0和父节点_1的关系
        f"UPDATE {UPLOAD_TABLE} SET 父节点_0=父节点_1, 父节点_1=父节点_2 WHERE 父节点_5=4",
        f"UPDATE {UPLOAD_TABLE} SET 父节点_0=父节点_2, 父节点_1=父节点_3 WHERE 父节点_5=5",
        f"UPDATE {UPLOAD_TABLE} SET 父节点_0=父节点_3, 父节点_1=父节点_4 WHERE 父节点_5=6",
        f"UPDATE {UPLOAD_TABLE} SET 父节点_0=父节点_4, 父节点_1=父节点_5 WHERE 父节点_6=7",

        # 规则组3：处理上游/中游/下游节点
        f"UPDATE {UPLOAD_TABLE} SET 父节点_1=nodes, 父节点_0=NULL, nodes=NULL WHERE node_level_temp=1",
        f"UPDATE {UPLOAD_TABLE} SET 父节点_1=父节点_0, 父节点_0=nodes, nodes=NULL WHERE node_level_temp=2",
        f"UPDATE {UPLOAD_TABLE} SET 父节点_1=父节点_0, 父节点_0=nodes, nodes=NULL WHERE node_level_temp=3 AND (父节点_1 IS NULL OR 父节点_1='{INDUSTRY_NAME}')",
    ]

    for i, rule in enumerate(update_rules, 1):
        cursor.execute(rule)
        affected_rows = cursor.rowcount
        conn.commit()
        print(f"规则 {i}/{len(update_rules)}: 影响 {affected_rows} 行")

    print("更新规则执行完成")

    cursor.close()
    conn.close()


def step4_output_structure_table():
    """
    步骤4A：输出结构表（产业链层级结构）
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("步骤4A：输出结构表")
    print("=" * 60)

    # 删除旧表
    cursor.execute(f"DROP TABLE IF EXISTS {OUTPUT_STRUCTURE_TABLE}")
    conn.commit()

    # 创建结构表（对相同名称的level=1节点去重，保留最小id）
    create_sql = f"""
    CREATE TABLE {OUTPUT_STRUCTURE_TABLE} AS
    SELECT MIN(id) AS 编码,
                    CASE WHEN node_level=1 THEN CONCAT('产业链', nodes) ELSE nodes END AS 产业环节,
                    CASE WHEN node_level=1 THEN NULL ELSE parent_id END AS 父级id,
                    node_level AS 级别
    FROM {CHAIN_TABLE}
    WHERE chain_name='{INDUSTRY_NAME}' AND node_level<>0
    GROUP BY CASE WHEN node_level=1 THEN CONCAT('产业链', nodes) ELSE nodes END,
             CASE WHEN node_level=1 THEN NULL ELSE parent_id END,
             node_level
    ORDER BY 级别, 产业环节
    """
    cursor.execute(create_sql)
    conn.commit()

    # 统计记录数
    cursor.execute(f"SELECT COUNT(*) FROM {OUTPUT_STRUCTURE_TABLE}")
    count = cursor.fetchone()[0]
    print(f"结构表 {OUTPUT_STRUCTURE_TABLE} 创建完成，共 {count} 条记录")

    cursor.close()
    conn.close()


def step5_output_company_table():
    """
    步骤4B：输出企业表（应用更新规则后）
    """
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("步骤4B：输出企业表")
    print("=" * 60)

    # 先执行检验规则
    print("\n执行检验规则...")
    check_sql = f"""
    SELECT DISTINCT CONCAT('产业链', a.父节点_1) AS 一级,
                    a.父节点_0 AS 二级,
                    a.nodes AS 三级,
                    a.company_name,
                    父节点_5, 父节点_6
    FROM {UPLOAD_TABLE} a
    WHERE 父节点_1 NOT IN ('上游', '中游', '下游')
    """
    cursor.execute(check_sql)
    check_results = cursor.fetchall()
    if check_results:
        print(f"警告：检验规则返回 {len(check_results)} 条异常记录")
        for row in check_results[:5]:  # 显示前5条
            print(f"  {row}")
    else:
        print("检验规则通过：无异常记录")

    # 删除旧表
    cursor.execute(f"DROP TABLE IF EXISTS {OUTPUT_COMPANY_TABLE}")
    conn.commit()

    # 创建企业表
    create_sql = f"""
    CREATE TABLE {OUTPUT_COMPANY_TABLE} AS
    SELECT DISTINCT CONCAT('产业链', a.父节点_1) AS 一级,
                    a.父节点_0 AS 二级,
                    a.nodes AS 三级,
                    a.company_name AS 供应商
    FROM {UPLOAD_TABLE} a
    ORDER BY 一级, 二级, 三级
    """
    cursor.execute(create_sql)
    conn.commit()

    # 统计记录数
    cursor.execute(f"SELECT COUNT(*) FROM {OUTPUT_COMPANY_TABLE}")
    count = cursor.fetchone()[0]
    print(f"\n企业表 {OUTPUT_COMPANY_TABLE} 创建完成，共 {count} 条记录")

    cursor.close()
    conn.close()


def step6_export_to_excel():
    """
    步骤5：导出两张表到Excel
    """
    conn = pymysql.connect(**db_config)

    print("\n" + "=" * 60)
    print("步骤5：导出到Excel")
    print("=" * 60)

    # 读取两张表
    df_structure = pd.read_sql(f"SELECT * FROM {OUTPUT_STRUCTURE_TABLE}", conn)
    df_company = pd.read_sql(f"SELECT * FROM {OUTPUT_COMPANY_TABLE}", conn)

    conn.close()

    # 生成输出文件名
    current_date = datetime.now().strftime("%Y%m%d")
    output_dir = "/root/mix_project"
    output_file = os.path.join(output_dir, f"产业链上线结果_{current_date}.xlsx")

    # 写入Excel（两个sheet）
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df_structure.to_excel(writer, sheet_name='结构表', index=False)
        df_company.to_excel(writer, sheet_name='企业表', index=False)

    print(f"导出完成：")
    print(f"  结构表: {len(df_structure)} 条记录")
    print(f"  企业表: {len(df_company)} 条记录")
    print(f"  文件路径: {output_file}")


def main():
    print("\n" + "=" * 60)
    print("产业链上线表输出处理流程")
    print("=" * 60)
    print(f"\n配置信息:")
    print(f"  Excel输入: {EXCEL_INPUT}")
    print(f"  上传表: {UPLOAD_TABLE}")
    print(f"  节点信息表: {CHAIN_TABLE}")
    print(f"  产业链名称: {INDUSTRY_NAME}")
    print(f"  输出结构表: {OUTPUT_STRUCTURE_TABLE}")
    print(f"  输出企业表: {OUTPUT_COMPANY_TABLE}")

    # 执行各步骤
    df = step1_upload_excel_to_mysql()
    df = step2_add_parent_columns(df)

    # 将更新后的数据写回MySQL
    conn = pymysql.connect(**db_config)
    engine = create_engine(f"mysql+pymysql://{db_config['user']}:{db_config['password']}@"
                           f"{db_config['host']}:3306/{db_config['database']}")
    df.to_sql(UPLOAD_TABLE, engine, index=False, if_exists='replace')
    conn.close()
    print(f"更新后的数据已写回 {UPLOAD_TABLE}")

    step3_update_parent_relationships()
    step4_output_structure_table()
    step5_output_company_table()
    step6_export_to_excel()

    print("\n" + "=" * 60)
    print("所有步骤执行完成！")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
