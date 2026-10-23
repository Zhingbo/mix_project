"""
白名单上传处理脚本
功能：解析Excel文件并导入到whitelist_company表
- 变更检测在"上传时"进行：直接对比 whitelist_company 真实表（累加 + 去重）
- 上传的企业名称若是短名，自动到底表补全为全称，保证白名单里都是全称
"""
import pandas as pd
import pymysql
from datetime import datetime
import os
import logging

logger = logging.getLogger(__name__)

# 数据库配置
DB_CONFIG = {
    'host': '8.141.5.67',
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'charset': 'utf8mb4'
}

# 名称补全用的企业底表（全称来源）
BASE_TABLE = 'ent_industry_class_chain_scope_20260928_converted'

# 判定"已是全称"的企业名后缀/标记
FULL_NAME_MARKERS = [
    '有限公司', '股份有限公司', '有限责任公司', '集团', '厂', '院', '所', '中心',
    '学校', '医院', '银行', '合作社', '事务所', '工作室', '研究院', '诊所', '门诊部'
]

# 识别"子公司/分支"的提示词（出现在全称里，说明不是头部母公司）
SUBSIDIARY_HINTS = ['分公司', '办事处', '子公司', '门市', '连锁', '营销', '销售', '贸易',
                    '投资', '产业', '管理', '咨询', '服务', '发展', '物流', '仓储', '配送',
                    '大药房', '药品经营', '加盟', '分店']

# 允许的position值
VALID_POSITIONS = ['上游', '中游', '下游']


def get_db_connection():
    """获取数据库连接"""
    return pymysql.connect(**DB_CONFIG)


def _is_full_name(name: str) -> bool:
    """判断名称是否已经是全称（含企业法定后缀）"""
    return any(m in name for m in FULL_NAME_MARKERS)


def validate_excel_file(file_path):
    """
    验证Excel文件格式
    """
    try:
        df = pd.read_excel(file_path)
        if df.empty:
            return False, "Excel文件为空", None
        required_columns = ['industry_name', 'position', 'company_name']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return False, f"缺少必需的列: {', '.join(missing_columns)}", None
        invalid_positions = df[~df['position'].isin(VALID_POSITIONS)]['position'].unique()
        if len(invalid_positions) > 0:
            return False, f"position值无效，允许的值: {', '.join(VALID_POSITIONS)}。发现无效值: {', '.join(map(str, invalid_positions))}", None
        return True, "", df
    except Exception as e:
        return False, f"读取Excel文件失败: {str(e)}", None


def _pick_head(short: str, candidates: list):
    """从多个前缀候选里挑"头部母公司"。返回候选列表（唯一=可补全）。"""
    if not candidates:
        return []
    # 1) 先排除明显子公司/分支（全称的"剩余部分"含子公司提示词）
    tail = [c for c in candidates if not any(h in c[len(short):] for h in SUBSIDIARY_HINTS)]
    pool = tail if tail else candidates
    # 2) 优先"集团"（通常是母公司/集团总部）
    groups = [c for c in pool if '集团' in c]
    if groups:
        pool = groups
    # 3) 取最短
    if not pool:
        return []
    minlen = min(len(c) for c in pool)
    return [c for c in pool if len(c) == minlen]


def _complete_name(cursor, company_name: str):
    """把短名补全为底表里的全称。返回 (最终名称, 状态)
    状态: full=本就是全称 / exact=精确命中 / completed=前缀补全 / not_found=未找到 / ambiguous=多个候选
    """
    if _is_full_name(company_name):
        return company_name, 'full'

    # 精确匹配
    cursor.execute(f"SELECT company_name FROM {BASE_TABLE} WHERE company_name = %s LIMIT 2", (company_name,))
    exact = [r[0] for r in cursor.fetchall()]
    if len(exact) == 1:
        return exact[0], 'exact'
    if len(exact) > 1:
        return company_name, 'ambiguous'

    # 前缀匹配（短名通常是全称去掉"有限公司/集团…"后缀）
    cursor.execute(f"SELECT company_name FROM {BASE_TABLE} WHERE company_name LIKE %s LIMIT 51", (company_name + '%',))
    prefix = [r[0] for r in cursor.fetchall()]
    if len(prefix) == 1:
        return prefix[0], 'completed'
    if len(prefix) > 1:
        head = _pick_head(company_name, prefix)
        if len(head) == 1:
            return head[0], 'completed'
        return company_name, 'ambiguous'
    return company_name, 'not_found'


def import_whitelist(file_path, user_id=None):
    """
    导入白名单数据到数据库（含名称补全 + 累加去重）
    """
    is_valid, error_msg, df = validate_excel_file(file_path)
    if not is_valid:
        return {'success': False, 'message': error_msg, 'stats': {}}

    total_rows = len(df)
    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    error_rows = []
    completion_stats = {'full': 0, 'exact': 0, 'completed': 0, 'not_found': 0, 'ambiguous': 0}
    # 名称补全明细（短名→全称），供前端展示
    name_changes = []

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 获取已存在的记录 (industry_name, company_name)
        cursor.execute("SELECT industry_name, company_name, position FROM whitelist_company")
        existing_records = {}
        for row in cursor.fetchall():
            existing_records[(row[0], row[1])] = row[2]

        for idx, row in df.iterrows():
            try:
                industry_name = str(row['industry_name']).strip()
                position = str(row['position']).strip()
                company_name = str(row['company_name']).strip()

                if not industry_name or not position or not company_name:
                    skipped_count += 1
                    error_rows.append({'row': idx + 2, 'reason': '必填字段为空'})
                    continue

                # 名称补全
                completed_name, cstat = _complete_name(cursor, company_name)
                completion_stats[cstat] += 1
                if completed_name != company_name:
                    name_changes.append({'original': company_name, 'final': completed_name, 'status': cstat})

                key = (industry_name, completed_name)

                if key in existing_records:
                    existing_position = existing_records[key]
                    if existing_position != position:
                        cursor.execute(
                            "UPDATE whitelist_company SET position = %s, updated_at = NOW() "
                            "WHERE industry_name = %s AND company_name = %s",
                            (position, industry_name, completed_name)
                        )
                        updated_count += 1
                        existing_records[key] = position
                    else:
                        skipped_count += 1
                else:
                    cursor.execute(
                        "INSERT INTO whitelist_company (industry_name, position, company_name) VALUES (%s, %s, %s)",
                        (industry_name, position, completed_name)
                    )
                    inserted_count += 1
                    existing_records[key] = position

            except Exception as e:
                skipped_count += 1
                error_rows.append({'row': idx + 2, 'reason': str(e)})

        conn.commit()

        return {
            'success': True,
            'message': '导入完成',
            'stats': {
                'total': total_rows,
                'inserted': inserted_count,
                'updated': updated_count,
                'skipped': skipped_count,
                'name_completion': completion_stats,
                'name_changes': name_changes[:50],
                'errors': error_rows[:10]
            }
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {'success': False, 'message': f"导入失败: {str(e)}", 'stats': {}}
    finally:
        if conn:
            conn.close()


def get_whitelist_list(industry_name=None):
    """获取白名单列表"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        if industry_name:
            cursor.execute(
                "SELECT id, industry_name, position, company_name, created_at, updated_at "
                "FROM whitelist_company WHERE industry_name = %s ORDER BY position, id",
                (industry_name,))
        else:
            cursor.execute(
                "SELECT id, industry_name, position, company_name, created_at, updated_at "
                "FROM whitelist_company ORDER BY industry_name, position, id")
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"获取白名单列表失败: {e}")
        return []
    finally:
        if conn:
            conn.close()


def delete_whitelist_by_industry(industry_name):
    """删除指定产业链的白名单"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM whitelist_company WHERE industry_name = %s", (industry_name,))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"删除白名单失败: {e}")
        return 0
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    test_file = "/root/mix_project/database/企业名录模版.xlsx"
    result = import_whitelist(test_file)
    print(result)