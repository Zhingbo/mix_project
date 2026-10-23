"""
变更检测模块

检测产业链图谱和白名单的变更，返回需要重跑的步骤
"""

import os
import pymysql
import hashlib
from typing import Dict, List, Set, Tuple
from datetime import datetime
from utils.logger import get_logger

logger = get_logger(__name__)


class ChangeDetector:
    """变更检测器"""

    DB_CONFIG = {
        'host': os.getenv('DB_HOST', '8.141.5.67'),
        'user': os.getenv('DB_USER', 'root'),
        'password': os.getenv('DB_PASSWORD'),
    }

    def __init__(self, industry_name: str):
        self.industry_name = industry_name

    def detect_all_changes(self) -> Dict:
        """
        检测所有变更

        Returns:
            {
                'has_changes': bool,
                'whitelist_changed': bool,
                'graph_changed': bool,
                'added_nodes': List[str],
                'removed_nodes': List[str],
                'modified_nodes': List[str],
                'added_companies': List[str],
                'removed_companies': List[str],
                'steps_to_rerun': List[float],
                'change_summary': str
            }
        """
        result = {
            'has_changes': False,
            'whitelist_changed': False,
            'graph_changed': False,
            'whitelist_snapshot_missing': False,
            'graph_snapshot_missing': False,
            'added_nodes': [],
            'removed_nodes': [],
            'modified_nodes': [],
            'added_companies': [],
            'removed_companies': [],
            'steps_to_rerun': [],
            'change_summary': '无变更'
        }

        try:
            # 1. 检测白名单变更
            whitelist_changes = self._detect_whitelist_changes()
            result.update(whitelist_changes)
            logger.info(f"白名单变更检测: {whitelist_changes}")

            # 2. 检测图谱变更
            graph_changes = self._detect_graph_changes()
            result.update(graph_changes)
            logger.info(f"图谱变更检测: {graph_changes}")

            # 3. 计算需要重跑的步骤
            result['steps_to_rerun'] = self._calculate_steps_to_rerun(result)

            # 4. 生成变更摘要
            result['change_summary'] = self._generate_summary(result)
            result['has_changes'] = len(result['steps_to_rerun']) > 0

        except Exception as e:
            logger.error(f"变更检测失败: {e}")
            # 发生错误时，默认执行全量
            result['has_changes'] = True
            result['steps_to_rerun'] = [2, 3, 4, 5, 6, 7, 8, 9, 10]
            result['change_summary'] = f"变更检测失败，将执行全量更新: {str(e)}"

        return result

    def _detect_whitelist_changes(self) -> Dict:
        """检测白名单变更"""
        result = {
            'whitelist_changed': False,
            'whitelist_snapshot_missing': False,
            'added_companies': [],
            'removed_companies': []
        }

        try:
            conn = pymysql.connect(
                database='business_data',
                **self.DB_CONFIG
            )
            cursor = conn.cursor()

            # 获取当前白名单企业
            cursor.execute("""
                SELECT company_name, position
                FROM whitelist_company
                WHERE industry_name = %s
            """, (self.industry_name,))
            current_whitelist = set(cursor.fetchall())

            # 获取快照中的白名单
            cursor.execute("""
                SELECT company_name, position
                FROM whitelist_snapshot
                WHERE industry_name = %s
            """, (self.industry_name,))
            snapshot_whitelist = set(cursor.fetchall())

            # 检查快照是否为空（首次使用增量功能）
            if len(snapshot_whitelist) == 0:
                cursor.close()
                conn.close()
                logger.info("白名单快照为空，标记为缺少基线")
                result['whitelist_snapshot_missing'] = True
                return result

            cursor.close()
            conn.close()

            # 比较差异
            added = current_whitelist - snapshot_whitelist
            removed = snapshot_whitelist - current_whitelist

            result['added_companies'] = [c[0] for c in added]
            result['removed_companies'] = [c[0] for c in removed]
            result['whitelist_changed'] = len(added) > 0 or len(removed) > 0

        except Exception as e:
            logger.error(f"白名单变更检测失败: {e}")

        return result

    def _detect_graph_changes(self) -> Dict:
        """检测图谱变更"""
        result = {
            'graph_changed': False,
            'graph_snapshot_missing': False,
            'added_nodes': [],
            'removed_nodes': [],
            'modified_nodes': []
        }

        try:
            conn = pymysql.connect(
                database='business_data',
                **self.DB_CONFIG
            )
            cursor = conn.cursor()

            # 获取当前图谱节点（从 chain_needcomp）
            cursor.execute("""
                SELECT nodes, nodes_definition
                FROM chain_needcomp
                WHERE chain_name = %s
            """, (self.industry_name,))
            current_nodes = {}
            for row in cursor.fetchall():
                node_name, definition = row
                current_nodes[node_name] = definition or ''

            # 获取快照中的节点
            cursor.execute("""
                SELECT node_name, node_definition, node_hash
                FROM graph_node_snapshot
                WHERE industry_name = %s
            """, (self.industry_name,))
            snapshot_nodes = {}
            for row in cursor.fetchall():
                node_name, definition, node_hash = row
                snapshot_nodes[node_name] = {
                    'definition': definition or '',
                    'hash': node_hash
                }

            cursor.close()
            conn.close()

            # 检查快照是否为空（首次使用增量功能）
            if len(snapshot_nodes) == 0:
                logger.info(f"图谱快照为空，标记为缺少基线，当前节点数: {len(current_nodes)}")
                result['graph_snapshot_missing'] = True
                return result

            # 比较节点列表
            current_node_set = set(current_nodes.keys())
            snapshot_node_set = set(snapshot_nodes.keys())

            added = current_node_set - snapshot_node_set
            removed = snapshot_node_set - current_node_set
            common = current_node_set & snapshot_node_set

            # 检查修改的节点（定义内容变化）
            modified = []
            for node in common:
                current_hash = hashlib.md5(current_nodes[node].encode('utf-8')).hexdigest()
                snapshot_hash = snapshot_nodes[node]['hash']
                if current_hash != snapshot_hash:
                    modified.append(node)
                    logger.info(f"检测到节点定义变更: {node}")

            result['added_nodes'] = list(added)
            result['removed_nodes'] = list(removed)
            result['modified_nodes'] = modified

            # 判断是否有变更
            result['graph_changed'] = len(added) > 0 or len(removed) > 0 or len(modified) > 0

            if result['graph_changed']:
                logger.info(f"检测到图谱变更: added={len(added)}, removed={len(removed)}, modified={len(modified)}")

        except Exception as e:
            logger.error(f"图谱变更检测失败: {e}")

        return result

    def _calculate_steps_to_rerun(self, changes: Dict) -> List[float]:
        """根据变更计算需要重跑的步骤"""
        steps = []

        if changes.get('whitelist_changed'):
            # 白名单变更影响步骤5-10
            steps.extend([5, 6, 7, 8, 9, 10])
            logger.info("白��单变更，将重跑步骤5-10")

        if changes.get('graph_changed'):
            added = changes.get('added_nodes', [])
            removed = changes.get('removed_nodes', [])
            modified = changes.get('modified_nodes', [])

            if modified and not added and not removed:
                # 只有节点定义变更，只需要重跑步骤6-10（但步骤需要��新补全名称）
                steps.extend([6, 7, 8, 9, 10])
                logger.info("节点定义变更，将重跑步骤6-10")
            else:
                # 有节点增删，需要重跑步骤2-10
                steps.extend([2, 3, 4, 6, 7, 8, 9, 10])
                logger.info("节点增删变更，将重跑步骤2-10（跳过步骤5）")

        return sorted(set(steps))

    def _generate_summary(self, changes: Dict) -> str:
        """生成变更摘要"""
        parts = []

        if changes.get('whitelist_changed'):
            added = changes.get('added_companies', [])
            removed = changes.get('removed_companies', [])
            if added:
                parts.append(f"新增白名单企业{len(added)}家")
            if removed:
                parts.append(f"删除白名单企业{len(removed)}家")

        if changes.get('graph_changed'):
            added = changes.get('added_nodes', [])
            removed = changes.get('removed_nodes', [])
            modified = changes.get('modified_nodes', [])
            if added:
                parts.append(f"新增节点{len(added)}个")
            if removed:
                parts.append(f"删除节点{len(removed)}个")
            if modified:
                parts.append(f"修改节点{len(modified)}个")

        if not parts:
            missing = []
            if changes.get('whitelist_snapshot_missing'):
                missing.append("白名单快照缺失")
            if changes.get('graph_snapshot_missing'):
                missing.append("图谱快照缺失")
            if missing:
                return "、".join(missing)
            return "无变更"

        return "、".join(parts)


def update_whitelist_snapshot(industry_name: str) -> int:
    """
    更新白名单快照

    Args:
        industry_name: 产业链名称

    Returns:
        更新的记录数
    """
    conn = pymysql.connect(
        host=os.getenv('DB_HOST', '8.141.5.67'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME', 'business_data')
    )
    cursor = conn.cursor()

    try:
        # 先删除旧快照
        cursor.execute(
            "DELETE FROM whitelist_snapshot WHERE industry_name = %s",
            (industry_name,)
        )

        # 插入新快照
        insert_sql = """
        INSERT INTO whitelist_snapshot (industry_name, company_name, position)
        SELECT industry_name, company_name, position
        FROM whitelist_company
        WHERE industry_name = %s
        """
        cursor.execute(insert_sql, (industry_name,))
        conn.commit()

        count = cursor.rowcount
        logger.info(f"更新产业链 {industry_name} 的白名单快照，{count} 条记录")
        return count

    except Exception as e:
        logger.error(f"更新白名单快照失败: {e}")
        conn.rollback()
        return 0

    finally:
        cursor.close()
        conn.close()


def update_graph_snapshot(industry_name: str) -> int:
    """
    更新图谱节点快照

    Args:
        industry_name: 产业链名称

    Returns:
        更新的记录数
    """
    conn = pymysql.connect(
        host=os.getenv('DB_HOST', '8.141.5.67'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME', 'business_data')
    )
    cursor = conn.cursor()

    try:
        # 先删除旧快照
        cursor.execute(
            "DELETE FROM graph_node_snapshot WHERE industry_name = %s",
            (industry_name,)
        )

        # 插入新快照
        insert_sql = """
        INSERT INTO graph_node_snapshot (industry_name, node_name, node_definition, node_hash)
        SELECT chain_name, nodes,
               COALESCE(nodes_definition, ''),
               MD5(COALESCE(nodes_definition, ''))
        FROM chain_needcomp
        WHERE chain_name = %s
        """
        cursor.execute(insert_sql, (industry_name,))
        conn.commit()

        count = cursor.rowcount
        logger.info(f"更新产业链 {industry_name} 的图谱节点快照，{count} 条记录")
        return count

    except Exception as e:
        logger.error(f"更新图谱节点快照失败: {e}")
        conn.rollback()
        return 0

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    # 测试变更检测
    detector = ChangeDetector("测试产业")
    changes = detector.detect_all_changes()
    print(f"变更检测结果: {changes}")
