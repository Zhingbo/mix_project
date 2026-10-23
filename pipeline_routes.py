"""
产业链自动化处理路由

功能：执行步骤2-10的自动化流程，使用SSE推送进度
"""

from fastapi import APIRouter, Request, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
import asyncio
import json
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth_routes import get_current_user
from utils.logger import get_logger
from steps.cancel_token import cancel_task, clear_cancel_task, is_cancelled as is_step_cancelled

logger = get_logger(__name__)

# 检查 Celery 是否可用
CELERY_AVAILABLE = False  # 暂时禁用 Celery，使用同步执行
run_pipeline_task = None
cancel_pipeline_task = None
try:
    from tasks.pipeline_tasks import run_pipeline_task, cancel_pipeline_task
    # CELERY_AVAILABLE = True  # 暂时禁用
    logger.info("Celery 可用，但当前使用同步执行模式")
except ImportError as e:
    logger.warning(f"Celery 不可用: {e}，将使用同步执行模式")

# 创建路由
pipeline_router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# 全局任务跟踪
running_tasks = {}  # {industry_name: {"task": asyncio.Task, "cancelled": bool, "status": dict, "messages": []}}
# 任务状态存储：每个任务的状态、进度、消息
task_status = {}  # {industry_name: {"status": "running"/"completed"/"error"/"cancelled", "current_step": int, "progress": int, "messages": []}}
# 暂停任务存储（Redis不可用时的备选方案）
paused_tasks = {}  # {industry_name: bool}

# 步骤配置
STEPS = [
    {'step': 2, 'name': '生成节点定义', 'function': 'step2_generate_definition'},
    {'step': 3, 'name': '节点匹配行业', 'function': 'step3_match_industryry'},
    {'step': 4, 'name': '公司匹配节点', 'function': 'step4_company_match_nodes'},
    {'step': 5, 'name': '搜索头部企业', 'function': 'step5_search_top_companies', 'need_whitelist': True},
    {'step': 6, 'name': '头部企业匹配节点', 'function': 'step6_top_company_match'},
    {'step': 7, 'name': '拆分结果', 'function': 'step7_split_results'},
    {'step': 8, 'name': '合并去重清理', 'function': 'step8_merge_and_clean'},
    {'step': 9, 'name': '输出最终名单', 'function': 'step9_export_finallist'},
    {'step': 10, 'name': '输出上线表', 'function': 'step10_export_online_tables'},
]

# 表名配置（统一使用不带前缀的表名，因为连接已指定business_data数据库）
TABLES = {
    'source_chain': 'industrial_chain.industrial_chain_structure',
    'whitelist_company': 'whitelist_company',
    'chain_needcomp': 'chain_needcomp',
    'company_nodes_mapping': 'company_nodes_mapping',
    'company_nodes_info_result': 'company_nodes_info_result',
    'company_nodes_info_split': 'company_nodes_info_split',
    'company_nodes_top': 'company_nodes_top',
    'company_nodes_final': 'company_nodes_final',
    'company_nodes_finallist': 'company_nodes_finallist',
    'industry_structure_output': 'industry_structure_output',
    'company_list_output': 'company_list_output',
    'mapping_industry_info_new': 'mapping_industry_info_new',
    'ent_industry_class_old': 'ent_industry_class_chain_scope_20260928_converted',
    'nodes_industry_mapping': 'nodes_industry_mapping',
    'company_nodes_mapping_temp': 'company_nodes_mapping_temp',
}


def _normalize_node_text(value):
    if value is None:
        return None
    return str(value).strip()


def _normalize_node_level(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _node_signature(parent_node, node_level):
    return (_normalize_node_text(parent_node), _normalize_node_level(node_level))


def _fetch_active_structure_nodes(cursor, industry_name: str):
    cursor.execute(
        """
        SELECT nodes, parent_node, node_level
        FROM industrial_chain.industrial_chain_structure
        WHERE chain_name = %s
          AND (status = 1 OR status IS NULL)
        ORDER BY node_level, id
        """,
        (industry_name,)
    )
    return cursor.fetchall()


def _sync_chain_needcomp_nodes(cursor, industry_name: str, node_data) -> dict:
    cursor.execute(
        """
        SELECT nodes, parent_node, node_level, nodes_definition
        FROM chain_needcomp
        WHERE chain_name = %s
        """,
        (industry_name,)
    )
    existing_rows = cursor.fetchall()

    existing_definitions = {}
    existing_signatures = set()
    for nodes, parent_node, node_level, nodes_definition in existing_rows:
        node_name = _normalize_node_text(nodes)
        if not node_name:
            continue
        signature = _node_signature(parent_node, node_level)
        existing_signatures.add((node_name, signature[0], signature[1]))
        if node_name not in existing_definitions or not existing_definitions[node_name]:
            existing_definitions[node_name] = nodes_definition

    new_signatures = set()
    ordered_nodes = []
    for nodes, parent_node, node_level in node_data:
        node_name = _normalize_node_text(nodes)
        if not node_name:
            continue
        signature = _node_signature(parent_node, node_level)
        new_signatures.add((node_name, signature[0], signature[1]))
        ordered_nodes.append((node_name, parent_node, node_level))

    existing_nodes = {row[0] for row in existing_signatures}
    new_nodes = {row[0] for row in new_signatures}
    added_nodes = sorted(new_nodes - existing_nodes)
    removed_nodes = sorted(existing_nodes - new_nodes)
    changed_row_nodes = {row[0] for row in (existing_signatures ^ new_signatures)}
    changed_nodes = sorted(changed_row_nodes - set(added_nodes) - set(removed_nodes))

    cursor.execute(
        "DELETE FROM chain_needcomp WHERE chain_name = %s",
        (industry_name,)
    )

    insert_count = 0
    for node_name, parent_node, node_level in ordered_nodes:
        nodes_definition = existing_definitions.get(node_name)
        cursor.execute(
            """
            INSERT INTO chain_needcomp
                (chain_name, nodes, parent_node, node_level, nodes_definition)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (industry_name, node_name, parent_node, node_level, nodes_definition)
        )
        insert_count += 1

    return {
        "insert_count": insert_count,
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "changed_nodes": changed_nodes,
        "structure_changed": existing_signatures != new_signatures,
    }


def _clear_pipeline_outputs_after_structure_change(cursor, industry_name: str) -> dict:
    cleanup_targets = [
        ("nodes_industry_mapping", "industry_name"),
        ("company_nodes_mapping", "industry_name"),
        ("company_nodes_top", "industry_chain"),
        ("company_nodes_info_result", "industry_name"),
        ("company_nodes_info_split", "industry_name"),
        ("company_nodes_final", "industry_name"),
        ("company_nodes_finallist", "industry_name"),
        ("company_nodes_merge_temp", "industry_name"),
        ("industry_structure_output", "industry_name"),
        ("company_list_output", "industry_name"),
    ]

    deleted = {}
    for table_name, column_name in cleanup_targets:
        try:
            cursor.execute(
                f"DELETE FROM {table_name} WHERE {column_name} = %s",
                (industry_name,)
            )
            deleted[table_name] = cursor.rowcount
        except Exception as exc:
            logger.warning(f"清理结构变更下游表 {table_name} 失败: {exc}")
            deleted[table_name] = None

    return deleted


def _sync_chain_nodes_and_cleanup(cursor, industry_name: str, node_data) -> dict:
    sync_result = _sync_chain_needcomp_nodes(cursor, industry_name, node_data)

    if sync_result["structure_changed"]:
        cleanup_result = _clear_pipeline_outputs_after_structure_change(cursor, industry_name)
        sync_result["cleanup"] = cleanup_result
        logger.info(
            "产业链节点结构变化，已清理下游结果: "
            f"industry={industry_name}, added={sync_result['added_nodes']}, "
            f"removed={sync_result['removed_nodes']}, changed={sync_result['changed_nodes']}, "
            f"cleanup={cleanup_result}"
        )
    else:
        sync_result["cleanup"] = {}

    return sync_result


def _check_step2_definition_completed(cursor, industry_name: str) -> bool:
    """步骤2完成需要节点定义已生成，不能只判断同步表有行。"""
    cursor.execute("""
        SELECT
            COUNT(*) AS total_count,
            SUM(CASE
                WHEN nodes_definition IS NOT NULL AND TRIM(nodes_definition) <> ''
                THEN 1 ELSE 0
            END) AS defined_count
        FROM chain_needcomp
        WHERE chain_name = %s
    """, (industry_name,))
    total_count, defined_count = cursor.fetchone()
    total_count = total_count or 0
    defined_count = defined_count or 0
    return total_count > 0 and defined_count >= total_count


def _get_task_status_record(industry_name: str):
    """读取任务状态记录，用于跨 worker 判断运行/取消状态。"""
    import pymysql

    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data',
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT status, current_step, current_step_name, progress, error_message, updated_at
            FROM pipeline_task_status
            WHERE industry_name = %s
            ORDER BY id DESC LIMIT 1
        """, (industry_name,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "status": row[0],
            "current_step": row[1],
            "current_step_name": row[2],
            "progress": row[3],
            "error_message": row[4],
            "updated_at": row[5],
        }
    finally:
        cursor.close()
        conn.close()


def _step_name(step_num):
    try:
        step_value = float(step_num)
    except (TypeError, ValueError):
        return ""
    for step in STEPS:
        if float(step['step']) == step_value:
            return step['name']
    return ""


def _task_update_age_seconds(updated_at):
    if not updated_at:
        return None
    try:
        from datetime import datetime, timezone

        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        now = datetime.now(updated_at.tzinfo or timezone.utc)
        if updated_at.tzinfo is None:
            now = datetime.now()
        return max(0, int((now - updated_at).total_seconds()))
    except Exception:
        return None


def _is_recent_task_update(updated_at, ttl_seconds: int = 120) -> bool:
    age_seconds = _task_update_age_seconds(updated_at)
    return age_seconds is not None and age_seconds <= ttl_seconds


def _normalize_pipeline_task_status(industry_name: str, step_status=None):
    """Return authoritative task status and clear stale DB running state."""
    import pymysql

    status = step_status if step_status is not None else check_step_status(industry_name)
    completed_steps = sum(1 for done in status.values() if done)
    total_steps = len(STEPS)
    has_local_task = industry_name in running_tasks and not running_tasks[industry_name].get("cancelled", False)
    task_record = _get_task_status_record(industry_name) or {}
    db_status = task_record.get("status") or "idle"
    has_recent_heartbeat = db_status == "running" and _is_recent_task_update(task_record.get("updated_at"))
    is_running = has_local_task or has_recent_heartbeat
    task_status_value = db_status

    if is_running:
        task_status_value = "running"
    elif db_status == "running":
        task_status_value = "completed" if completed_steps >= total_steps else "idle"
        try:
            conn = pymysql.connect(
                host='8.141.5.67',
                user='root',
                password=os.getenv('DB_PASSWORD'),
                database='business_data',
                charset='utf8mb4'
            )
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE pipeline_task_status
                SET status = %s,
                    progress = CASE WHEN %s = 'completed' THEN 100 ELSE progress END,
                    completed_at = CASE WHEN %s = 'completed' THEN NOW() ELSE completed_at END,
                    updated_at = NOW()
                WHERE industry_name = %s AND status = 'running'
            """, (task_status_value, task_status_value, task_status_value, industry_name))
            conn.commit()
            cursor.close()
            conn.close()
            logger.warning(
                f"已修正产业链 {industry_name} 残留 running 状态为 {task_status_value}"
            )
        except Exception as exc:
            logger.error(f"修正残留任务状态失败: {exc}")
    elif db_status in {"completed", "cancelled", "error", "paused"}:
        task_status_value = db_status
    elif completed_steps >= total_steps:
        task_status_value = "completed"
    else:
        task_status_value = "idle"

    current_step = task_record.get("current_step")
    if task_status_value != "running":
        next_step = next((step['step'] for step in STEPS if not status.get(step['step'], False)), None)
        current_step = next_step or 10

    current_step_name = task_record.get("current_step_name") if task_status_value == "running" else None
    if not current_step_name:
        current_step_name = _step_name(current_step)

    return {
        "status": task_status_value,
        "is_running": is_running and task_status_value == "running",
        "current_step": current_step,
        "current_step_name": current_step_name,
        "progress": task_record.get("progress") or (100 if task_status_value == "completed" else 0),
        "error_message": task_record.get("error_message"),
        "updated_at": task_record.get("updated_at"),
        "heartbeat_age_seconds": _task_update_age_seconds(task_record.get("updated_at")),
        "completed_steps": completed_steps,
        "total_steps": total_steps,
    }


def _write_pipeline_task_status(
    industry_name: str,
    status: str = None,
    current_step=None,
    current_step_name: str = None,
    progress: int = None,
    error_message: str = None,
    completed: bool = False,
    cancelled: bool = False,
):
    import pymysql

    columns = ["industry_name", "updated_at"]
    placeholders = ["%s", "NOW()"]
    params = [industry_name]
    updates = ["updated_at = NOW()"]

    def add_value(column, value):
        columns.append(column)
        placeholders.append("%s")
        params.append(value)
        updates.append(f"{column} = VALUES({column})")

    if status is not None:
        add_value("status", status)
    if current_step is not None:
        add_value("current_step", current_step)
    if current_step_name is not None:
        add_value("current_step_name", current_step_name)
    if progress is not None:
        add_value("progress", progress)
    if error_message is not None:
        add_value("error_message", error_message[:500])
    if completed:
        columns.append("completed_at")
        placeholders.append("NOW()")
        updates.append("completed_at = NOW()")
    if cancelled:
        columns.append("cancelled_at")
        placeholders.append("NOW()")
        updates.append("cancelled_at = NOW()")

    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data',
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            INSERT INTO pipeline_task_status
            ({", ".join(columns)})
            VALUES ({", ".join(placeholders)})
            ON DUPLICATE KEY UPDATE {", ".join(updates)}
        """, params)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def _ensure_pipeline_task_logs_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_task_logs (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            industry_name VARCHAR(255) NOT NULL,
            level VARCHAR(20) NOT NULL DEFAULT 'info',
            step VARCHAR(20) NULL,
            step_name VARCHAR(100) NULL,
            message TEXT NOT NULL,
            detail_json LONGTEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_pipeline_task_logs_industry_id (industry_name, id),
            INDEX idx_pipeline_task_logs_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def _extract_log_payload(message_type: str, content):
    level_map = {
        "error": "error",
        "warning": "warning",
        "cancelled": "warning",
        "paused": "warning",
        "completed": "success",
        "step_completed": "success",
        "step_skipped": "info",
        "batch_progress": "progress",
        "progress": "progress",
        "start": "info",
        "info": "info",
    }
    level = level_map.get(message_type, "info")
    step = None
    step_name = None

    if isinstance(content, dict):
        step = content.get("step")
        step_name = content.get("step_name")
        message = content.get("message")
        if not message:
            if message_type == "batch_progress" and content.get("total"):
                current = content.get("current", 0)
                total = content.get("total")
                company_name = content.get("company_name") or ""
                message = f"{step_name or '步骤进度'}: {current}/{total} {company_name}".strip()
            else:
                message = json.dumps(content, ensure_ascii=False, default=str)
        detail = content
    else:
        message = str(content)
        detail = {"content": content}

    return {
        "level": level,
        "step": "" if step is None else str(step),
        "step_name": step_name or "",
        "message": message,
        "detail": detail,
    }


def _calculate_pipeline_progress(step, current=None, total=None):
    try:
        step_value = float(step)
    except (TypeError, ValueError):
        return None

    step_index = next((idx for idx, item in enumerate(STEPS, start=1) if float(item["step"]) == step_value), None)
    if step_index is None:
        return None

    base = ((step_index - 1) / len(STEPS)) * 100
    if current is None or total in (None, 0):
        return round(base)
    try:
        ratio = max(0, min(float(current) / float(total), 1))
    except (TypeError, ValueError, ZeroDivisionError):
        return round(base)
    return round(base + ratio * (100 / len(STEPS)))


def _record_pipeline_activity(industry_name: str, message_type: str, content):
    import pymysql

    payload = _extract_log_payload(message_type, content)
    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data',
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    try:
        _ensure_pipeline_task_logs_table(cursor)
        cursor.execute("""
            INSERT INTO pipeline_task_logs
            (industry_name, level, step, step_name, message, detail_json)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            industry_name,
            payload["level"],
            payload["step"],
            payload["step_name"],
            payload["message"],
            json.dumps(payload["detail"], ensure_ascii=False, default=str),
        ))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    if message_type in {"progress", "batch_progress"} and isinstance(content, dict):
        step = content.get("step")
        step_name = content.get("step_name")
        progress = _calculate_pipeline_progress(step, content.get("current"), content.get("total"))
        status_step_name = step_name
        if message_type == "batch_progress" and content.get("total"):
            status_step_name = f"{step_name or _step_name(step)} ({content.get('current', 0)}/{content.get('total')})"
        try:
            _write_pipeline_task_status(
                industry_name,
                status="running",
                current_step=step,
                current_step_name=status_step_name,
                progress=progress,
            )
        except Exception as exc:
            logger.error(f"记录任务活动状态失败: {exc}")


def _get_pipeline_task_logs(industry_name: str, limit: int = 100, after_id: int = None):
    import pymysql

    safe_limit = max(1, min(int(limit or 100), 500))
    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data',
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    try:
        _ensure_pipeline_task_logs_table(cursor)
        if after_id:
            cursor.execute("""
                SELECT id, level, step, step_name, message, detail_json, created_at
                FROM pipeline_task_logs
                WHERE industry_name = %s AND id > %s
                ORDER BY id ASC
                LIMIT %s
            """, (industry_name, after_id, safe_limit))
        else:
            cursor.execute("""
                SELECT id, level, step, step_name, message, detail_json, created_at
                FROM (
                    SELECT id, level, step, step_name, message, detail_json, created_at
                    FROM pipeline_task_logs
                    WHERE industry_name = %s
                    ORDER BY id DESC
                    LIMIT %s
                ) recent
                ORDER BY id ASC
            """, (industry_name, safe_limit))
        logs = []
        for row in cursor.fetchall():
            detail = None
            if row[5]:
                try:
                    detail = json.loads(row[5])
                except Exception:
                    detail = None
            logs.append({
                "id": row[0],
                "level": row[1],
                "step": row[2],
                "step_name": row[3],
                "message": row[4],
                "detail": detail,
                "created_at": row[6],
            })
        return logs
    finally:
        cursor.close()
        conn.close()


def _get_pipeline_task_overview(limit: int = 100):
    import pymysql

    safe_limit = max(1, min(int(limit or 100), 500))
    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data',
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT industry_name, status, current_step, current_step_name, progress,
                   error_message, started_at, updated_at, completed_at, cancelled_at
            FROM pipeline_task_status
            ORDER BY
                CASE status
                    WHEN 'running' THEN 0
                    WHEN 'paused' THEN 1
                    WHEN 'error' THEN 2
                    WHEN 'cancelled' THEN 3
                    WHEN 'completed' THEN 4
                    ELSE 5
                END,
                updated_at DESC
            LIMIT %s
        """, (safe_limit,))
        tasks = []
        seen_industries = set()
        for row in cursor.fetchall():
            industry_name = (row[0] or "").strip()
            if not industry_name or industry_name in seen_industries:
                continue
            seen_industries.add(industry_name)

            age_seconds = _task_update_age_seconds(row[7])
            is_running = row[1] == "running" and _is_recent_task_update(row[7])
            tasks.append({
                "industry_name": industry_name,
                "status": "running" if is_running else row[1],
                "is_running": is_running,
                "is_stale": row[1] == "running" and not is_running,
                "current_step": row[2],
                "current_step_name": row[3] or _step_name(row[2]),
                "progress": row[4],
                "error_message": row[5],
                "started_at": row[6],
                "updated_at": row[7],
                "heartbeat_age_seconds": age_seconds,
                "completed_at": row[8],
                "cancelled_at": row[9],
            })
        return tasks
    finally:
        cursor.close()
        conn.close()


async def _stream_task_status_events(industry_name: str):
    last_payload = None
    last_log_id = None
    while True:
        try:
            step_status = check_step_status(industry_name)
            task_state = _normalize_pipeline_task_status(industry_name, step_status)
            logs = _get_pipeline_task_logs(industry_name, limit=50 if last_log_id is None else 100, after_id=last_log_id)
            payload = {
                "industry_name": industry_name,
                "status": task_state["status"],
                "is_running": task_state["is_running"],
                "step": task_state["current_step"],
                "step_name": task_state["current_step_name"],
                "progress": task_state["progress"],
                "completed_steps": task_state["completed_steps"],
                "total_steps": task_state["total_steps"],
                "step_status": step_status,
                "latest_log": logs[-1] if logs else None,
            }
            encoded = json.dumps(payload, ensure_ascii=False, default=str)
            if encoded != last_payload:
                yield {"data": json.dumps({"type": "progress", "content": payload}, ensure_ascii=False, default=str)}
                last_payload = encoded

            for log_item in logs:
                yield {"data": json.dumps({"type": "log", "content": log_item}, ensure_ascii=False, default=str)}
                last_log_id = log_item["id"]

            if not task_state["is_running"]:
                final_type = "completed" if task_state["status"] == "completed" else task_state["status"]
                yield {"data": json.dumps({"type": final_type, "content": payload}, ensure_ascii=False, default=str)}
                break
        except Exception as exc:
            logger.error(f"监听任务状态失败: {exc}")
            yield {"data": json.dumps({"type": "error", "content": str(exc)}, ensure_ascii=False)}
            break

        await asyncio.sleep(2)


def _set_task_status_cancelled(industry_name: str):
    """写入共享取消状态，让其他 worker 和状态接口都能看到。"""
    import pymysql

    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data',
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO pipeline_task_status
            (industry_name, status, current_step, progress, cancelled_at, updated_at)
            VALUES (%s, 'cancelled', 0, 0, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
            status = 'cancelled',
            current_step = 0,
            progress = 0,
            cancelled_at = NOW(),
            updated_at = NOW()
        """, (industry_name,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def _is_cancel_requested(industry_name: str) -> bool:
    """同时检查内存令牌和数据库取消状态。"""
    if is_step_cancelled(industry_name):
        return True
    record = _get_task_status_record(industry_name)
    return bool(record and record.get("status") == "cancelled")


def _clear_cancel_status(industry_name: str):
    """新任务启动前清除上一轮取消状态。"""
    clear_cancel_task(industry_name)


def is_task_cancelled(industry_name: str) -> bool:
    """
    检查任务是否已被取消

    Args:
        industry_name: 产业链名称

    Returns:
        True 表示已取消，False 表示未取消
    """
    if industry_name in running_tasks:
        return running_tasks[industry_name].get("cancelled", False)
    return _is_cancel_requested(industry_name)


async def check_step_completed(industry_name: str, step_num: float, tables: dict) -> bool:
    """
    检查指定步骤是否已完成（目标表中是否有该产业链的数据）

    Args:
        industry_name: 产业链名称
        step_num: 步骤编号
        tables: 表名配置字典

    Returns:
        True 表示已完成，False 表示未完成
    """
    import pymysql

    db_config = {
        'host': '8.141.5.67',
        'user': 'root',
        'password': os.getenv('DB_PASSWORD'),
        'database': 'business_data'
    }

    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()

        # 根据步骤检查对应的表
        if step_num == 2:
            completed = _check_step2_definition_completed(cursor, industry_name)
            logger.info(f"步骤2检查: chain_needcomp 节点定义完成={completed}")

        elif step_num == 3:
            cursor.execute(
                f"SELECT COUNT(*) FROM nodes_industry_mapping WHERE industry_name = %s",
                (industry_name,)
            )
            count = cursor.fetchone()[0]
            completed = count > 0
            logger.info(f"步骤3检查: nodes_industry_mapping 有 {count} 条记录")

        elif step_num == 4:
            cursor.execute(
                f"SELECT COUNT(*) FROM company_nodes_mapping WHERE industry_name = %s",
                (industry_name,)
            )
            count = cursor.fetchone()[0]
            completed = count > 0
            logger.info(f"步骤4检查: company_nodes_mapping 有 {count} 条记录")

        elif step_num == 5:
            cursor.execute(
                f"SELECT COUNT(*) FROM company_nodes_top WHERE industry_chain = %s",
                (industry_name,)
            )
            count = cursor.fetchone()[0]
            completed = count > 0
            logger.info(f"步骤5检查: company_nodes_top 有 {count} 条记录")

        elif step_num == 6:
            cursor.execute(
                f"SELECT COUNT(*) FROM company_nodes_info_result WHERE industry_name = %s",
                (industry_name,)
            )
            count = cursor.fetchone()[0]
            completed = count > 0
            logger.info(f"步骤6检查: company_nodes_info_result 有 {count} 条记录")

        elif step_num == 7:
            # 步骤7检查多个表
            cursor.execute(
                f"SELECT COUNT(*) FROM company_nodes_info_split WHERE industry_name = %s",
                (industry_name,)
            )
            count = cursor.fetchone()[0]
            completed = count > 0
            logger.info(f"步骤7检查: company_nodes_info_split 有 {count} 条记录")

        elif step_num == 8:
            cursor.execute(
                f"SELECT COUNT(*) FROM company_nodes_final WHERE industry_name = %s",
                (industry_name,)
            )
            count = cursor.fetchone()[0]
            completed = count > 0
            logger.info(f"步骤8检查: company_nodes_final 有 {count} 条记录")

        elif step_num == 9:
            cursor.execute(
                f"SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name = %s",
                (industry_name,)
            )
            count = cursor.fetchone()[0]
            completed = count > 0
            logger.info(f"步骤9检查: company_nodes_finallist 有 {count} 条记录")

        elif step_num == 10:
            cursor.execute(
                f"SELECT COUNT(*) FROM company_list_output WHERE industry_name = %s",
                (industry_name,)
            )
            count = cursor.fetchone()[0]
            completed = count > 0
            logger.info(f"步骤10检查: company_list_output 有 {count} 条记录")

        else:
            completed = False

        cursor.close()
        conn.close()

        return completed

    except Exception as e:
        logger.error(f"检查步骤{step_num}完成状态失败: {e}")
        return False


def load_whitelist_data(industry_name):
    """从 MySQL 读取白名单数据"""
    import pymysql

    try:
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data'
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT industry_name, position, company_name
            FROM whitelist_company
            WHERE industry_name = %s
        """, (industry_name,))
        results = cursor.fetchall()
        cursor.close()
        conn.close()

        logger.info(f"从数据库加载了 {len(results)} 条白名单数据")
        return results
    except Exception as e:
        logger.error(f"加载白名单失败: {e}")
        return []


def check_step_status(industry_name):
    """检查每个步骤的完成状态"""
    import pymysql

    status = {}
    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data'
    )
    cursor = conn.cursor()

    # 步骤2: 检查节点定义是否已生成
    status[2] = _check_step2_definition_completed(cursor, industry_name)

    # 步骤3: 检查nodes_industry_mapping
    cursor.execute("SELECT COUNT(*) FROM nodes_industry_mapping WHERE industry_name = %s", (industry_name,))
    step3_done = cursor.fetchone()[0] > 0
    status[3] = step3_done

    # 步骤4: 检查company_nodes_mapping
    cursor.execute("SELECT COUNT(*) FROM company_nodes_mapping WHERE industry_name = %s", (industry_name,))
    step4_done = cursor.fetchone()[0] > 0
    status[4] = step4_done

    # 步骤5: 检查company_nodes_top
    cursor.execute("SELECT COUNT(*) FROM company_nodes_top WHERE industry_chain = %s", (industry_name,))
    step5_done = cursor.fetchone()[0] > 0
    status[5] = step5_done

    # 步骤6: 检查company_nodes_info_result
    cursor.execute("SELECT COUNT(*) FROM company_nodes_info_result WHERE industry_name = %s", (industry_name,))
    step6_done = cursor.fetchone()[0] > 0
    status[6] = step6_done

    # 步骤7: 检查company_nodes_info_split
    cursor.execute("SELECT COUNT(*) FROM company_nodes_info_split WHERE industry_name = %s", (industry_name,))
    step7_done = cursor.fetchone()[0] > 0
    status[7] = step7_done

    # 步骤8: 检查company_nodes_final
    try:
        cursor.execute("SELECT COUNT(*) FROM company_nodes_final WHERE industry_name = %s", (industry_name,))
        step8_done = cursor.fetchone()[0] > 0
    except:
        step8_done = False
    status[8] = step8_done

    # 步骤9: 检查company_nodes_finallist
    try:
        cursor.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name = %s", (industry_name,))
        step9_done = cursor.fetchone()[0] > 0
    except:
        step9_done = False
    status[9] = step9_done

    # 步骤10: 检查company_list_output
    try:
        cursor.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name = %s", (industry_name,))
        step10_done = cursor.fetchone()[0] > 0
    except:
        step10_done = False
    status[10] = step10_done

    cursor.close()
    conn.close()

    return status


def get_incomplete_steps(industry_name):
    """返回当前产业链缺失或不完整的步骤。"""
    status = check_step_status(industry_name)
    return [step_num for step_num in range(2, 11) if not status.get(step_num, False)]


@pipeline_router.get("/industries")
async def get_industries(current_user: dict = Depends(get_current_user)):
    """获取所有可用的产业链列表"""
    import pymysql

    try:
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            charset='utf8mb4'
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT chain_name
            FROM industrial_chain.industrial_chain_structure
            WHERE status = 1 OR status IS NULL
            ORDER BY chain_name
        """)
        industries = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()

        return {
            "status": "success",
            "data": industries
        }
    except Exception as e:
        logger.error(f"获取产业链列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pipeline_router.get("/industry/{industry_name}/info")
async def get_industry_info(industry_name: str, current_user: dict = Depends(get_current_user)):
    """获取产业链信息"""
    import pymysql

    try:
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            charset='utf8mb4'
        )
        cursor = conn.cursor()

        # 检查产业链是否存在
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM industrial_chain.industrial_chain_structure
            WHERE chain_name = %s
              AND (status = 1 OR status IS NULL)
            """,
            (industry_name,)
        )
        count = cursor.fetchone()[0]

        if count == 0:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=404, detail=f"产业链 '{industry_name}' 不存在")

        # 获取节点数量
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM industrial_chain.industrial_chain_structure
            WHERE chain_name = %s
              AND (status = 1 OR status IS NULL)
            """,
            (industry_name,)
        )
        node_count = cursor.fetchone()[0]

        # 检查是否有白名单
        cursor.execute(
            "SELECT COUNT(*) FROM business_data.whitelist_company WHERE industry_name = %s",
            (industry_name,)
        )
        whitelist_count = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return {
            "status": "success",
            "data": {
                "industry_name": industry_name,
                "exists": True,
                "node_count": node_count,
                "whitelist_count": whitelist_count,
                "steps": len(STEPS)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取产业链信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pipeline_router.get("/industry/{industry_name}/step_status")
async def get_step_status(industry_name: str, current_user: dict = Depends(get_current_user)):
    """获取产业链各步骤的完成状态"""
    try:
        status = check_step_status(industry_name)
        task_state = _normalize_pipeline_task_status(industry_name, status)

        # 找出下一个未完成的步骤
        next_step = None
        for step_num in range(2, 11):
            if not status.get(step_num, False):
                next_step = step_num
                break

        return {
            "status": "success",
            "data": {
                "industry_name": industry_name,
                "step_status": status,
                "next_step": next_step,
                "all_completed": next_step is None,
                "task_status": task_state["status"],
                "is_running": task_state["is_running"],
                "current_step": task_state["current_step"],
                "current_step_name": task_state["current_step_name"],
                "progress": task_state["progress"],
                "updated_at": task_state["updated_at"],
                "heartbeat_age_seconds": task_state["heartbeat_age_seconds"]
            }
        }
    except Exception as e:
        logger.error(f"获取步骤状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pipeline_router.get("/logs/{industry_name}")
async def get_pipeline_logs(
    industry_name: str,
    limit: int = 100,
    after_id: int = None,
    current_user: dict = Depends(get_current_user)
):
    """获取产业链任务运行日志。"""
    try:
        return {
            "status": "success",
            "data": _get_pipeline_task_logs(industry_name, limit=limit, after_id=after_id)
        }
    except Exception as e:
        logger.error(f"获取任务日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pipeline_router.get("/tasks")
async def get_pipeline_tasks(limit: int = 100, current_user: dict = Depends(get_current_user)):
    """获取产业链任务运行概览。"""
    try:
        return {
            "status": "success",
            "data": _get_pipeline_task_overview(limit=limit)
        }
    except Exception as e:
        logger.error(f"获取任务概览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pipeline_router.delete("/tasks/{industry_name}")
async def delete_pipeline_task(industry_name: str, current_user: dict = Depends(get_current_user)):
    """删除运行监控中的任务记录，不删除产业链图谱数据。"""
    import pymysql

    if industry_name in running_tasks:
        task_info = running_tasks[industry_name]
        if task_info.get("task") and not task_info["task"].done():
            raise HTTPException(status_code=409, detail="任务仍在运行，不能删除")
        running_tasks.pop(industry_name, None)

    task_status.pop(industry_name, None)
    paused_tasks.pop(industry_name, None)

    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data',
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT status, updated_at FROM pipeline_task_status WHERE industry_name = %s ORDER BY id DESC LIMIT 1",
            (industry_name,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="没有可删除的任务记录")

        status, updated_at = row
        if status == "running" and _is_recent_task_update(updated_at):
            raise HTTPException(status_code=409, detail="任务仍在运行，不能删除")

        cursor.execute(
            """
            DELETE FROM pipeline_task_status
            WHERE industry_name = %s
              AND (
                  status IN ('error', 'cancelled', 'completed', 'paused')
                  OR (status = 'running' AND (updated_at IS NULL OR updated_at < DATE_SUB(NOW(), INTERVAL 90 SECOND)))
              )
            """,
            (industry_name,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        if deleted_count == 0:
            raise HTTPException(status_code=404, detail="没有可删除的已结束任务记录")
        return {
            "status": "success",
            "message": f"已删除 {industry_name} 的监控记录",
            "deleted_count": deleted_count
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"删除任务监控记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


@pipeline_router.get("/stream/{industry_name}")
async def stream_task_status(industry_name: str, current_user: dict = Depends(get_current_user)):
    """只监听已有任务状态，不启动新的处理流程。"""
    return EventSourceResponse(_stream_task_status_events(industry_name))


@pipeline_router.post("/process")
async def start_process(request: Request, current_user: dict = Depends(get_current_user)):
    """
    启动产业链自动化处理流程

    请求体格式:
    {
        "industry_name": "产业链名称",
        "start_step": 2,      // 可选，从指定步骤开始（支持断点续传）
        "force": false        // 可选，强制全量重跑，跳过变更检测（默认false）
    }

    返回 SSE 流，实时推送处理进度
    """
    data = await request.json()
    industry_name = data.get("industry_name", "").strip()
    start_step = data.get("start_step", 2)  # 默认从步骤2开始
    force = data.get("force", False)  # 是否强制全量重跑

    if not industry_name:
        raise HTTPException(status_code=400, detail="缺少 industry_name 参数")

    _clear_cancel_status(industry_name)

    # 验证产业链是否存在（从 industrial_chain_structure 表）
    import pymysql
    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        charset='utf8mb4'
    )
    cursor = conn.cursor()

    # 检查 industrial_chain_structure 表中是否存在该产业链
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM industrial_chain.industrial_chain_structure
        WHERE chain_name = %s
          AND (status = 1 OR status IS NULL)
        """,
        (industry_name,)
    )
    count = cursor.fetchone()[0]

    if count == 0:
        cursor.close()
        conn.close()
        raise HTTPException(
            status_code=404,
            detail=f"产业链 '{industry_name}' 不存在"
        )

    # 查询节点数据
    node_data = _fetch_active_structure_nodes(cursor, industry_name)
    cursor.close()
    conn.close()

    logger.info(f"从 industrial_chain_structure 查询到 {len(node_data)} 条节点数据")

    # ========== 使用Celery异步任务（如果可用）==========
    if CELERY_AVAILABLE:
        logger.info(f"使用Celery执行任务: {industry_name}, start_step={start_step}")

        # 先同步数据到 chain_needcomp
        sync_conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data',
            charset='utf8mb4'
        )
        sync_cursor = sync_conn.cursor()
        sync_result = _sync_chain_nodes_and_cleanup(sync_cursor, industry_name, node_data)
        sync_conn.commit()
        sync_cursor.close()
        sync_conn.close()
        logger.info(f"已同步 {sync_result['insert_count']} 条节点数据到 chain_needcomp")

        # 先清除取消标志，确保任���可以执行
        clear_conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data',
            charset='utf8mb4'
        )
        clear_cursor = clear_conn.cursor()
        clear_cursor.execute("""
            UPDATE pipeline_task_status
            SET cancelled_at = NULL, status = 'running'
            WHERE industry_name = %s
        """, (industry_name,))
        clear_conn.commit()
        clear_cursor.close()
        clear_conn.close()
        logger.info(f"已清除取消标志: {industry_name}")

        # 提交Celery任务
        task = run_pipeline_task.delay(industry_name, start_step=start_step)
        logger.info(f"Celery任务已提交: task_id={task.id}, industry={industry_name}")

        # 返回SSE流，通过轮询推送进度
        async def event_generator_celery():
            last_status = None
            last_progress = -1
            check_count = 0
            max_checks = 7200  # 最多检查2小时

            # 发送初始消息
            yield f"data: {json.dumps({'type': 'start', 'content': '任务已提交，正在执行...'})}\n\n"

            while check_count < max_checks:
                try:
                    status_conn = pymysql.connect(
                        host='8.141.5.67',
                        user='root',
                        password=os.getenv('DB_PASSWORD'),
                        database='business_data',
                        charset='utf8mb4',
                        connect_timeout=5
                    )
                    status_cursor = status_conn.cursor()
                    status_cursor.execute("""
                        SELECT status, current_step, progress, error_message
                        FROM pipeline_task_status
                        WHERE industry_name = %s
                    """, (industry_name,))
                    row = status_cursor.fetchone()
                    status_cursor.close()
                    status_conn.close()

                    if row:
                        status, step, progress, error = row
                        if status != last_status or progress != last_progress:
                            yield f"data: {json.dumps({'type': 'progress', 'content': {'step': step, 'progress': progress, 'status': status}})}\n\n"
                            last_status = status
                            last_progress = progress

                        if status == 'completed':
                            yield f"data: {json.dumps({'type': 'completed', 'content': '任务完成'})}\n\n"
                            break
                        elif status == 'cancelled':
                            yield f"data: {json.dumps({'type': 'cancelled', 'content': '任务已取消'})}\n\n"
                            break
                        elif status == 'error':
                            yield f"data: {json.dumps({'type': 'error', 'content': error or '任务执行失败'})}\n\n"
                            break

                except Exception as e:
                    logger.error(f"查询任务状态失败: {e}")

                check_count += 1
                await asyncio.sleep(1)

            if check_count >= max_checks:
                yield f"data: {json.dumps({'type': 'timeout', 'content': '查询超时'})}\n\n"

        return EventSourceResponse(event_generator_celery())

    # Celery不可用时使用旧的同步执行方式
    async def event_generator():
        queue = asyncio.Queue()

        async def send_message(message, message_type="info"):
            try:
                _record_pipeline_activity(industry_name, message_type, message)
            except Exception as log_exc:
                logger.error(f"记录任务日志失败: {log_exc}")
            await queue.put({"data": json.dumps({"type": message_type, "content": message})})

        # 创建线程安全的进度回调（步骤函数在线程��中执行）
        def create_progress_callback():
            """创建线程安全的进度回调函数"""
            loop = asyncio.get_event_loop()

            def progress_callback(message_type, content):
                """步骤函数可以调用的进度回调

                Args:
                    message_type: 消息类型 ('progress', 'info', 'warning', 'batch_progress')
                    content: 消息内容，可以是字符串或字典
                """
                try:
                    try:
                        _record_pipeline_activity(industry_name, message_type, content)
                    except Exception as log_exc:
                        logger.error(f"记录步骤进度日志失败: {log_exc}")
                    # 使用 call_soon_threadsafe 确保线程安全
                    loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(
                            queue.put({"data": json.dumps({"type": message_type, "content": content})})
                        )
                    )
                except Exception as e:
                    logger.error(f"进度回调失败: {e}")

            return progress_callback

        async def task_heartbeat():
            while True:
                await asyncio.sleep(30)
                current_task = running_tasks.get(industry_name)
                if not current_task or current_task.get("cancelled"):
                    return
                task_obj = current_task.get("task")
                if task_obj and task_obj.done():
                    return
                try:
                    _write_pipeline_task_status(industry_name, status="running")
                except Exception as heartbeat_exc:
                    logger.error(f"更新任务心跳失败: {heartbeat_exc}")

        async def run_pipeline():
            """执行自动化处理流程"""
            try:
                tables = TABLES  # 使用全局的TABLES定义
                progress_callback = create_progress_callback()

                # 在数据库中记录任务开始
                try:
                    import pymysql
                    # 更新 pipeline_task_status 表
                    status_conn = pymysql.connect(
                        host='8.141.5.67',
                        user='root',
                        password=os.getenv('DB_PASSWORD'),
                        database='business_data'
                    )
                    status_cursor = status_conn.cursor()
                    status_cursor.execute("""
                        INSERT INTO pipeline_task_status
                        (industry_name, status, current_step, current_step_name, progress)
                        VALUES (%s, 'running', 0, '准备环境', 0)
                        ON DUPLICATE KEY UPDATE
                        status = 'running',
                        current_step = 0,
                        current_step_name = '准备环境',
                        progress = 0,
                        started_at = NOW(),
                        completed_at = NULL,
                        cancelled_at = NULL,
                        updated_at = NOW()
                    """, (industry_name,))
                    status_conn.commit()
                    status_cursor.close()
                    status_conn.close()
                except Exception as e:
                    logger.error(f"记录任务状态失败: {e}")

                await send_message(f"开始处理产业链: {industry_name}", "start")
                await send_message({
                    "step": 0,
                    "step_name": "同步数据",
                    "message": "从 industrial_chain_structure 同步节点数据到 chain_needcomp..."
                }, "progress")

                # 同步数据：从 industrial_chain_structure 到 chain_needcomp
                try:
                    import pymysql
                    sync_conn = pymysql.connect(
                        host='8.141.5.67',
                        user='root',
                        password=os.getenv('DB_PASSWORD'),
                        database='business_data',
                        charset='utf8mb4'
                    )
                    sync_cursor = sync_conn.cursor()

                    sync_result = _sync_chain_nodes_and_cleanup(sync_cursor, industry_name, node_data)

                    sync_conn.commit()
                    sync_cursor.close()
                    sync_conn.close()

                    insert_count = sync_result["insert_count"]
                    logger.info(f"成功同步 {insert_count} 条节点数据到 chain_needcomp")
                    await send_message(f"已同步 {insert_count} 条节点数据", "info")
                    if sync_result["structure_changed"]:
                        await send_message(
                            {
                                "step": 0,
                                "step_name": "结构变更清理",
                                "message": "检测到节点结构变化，已清理步骤3-10旧结果，本次将按新结构重跑",
                                "added_nodes": sync_result["added_nodes"],
                                "removed_nodes": sync_result["removed_nodes"],
                                "changed_nodes": sync_result["changed_nodes"],
                            },
                            "warning"
                        )

                except Exception as e:
                    logger.error(f"数据同步失败: {e}")
                    await send_message(f"数据同步失败: {e}", "error")
                    raise

                await send_message({
                    "step": 0,
                    "step_name": "准备环境",
                    "message": "检查并创建数据库表..."
                }, "progress")

                # 确保表存在
                from auto_industry_chain_pipeline import ensure_tables_exist
                ensure_tables_exist()

                results = []

                # ========== 变更检测（增量更新） ==========
                change_context = None
                steps_to_skip = set()

                if not force and start_step <= 2:
                    # 非强制模式且从头开始时，执行变更检测
                    await send_message({
                        "step": 0,
                        "step_name": "变更检测",
                        "message": "正在检测图谱和白名单变更..."
                    }, "progress")

                    try:
                        from services.change_detector import (
                            ChangeDetector,
                            update_graph_snapshot,
                            update_whitelist_snapshot,
                        )

                        detector = ChangeDetector(industry_name)
                        changes = detector.detect_all_changes()

                        await send_message({
                            "type": "change_detection",
                            "changes": changes
                        }, "info")

                        if (
                            not changes['has_changes']
                            and (
                                changes.get('whitelist_snapshot_missing')
                                or changes.get('graph_snapshot_missing')
                            )
                        ):
                            step_status = check_step_status(industry_name)
                            has_existing_step_data = any(step_status.get(s, False) for s in range(2, 11))
                            if has_existing_step_data:
                                await send_message(
                                    "检测到快照基线缺失，但该产业链已有步骤数据，正在初始化快照基线",
                                    "info"
                                )
                                if changes.get('whitelist_snapshot_missing'):
                                    update_whitelist_snapshot(industry_name)
                                if changes.get('graph_snapshot_missing'):
                                    update_graph_snapshot(industry_name)

                                changes['whitelist_snapshot_missing'] = False
                                changes['graph_snapshot_missing'] = False
                                changes['change_summary'] = '无变更'

                        if not changes['has_changes']:
                            logger.info(f"变更检测发现无变化，检查步骤数据完整性...")
                            # 检查各步骤数据是否完整
                            step_status = check_step_status(industry_name)
                            incomplete_steps = [s for s in range(2, 11) if not step_status.get(s, False)]

                            logger.info(f"步骤数据检查结果: 不完整步骤={incomplete_steps}")

                            if incomplete_steps:
                                await send_message(f"未检测到变更，但发现步骤 {incomplete_steps} 数据不完整，将继续执行", "info")
                                logger.info(f"将仅执行缺失步骤: {incomplete_steps}")
                                all_steps = [s['step'] for s in STEPS]
                                steps_to_rerun = incomplete_steps
                                steps_to_skip = set(all_steps) - set(incomplete_steps)
                                change_context = None
                            else:
                                await send_message("未检测到变更，数据完整，无需重新处理", "info")
                                logger.info(f"数据完整，跳过执行")
                                # 仍然需要更新状态
                                try:
                                    meta_conn = pymysql.connect(
                                        host='8.141.5.67',
                                        user='root',
                                        password=os.getenv('DB_PASSWORD'),
                                        database='industrial_chain',
                                        charset='utf8mb4'
                                    )
                                    meta_cursor = meta_conn.cursor()
                                    meta_cursor.execute("""
                                        UPDATE industrial_chain_meta
                                        SET status = 2
                                        WHERE name = %s
                                    """, (industry_name,))
                                    meta_conn.commit()
                                    meta_cursor.close()
                                    meta_conn.close()
                                except:
                                    pass
                                return
                        else:
                            # 有变更：根据变更确定需要跳过的步骤
                            all_steps = [s['step'] for s in STEPS]
                            steps_to_rerun = changes.get('steps_to_rerun', all_steps)
                            incomplete_steps = get_incomplete_steps(industry_name)
                            if incomplete_steps:
                                steps_to_rerun = sorted(set(steps_to_rerun) | set(incomplete_steps))
                                await send_message(
                                    f"发现步骤 {incomplete_steps} 数据缺失或不完整，已加入本次重跑",
                                    "warning"
                                )
                                logger.info(f"变更检测后补充缺失步骤重跑: {incomplete_steps}")
                            steps_to_skip = set(all_steps) - set(steps_to_rerun)

                            # 将变更信息传递给需要增量处理的步骤
                            change_context = {
                                'added_nodes': changes.get('added_nodes', []),
                                'removed_nodes': changes.get('removed_nodes', []),
                                'modified_nodes': changes.get('modified_nodes', []),
                                'added_companies': changes.get('added_companies', []),
                                'removed_companies': changes.get('removed_companies', [])
                            }

                        if changes['has_changes'] or 'steps_to_rerun' in locals():
                            await send_message(f"检测到变更: {changes['change_summary']}，将重跑步骤 {steps_to_rerun}", "info")

                    except Exception as e:
                        logger.error(f"变更检测失败: {e}")
                        await send_message(f"变更检测失败，将执行全量更新: {str(e)}", "warning")
                        steps_to_skip = set()
                        change_context = None

                elif force:
                    await send_message("强制全量模式，将重跑所有步骤", "info")
                # ========== 变更检测结束 ==========

                # 如果start_step > 2，跳过前面的步骤
                if start_step > 2:
                    await send_message(f"从步骤{start_step}开始执行（跳过已完成的步骤）", "info")

                logger.info(f"=== 开始步骤循环 === steps_to_skip={steps_to_skip}, change_context={change_context}, start_step={start_step}")

                for step_info in STEPS:
                    # 【优先】检查是否被取消（在每个步骤开始前检查）
                    if is_task_cancelled(industry_name):
                        await send_message("任务已被取消", "cancelled")
                        logger.info(f"产业链 {industry_name} 任务被取消")
                        break

                    # 检查是否被暂停
                    is_paused = False
                    try:
                        import redis
                        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
                        pause_key = f"pipeline_pause:{industry_name}"
                        is_paused = r.exists(pause_key) > 0
                    except:
                        is_paused = industry_name in paused_tasks

                    if is_paused:
                        await send_message({
                            "step": step_num if 'step_num' in locals() else step_info['step'],
                            "step_name": step_info['name'],
                            "message": "任务已暂停"
                        }, "paused")
                        # 保存当前进度到数据库
                        try:
                            import pymysql
                            meta_conn = pymysql.connect(
                                host='8.141.5.67',
                                user='root',
                                password=os.getenv('DB_PASSWORD'),
                                database='business_data',
                                charset='utf8mb4'
                            )
                            meta_cursor = meta_conn.cursor()
                            meta_cursor.execute("""
                                UPDATE pipeline_task_status
                                SET status = 'paused', current_step = %s, paused_at = NOW()
                                WHERE industry_name = %s AND status = 'running'
                            """, (step_info['step'], industry_name))
                            meta_conn.commit()
                            meta_cursor.close()
                            meta_conn.close()
                        except Exception as e:
                            logger.error(f"保存暂停状态失败: {e}")
                        break

                    step_num = step_info['step']
                    step_name = step_info['name']
                    step_function_name = step_info['function']

                    logger.info(f"处理步骤{step_num}: {step_name}, start_step={start_step}, in_skip={step_num in steps_to_skip}")

                    # 跳过start_step之前的步骤
                    if step_num < start_step:
                        results.append({
                            'step': step_num,
                            'name': step_name,
                            'status': 'skipped',
                            'reason': '已在之前完成'
                        })
                        continue

                    # 跳过变更检测后不需要重跑��步骤
                    if step_num in steps_to_skip:
                        if await check_step_completed(industry_name, step_num, tables):
                            await send_message({
                                "step": step_num,
                                "step_name": step_name,
                                "message": f"步骤{step_num}无需重跑，跳过"
                            }, "info")
                            results.append({
                                'step': step_num,
                                'name': step_name,
                                'status': 'skipped',
                                'reason': '变更检测：无需重跑'
                            })
                            continue

                        await send_message({
                            "step": step_num,
                            "step_name": step_name,
                            "message": f"变更检测建议跳过步骤{step_num}，但发现该步骤数据缺失或不完整，将继续执行"
                        }, "warning")
                        logger.info(f"步骤{step_num}在变更检测跳过列表中，但数据缺失或不完整，改为执行")

                    # 检查该步骤是否已完成（通过检查目标表是否有数据）
                    # 只有在非变更检测模式下才检查步骤是否已完成
                    # 如果变更检测确定需要重跑，则不检查是否已有数据
                    change_detection_was_run = (not force and start_step <= 2 and change_context is not None)
                    logger.info(f"步骤{step_num}: change_detection_was_run={change_detection_was_run}, force={force}, change_context_is_not_None={change_context is not None}")

                    if not change_detection_was_run and await check_step_completed(industry_name, step_num, tables):
                        await send_message({
                            "step": step_num,
                            "step_name": step_name,
                            "message": f"步骤{step_num}已完成，跳过"
                        }, "info")
                        results.append({
                            'step': step_num,
                            'name': step_name,
                            'status': 'skipped',
                            'reason': '已有数据'
                        })
                        logger.info(f"步骤{step_num}已完成，跳过")
                        continue

                    # 【重要】在执行步骤前再次检查是否被取消（实现立即停止）
                    if is_task_cancelled(industry_name):
                        await send_message("任务已被取消", "cancelled")
                        logger.info(f"产业链 {industry_name} 任务被取消，跳过步骤{step_num}")
                        break

                    await send_message({
                        "step": step_num,
                        "step_name": step_name,
                        "message": f"开始执行步骤{step_num}: {step_name}"
                    }, "progress")
                    try:
                        step_index = next((idx for idx, step in enumerate(STEPS, start=1) if step['step'] == step_num), 1)
                        _write_pipeline_task_status(
                            industry_name,
                            status="running",
                            current_step=step_num,
                            current_step_name=step_name,
                            progress=round(((step_index - 1) / len(STEPS)) * 100)
                        )
                    except Exception as progress_exc:
                        logger.error(f"更新步骤进度失败: {progress_exc}")

                    try:
                        # 加载白名单数据（如果需要）
                        whitelist_data = None
                        if step_info.get('need_whitelist', False):
                            whitelist_data = load_whitelist_data(industry_name)

                        # 动态导入并执行步骤函数
                        import importlib
                        module = importlib.import_module(f'steps.{step_function_name}')
                        step_func = getattr(module, step_function_name)

                        # 在线程池中执行同步函数，传入进度回调
                        loop = asyncio.get_event_loop()

                        # 准备参数，支持增量处理的步骤传递 change_context
                        step_args = [industry_name, TABLES, whitelist_data, progress_callback]
                        if step_num in [2, 3, 4, 6] and change_context:
                            step_args.append(change_context)

                        result = await loop.run_in_executor(
                            None,
                            step_func,
                            *step_args
                        )

                        if isinstance(result, dict) and result.get('status') in {'error', 'cancelled'}:
                            message = result.get('error') or result.get('message') or result.get('reason') or '步骤执行未完成'
                            if result.get('status') == 'cancelled':
                                await send_message({
                                    "step": step_num,
                                    "step_name": step_name,
                                    "message": f"步骤{step_num}已取消: {message}",
                                    "result": result
                                }, "cancelled")
                            else:
                                await send_message({
                                    "step": step_num,
                                    "step_name": step_name,
                                    "message": f"步骤{step_num}失败: {message}",
                                    "result": result
                                }, "error")
                            raise RuntimeError(f"步骤{step_num}返回{result.get('status')}: {message}")

                        results.append({
                            'step': step_num,
                            'name': step_name,
                            'status': 'completed',
                            'result': result
                        })

                        # 步骤5完成后，更新产业链状态为"已完成"(2)
                        if step_num == 5:
                            try:
                                import pymysql
                                meta_conn = pymysql.connect(
                                    host='8.141.5.67',
                                    user='root',
                                    password=os.getenv('DB_PASSWORD'),
                                    database='industrial_chain',
                                    charset='utf8mb4'
                                )
                                meta_cursor = meta_conn.cursor()
                                meta_cursor.execute("""
                                    UPDATE industrial_chain_meta
                                    SET status = 2
                                    WHERE name = %s
                                """, (industry_name,))
                                meta_conn.commit()
                                meta_cursor.close()
                                meta_conn.close()
                                logger.info(f"步骤5完成，已将产业链 {industry_name} 状态设置为已完成(2)")
                            except Exception as status_e:
                                logger.error(f"更新产业链状态失败: {status_e}")

                        # 检查步骤是否被跳过
                        if isinstance(result, dict) and result.get('status') == 'skipped':
                            await send_message({
                                "step": step_num,
                                "step_name": step_name,
                                "message": f"步骤{step_num}跳过: {result.get('reason', '无数据')}",
                                "result": result
                            }, "step_skipped")
                        else:
                            await send_message({
                                "step": step_num,
                                "step_name": step_name,
                                "message": f"步骤{step_num}完成: {step_name}",
                                "result": result
                            }, "step_completed")
                        try:
                            step_index = next((idx for idx, step in enumerate(STEPS, start=1) if step['step'] == step_num), 1)
                            _write_pipeline_task_status(
                                industry_name,
                                status="running",
                                current_step=step_num,
                                current_step_name=step_name,
                                progress=round((step_index / len(STEPS)) * 100)
                            )
                        except Exception as progress_exc:
                            logger.error(f"更新步骤完成进度失败: {progress_exc}")

                    except Exception as e:
                        error_msg = f"步骤{step_num}失败: {str(e)}"
                        logger.error(error_msg)
                        try:
                            _write_pipeline_task_status(
                                industry_name,
                                status="error",
                                current_step=step_num,
                                current_step_name=step_name,
                                error_message=error_msg
                            )
                        except Exception as progress_exc:
                            logger.error(f"更新步骤错误状态失败: {progress_exc}")
                        await send_message({
                            "step": step_num,
                            "step_name": step_name,
                            "message": error_msg,
                            "error": str(e)
                        }, "error")
                        raise

                # ============ 产业链特殊后置处理(仅特定链, 如工业软件定向优化) ============
                try:
                    from steps.chain_special_processing import apply_chain_special_processing
                    sp_result = await asyncio.get_event_loop().run_in_executor(None, apply_chain_special_processing, industry_name)
                    results.append({'step': 11, 'name': '产业链特殊处理', 'status': sp_result.get('status', 'completed'), 'result': sp_result})
                    await send_message({"step": 11, "step_name": "产业链特殊处理", "message": sp_result.get('reason', str(sp_result))}, "info")
                except Exception as sp_e:
                    logger.error(f"产业链特殊后置处理失败: {sp_e}")
                # ============ 产业链特殊后置处理结束 ============

                # 完成
                final_result = {
                    'industry_name': industry_name,
                    'status': 'completed',
                    'total_steps': len(STEPS),
                    'completed': len(results),
                    'results': results
                }

                await send_message({
                    "message": f"产业链 {industry_name} 处理完成！",
                    "result": final_result
                }, "completed")
                # 发送钉钉通知（支持 CAS 和普通登录用户）
                try:
                    from services.dingtalk_service import get_bot
                    oa_user_id = current_user.get("oa_user_id") or current_user.get("username")

                    if oa_user_id:
                        bot = get_bot("industry_chain")
                        dinguserid = bot.get_dinguserid_by_alias(oa_user_id)
                        if dinguserid:
                            notification_title = f"🏢 {industry_name}企业名单生成完毕"
                            notification_content = f"""## 🏢 企业名单生成完成

---

**产业链名称：** {industry_name}

**生成时间：** 刚刚

**总步骤数：** 10

---

### ✅ 第二阶段已完成

企业名单已经成功生成，包含上中下游企业信息。

---

### 📊 生成内容

- 节点定义
- 节点匹配行业
- 公司匹配节点
- 企业名称补全
- 头部企业搜索
- 头部企业匹配
- 结果拆分
- 合并去重清理
- 最终名单输出
- 上线表输出

---

### 📋 后续操作

可以导出企业名单或查看详细信息。

---

📌 **产业链智能体** 自动通知
"""
                            bot.send_single_markdown([dinguserid], notification_title, notification_content)
                            logger.info(f"已发送钉钉通知到用户 {oa_user_id}（第二阶段完成）")
                except Exception as dingtalk_error:
                    logger.warning(f"发送钉钉通知失败: {str(dingtalk_error)}")
                    _write_pipeline_task_status(
                        industry_name,
                        status="completed",
                        current_step=10,
                        current_step_name="输出上线表",
                        progress=100,
                        completed=True
                    )
                except Exception as progress_exc:
                    logger.error(f"更新完成状态失败: {progress_exc}")

                # 延迟关闭SSE连接，确保前端收到completed事件
                await asyncio.sleep(3)

            except Exception as e:
                error_msg = f"流程执行失败: {str(e)}"
                logger.error(error_msg)
                try:
                    _write_pipeline_task_status(
                        industry_name,
                        status="error",
                        error_message=error_msg
                    )
                except Exception as progress_exc:
                    logger.error(f"更新流程错误状态失败: {progress_exc}")
                await send_message(error_msg, "error")
                raise

        # 启动���理任务
        task = asyncio.create_task(run_pipeline())
        heartbeat_task = asyncio.create_task(task_heartbeat())

        # 记录到全局任务跟踪
        running_tasks[industry_name] = {
            "task": task,
            "heartbeat_task": heartbeat_task,
            "cancelled": False,
            "queue": queue
        }

        # 记录任务执行结果
        task_exception = None
        task_succeeded = False

        try:
            # 发送心跳和消息
            while True:
                try:
                    # 检查任务是否完成
                    if task.done():
                        # 获取任务结果或异常
                        try:
                            result = await task
                            task_succeeded = True
                            logger.info(f"任务 {industry_name} 成功完成")
                        except Exception as e:
                            task_exception = e
                            logger.error(f"任务 {industry_name} 执行失败: {e}")
                        break

                    # 等待消息，设置超时
                    try:
                        sse_event = await asyncio.wait_for(queue.get(), timeout=1.0)
                        if sse_event is None:
                            break
                        yield sse_event
                    except asyncio.TimeoutError:
                        # 发送心跳
                        yield {"data": json.dumps({'type': 'heartbeat', 'content': 'heartbeat'})}

                except Exception as e:
                    logger.error(f"消息处理出错: {e}")
                    yield {"data": json.dumps({'type': 'error', 'content': str(e)})}
                    break

        finally:
            # 仅在任务真正完成/失败/取消时更新数据库状态
            # 如果SSE断开但任务仍在运行，不做任何数据库更新（任务自己会更新进度）
            was_cancelled = running_tasks.get(industry_name, {}).get('cancelled', False) or _is_cancel_requested(industry_name)
            if task.done() or was_cancelled or task_exception is not None:
                try:
                    import pymysql

                    # 根据任务实际执行结果设置状态
                    if was_cancelled:
                        status = 'cancelled'
                    elif task_exception:
                        status = 'error'
                        logger.error(f"任务 {industry_name} 因异常结束，状态设为error: {task_exception}")
                    elif task_succeeded:
                        status = 'completed'
                        logger.info(f"任务 {industry_name} 成功完成，状态设为completed")
                    else:
                        status = 'error'  # 任务结束但没有成功也没有异常标记为error
                        logger.warning(f"任务 {industry_name} 异常结束，状态设为error")

                    # 更新 pipeline_task_status 表
                    conn = pymysql.connect(
                        host="8.141.5.67",
                        user="root",
                        password=os.getenv("DB_PASSWORD"),
                        database="business_data"
                    )
                    cursor = conn.cursor()

                    if status == 'completed':
                        # 任务成功完成，设置完成状态
                        cursor.execute("""
                            INSERT INTO pipeline_task_status
                            (industry_name, status, current_step, progress, completed_at, cancelled_at)
                            VALUES (%s, %s, %s, %s, NOW(), %s)
                            ON DUPLICATE KEY UPDATE
                            status = VALUES(status),
                            current_step = VALUES(current_step),
                            progress = VALUES(progress),
                            completed_at = VALUES(completed_at),
                            cancelled_at = VALUES(cancelled_at)
                        """, (industry_name, status, 10, 100, None))
                    elif status == 'error':
                        # 任务失败，记录错误信息
                        cursor.execute("""
                            INSERT INTO pipeline_task_status
                            (industry_name, status, error_message, updated_at)
                            VALUES (%s, %s, %s, NOW())
                            ON DUPLICATE KEY UPDATE
                            status = VALUES(status),
                            error_message = VALUES(error_message),
                            updated_at = VALUES(updated_at)
                        """, (industry_name, status, str(task_exception)[:500] if task_exception else '未知错误'))
                    elif status == 'cancelled':
                        # 任务被取消
                        cursor.execute("""
                            INSERT INTO pipeline_task_status
                            (industry_name, status, cancelled_at, updated_at)
                            VALUES (%s, %s, NOW(), NOW())
                            ON DUPLICATE KEY UPDATE
                            status = VALUES(status),
                            cancelled_at = VALUES(cancelled_at),
                            updated_at = VALUES(updated_at)
                        """, (industry_name, status))
                    else:
                        # 任务仍在运行（SSE断开但任务继续），不更新状态
                        logger.info(f"任务 {industry_name} 仍在后台运行，保持running状态")

                    conn.commit()
                    cursor.close()
                    conn.close()

                    # 同时更新 industrial_chain_meta 表的状态（仅在真正完成时）
                    if status == 'completed':
                        meta_status = 2  # 已完成
                        meta_conn = pymysql.connect(
                            host='8.141.5.67',
                            user='root',
                            password=os.getenv('DB_PASSWORD'),
                            database='industrial_chain',
                            charset='utf8mb4'
                        )
                        meta_cursor = meta_conn.cursor()
                        meta_cursor.execute("""
                            UPDATE industrial_chain_meta
                            SET status = %s
                            WHERE name = %s
                        """, (meta_status, industry_name))
                        meta_conn.commit()
                        meta_cursor.close()
                        meta_conn.close()
                        logger.info(f"已将产业链 {industry_name} 状态设置为 {meta_status} (已完成)")

                        # 更新快照（仅在任务成功完成时）
                        try:
                            from services.change_detector import update_whitelist_snapshot, update_graph_snapshot
                            update_whitelist_snapshot(industry_name)
                            update_graph_snapshot(industry_name)
                            logger.info(f"已更新产业链 {industry_name} 的快照")
                        except Exception as snapshot_e:
                            logger.error(f"更新快照失败: {snapshot_e}")
                    elif status == 'cancelled':
                        # 取消时设置为已废弃(3)
                        meta_status = 3
                        meta_conn = pymysql.connect(
                            host='8.141.5.67',
                            user='root',
                            password=os.getenv('DB_PASSWORD'),
                            database='industrial_chain',
                            charset='utf8mb4'
                        )
                        meta_cursor = meta_conn.cursor()
                        meta_cursor.execute("""
                            UPDATE industrial_chain_meta
                            SET status = %s
                            WHERE name = %s
                        """, (meta_status, industry_name))
                        meta_conn.commit()
                        meta_cursor.close()
                        meta_conn.close()
                        logger.info(f"已将产业链 {industry_name} 状态设置为 {meta_status} (已废弃)")
                except Exception as e:
                    logger.error(f"更新任务状态失败: {e}")

            # 清理
            if was_cancelled and not task.done():
                task.cancel()
            if heartbeat_task and not heartbeat_task.done() and (task.done() or was_cancelled):
                heartbeat_task.cancel()
            # 清理任务记录
            if industry_name in running_tasks and (task.done() or was_cancelled):
                del running_tasks[industry_name]

    return EventSourceResponse(event_generator())


@pipeline_router.post("/stop")
async def stop_process(request: Request, current_user: dict = Depends(get_current_user)):
    """
    停止正在运行的产业链处理任务

    请求体格式:
    {
        "industry_name": "产业链名称"
    }
    """
    data = await request.json()
    industry_name = data.get("industry_name", "").strip()

    if not industry_name:
        raise HTTPException(status_code=400, detail="缺少 industry_name 参数")

    cancel_task(industry_name)
    try:
        _set_task_status_cancelled(industry_name)
    except Exception as e:
        logger.error(f"写入共享取消状态失败: {e}")

    # 如果使用Celery，取消Celery任务
    if CELERY_AVAILABLE:
        try:
            from tasks.pipeline_tasks import cancel_pipeline_task
            cancel_pipeline_task(industry_name)
            logger.info(f"已发送取消信号给Celery任务: {industry_name}")
        except Exception as e:
            logger.error(f"取消Celery任务失败: {e}")

    # 立即取消当前 worker 中的任务；其他 worker 会通过数据库取消状态感知。
    if industry_name in running_tasks:
        # 设置取消标志
        running_tasks[industry_name]["cancelled"] = True

        # 立即取消asyncio任务
        task = running_tasks[industry_name].get("task")
        if task and not task.done():
            task.cancel()
            logger.info(f"已取消产业链 {industry_name} 的asyncio任务")

        # 发送停止消息给SSE连接
        messages = running_tasks[industry_name].get("messages", [])
        messages.append({
            "type": "cancelled",
            "content": "任务已被取消"
        })
    else:
        logger.info(f"未在当前worker找到任务 {industry_name}，已写入共享取消状态")

    return {
        "status": "success",
        "message": f"已发送产业链 {industry_name} 的停止信号"
    }


async def update_stop_status_db(industry_name: str):
    """异步更新停止状态到数据库"""
    try:
        import pymysql
        # 更新 pipeline_task_status 表
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data'
        )
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pipeline_task_status
            (industry_name, status, cancelled_at)
            VALUES (%s, 'cancelled', NOW())
            ON DUPLICATE KEY UPDATE
            status = 'cancelled',
            cancelled_at = NOW()
        """, (industry_name,))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"已更新产业链 {industry_name} 的停止状态到数据库")
    except Exception as e:
        logger.error(f"更新停止状态失败: {e}")


@pipeline_router.get("/status_legacy/{industry_name}")
async def get_task_status_legacy(industry_name: str, current_user: dict = Depends(get_current_user)):
    return await get_task_status(industry_name, current_user)


@pipeline_router.get("/status/{industry_name}")
async def get_task_status(industry_name: str, current_user: dict = Depends(get_current_user)):
    """
    获取产业链处理任务的状态

    返回：是否正在运行、当前步骤、进度等
    """
    try:
        status = check_step_status(industry_name)
        task_state = _normalize_pipeline_task_status(industry_name, status)
        recent_logs = _get_pipeline_task_logs(industry_name, limit=10)

        return {
            "status": "success",
            "data": {
                "industry_name": industry_name,
                "is_running": task_state["is_running"],
                "status": task_state["status"],
                "current_step": task_state["current_step"],
                "current_step_name": task_state["current_step_name"],
                "total_steps": task_state["total_steps"],
                "completed_steps": task_state["completed_steps"],
                "progress": task_state["progress"],
                "error_message": task_state["error_message"],
                "updated_at": task_state["updated_at"],
                "heartbeat_age_seconds": task_state["heartbeat_age_seconds"],
                "step_status": status,
                "latest_log": recent_logs[-1] if recent_logs else None,
                "recent_logs": recent_logs
            }
        }
    except Exception as e:
        logger.error(f"获取任务状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pipeline_router.post("/reset_status/{industry_name}")
async def reset_task_status(industry_name: str, current_user: dict = Depends(get_current_user)):
    """
    重置产业链任务状态

    用于处理任务异常退出后状态不一致的问题
    """
    import pymysql

    try:
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data'
        )
        cursor = conn.cursor()

        # 检查当前状态
        cursor.execute("""
            SELECT status FROM pipeline_task_status
            WHERE industry_name = %s
            ORDER BY id DESC LIMIT 1
        """, (industry_name,))

        result = cursor.fetchone()
        current_status = result[0] if result else None

        if current_status == 'running':
            # 更新为completed
            cursor.execute("""
                UPDATE pipeline_task_status
                SET status = 'completed'
                WHERE industry_name = %s AND status = 'running'
            """, (industry_name,))

            conn.commit()

            # 同时从running_tasks中移除（如果存在）
            if industry_name in running_tasks:
                del running_tasks[industry_name]

            cursor.close()
            conn.close()

            return {
                "status": "success",
                "message": f"已将产业链 '{industry_name}' 的状态重置为 'completed'"
            }
        else:
            cursor.close()
            conn.close()

            return {
                "status": "success",
                "message": f"产业链 '{industry_name}' 的状态不是 'running'，无需重置"
            }

    except Exception as e:
        logger.error(f"重置任务状态失败: {e}")
        return {
            "status": "error",
            "message": f"重置失败: {str(e)}"
        }


@pipeline_router.post("/pause")
async def pause_pipeline(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    暂停正在运行的产业链处理任务

    请求体格式:
    {
        "industry_name": "产业链名称"
    }
    """
    import redis
    import json

    try:
        data = await request.json()
        industry_name = data.get("industry_name", "").strip()

        if not industry_name:
            raise HTTPException(status_code=400, detail="缺少 industry_name 参数")

        # 使用Redis存储暂停状态
        try:
            r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            pause_key = f"pipeline_pause:{industry_name}"
            r.set(pause_key, "1", ex=3600)  # 1小时过期
            logger.info(f"已设置暂停标志: {pause_key}")
        except Exception as e:
            logger.warning(f"Redis连接失败，将使用内存存储: {e}")
            # 使用内存存储作为备选
            paused_tasks[industry_name] = True

        # 更新数据库状态为paused
        import pymysql
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data'
        )
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE pipeline_task_status
            SET status = 'paused', paused_at = NOW()
            WHERE industry_name = %s AND status = 'running'
        """, (industry_name,))

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "status": "success",
            "message": f"已暂停产业链 '{industry_name}' ��处理任务"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"暂停任务失败: {e}")
        return {
            "status": "error",
            "message": f"暂停失败: {str(e)}"
        }


@pipeline_router.post("/resume")
async def resume_pipeline(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    恢复已暂停的产业链处理任务

    请求体格式:
    {
        "industry_name": "产业链名称"
    }
    """
    import redis

    try:
        data = await request.json()
        industry_name = data.get("industry_name", "").strip()

        if not industry_name:
            raise HTTPException(status_code=400, detail="缺少 industry_name 参数")

        # 清除Redis中的暂停标志
        try:
            r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            pause_key = f"pipeline_pause:{industry_name}"
            r.delete(pause_key)
            logger.info(f"已清除暂停标志: {pause_key}")
        except Exception as e:
            logger.warning(f"Redis连接失败: {e}")
            # 清除内存存储
            if industry_name in paused_tasks:
                del paused_tasks[industry_name]

        # 检查是否有暂停的任务可以恢复
        import pymysql
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data'
        )
        cursor = conn.cursor()

        cursor.execute("""
            SELECT current_step FROM pipeline_task_status
            WHERE industry_name = %s AND status = 'paused'
            ORDER BY id DESC LIMIT 1
        """, (industry_name,))

        result = cursor.fetchone()

        if not result:
            cursor.close()
            conn.close()
            return {
                "status": "info",
                "message": f"没有找到可恢复的暂停任务"
            }

        current_step = result[0]

        # 更新状态为running
        cursor.execute("""
            UPDATE pipeline_task_status
            SET status = 'running', resumed_at = NOW()
            WHERE industry_name = %s AND status = 'paused'
        """, (industry_name,))

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "status": "success",
            "message": f"已恢复产业链 '{industry_name}' 的处理任务",
            "resume_from_step": current_step
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复任务失败: {e}")
        return {
            "status": "error",
            "message": f"恢复失败: {str(e)}"
        }


@pipeline_router.get("/pause_status/{industry_name}")
async def get_pause_status(
    industry_name: str,
    current_user: dict = Depends(get_current_user)
):
    """
    获取产业链任务的暂停状态

    Args:
        industry_name: 产业链名称

    Returns:
        暂停状态信息
    """
    import redis

    try:
        # 检查Redis中的暂停标志
        is_paused = False
        try:
            r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            pause_key = f"pipeline_pause:{industry_name}"
            is_paused = r.exists(pause_key) > 0
        except Exception as e:
            logger.warning(f"Redis连接失败: {e}")
            is_paused = industry_name in paused_tasks

        return {
            "status": "success",
            "data": {
                "industry_name": industry_name,
                "is_paused": is_paused
            }
        }

    except Exception as e:
        logger.error(f"获取暂停状态失败: {e}")
        return {
            "status": "error",
            "message": f"获取暂停状态失败: {str(e)}"
        }


@pipeline_router.post("/delete_steps")
async def delete_steps(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    删除指定步骤的数据

    请求体格式:
    {
        "industry_name": "产业链名称",
        "steps": [4, 5, 6]  // 要删除的步骤列表，支持单个或批量
    }
    """
    import pymysql

    try:
        data = await request.json()
        industry_name = data.get("industry_name", "").strip()
        steps = data.get("steps", [])

        if not industry_name:
            raise HTTPException(status_code=400, detail="缺少 industry_name 参数")

        if not steps:
            raise HTTPException(status_code=400, detail="缺少 steps 参数")

        if not isinstance(steps, list):
            steps = [steps]

        # 步骤对应的表配置
        step_tables = {
            2: ("chain_needcomp", "chain_name"),
            3: ("nodes_industry_mapping", "industry_name"),
            4: ("company_nodes_mapping", "industry_name"),
            5: ("company_nodes_top", "industry_chain"),
            6: ("company_nodes_info_result", "industry_name"),
            7: ("company_nodes_info_split", "industry_name"),
            8: ("company_nodes_final", "industry_name"),
            9: ("company_nodes_finallist", "industry_name"),
            10: ("company_list_output", "industry_name"),
        }

        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data',
            charset='utf8mb4'
        )
        cursor = conn.cursor()

        deleted_info = []
        total_deleted = 0

        for step in steps:
            if step not in step_tables:
                deleted_info.append({"step": step, "status": "skip", "reason": "无效的步骤号"})
                continue

            table_name, column_name = step_tables[step]

            try:
                cursor.execute(f"DELETE FROM {table_name} WHERE {column_name} = %s", (industry_name,))
                deleted_count = cursor.rowcount
                total_deleted += deleted_count
                deleted_info.append({
                    "step": step,
                    "status": "success",
                    "table": table_name,
                    "deleted_count": deleted_count
                })
                logger.info(f"删除步骤{step}数据: {table_name}, 删除{deleted_count}条")
            except Exception as e:
                deleted_info.append({
                    "step": step,
                    "status": "error",
                    "table": table_name,
                    "error": str(e)
                })

        cursor.execute("""
            UPDATE pipeline_task_status
            SET status = 'idle',
                current_step = 0,
                current_step_name = '',
                progress = 0,
                completed_at = NULL,
                cancelled_at = NULL,
                error_message = NULL,
                updated_at = NOW()
            WHERE industry_name = %s
        """, (industry_name,))
        task_status.pop(industry_name, None)

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "status": "success",
            "message": f"已完成步骤删除，共删除 {total_deleted} 条数据",
            "data": {
                "industry_name": industry_name,
                "deleted_steps": deleted_info,
                "total_deleted": total_deleted
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除步骤数据失败: {e}")
        return {
            "status": "error",
            "message": f"删除失败: {str(e)}"
        }


@pipeline_router.get("/export/{industry_name}")
async def export_industry_results(industry_name: str, current_user: dict = Depends(get_current_user)):
    """
    导出产业链处理结果（步骤9和步骤10的结果表）

    Args:
        industry_name: 产业链名称

    返回: Excel文件，包含三个Sheet
        - 最终名单 (步骤9)
        - 结构表 (步骤10)
        - 企业表 (步骤10)
    """
    import pymysql
    import pandas as pd
    from fastapi.responses import FileResponse
    from datetime import datetime
    import os

    try:
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data',
            charset='utf8mb4'
        )

        # 1. 读取步骤9结果：最终名单(分批读取全部数据)
        finallist_query = """
        SELECT company_name AS 企业名称,
               industry_name AS 产业链,
               nodes AS 节点,
               node_level AS 节点层级,
               parent_node AS 父节点,
               score AS 置信度
        FROM company_nodes_finallist
        WHERE industry_name = %s
        ORDER BY company_name, nodes
        """
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name = %s", (industry_name,))
            finallist_count = cursor.fetchone()[0]
            cursor.close()
            logger.info(f"导出 {industry_name}: finallist 有 {finallist_count} 条")
            # 分批读,每批 10 万条
            df_finallist = pd.DataFrame()
            batch_size = 100000
            for offset in range(0, finallist_count, batch_size):
                chunk = pd.read_sql(
                    f"SELECT company_name AS 企业名称, industry_name AS 产业链, nodes AS 节点, node_level AS 节点层级, parent_node AS 父节点, score AS 置信度 FROM company_nodes_finallist WHERE industry_name = %s LIMIT {batch_size} OFFSET {offset}",
                    conn, params=(industry_name,)
                )
                df_finallist = pd.concat([df_finallist, chunk], ignore_index=True)
                if offset % 500000 == 0:
                    logger.info(f"导出 {industry_name}: finallist 已读 {offset} 条")
        except Exception as e:
            logger.error(f"读取 finallist 失败: {e}")
            df_finallist = pd.DataFrame()

        # 2. 读取步骤10结果：结构表
        structure_query = """
        SELECT 编码, 产业环节, 父级id, 级别
        FROM industry_structure_output
        WHERE industry_name = %s
        ORDER BY 级别, 产业环节
        """
        try:
            df_structure = pd.read_sql(structure_query, conn, params=(industry_name,))
            logger.info(f"导出 {industry_name}: structure 有 {len(df_structure)} 条")
        except Exception as e:
            logger.error(f"读取 structure 失败: {e}")
            df_structure = pd.DataFrame()

        # 3. 读取步骤10结果：企业表(分批读取全部数据)
        company_query = """
        SELECT 层级1, 层级2, 层级3, 供应商
        FROM company_list_output
        WHERE industry_name = %s
        ORDER BY 层级1, 层级2, 层级3, 供应商
        """
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM company_list_output WHERE industry_name = %s", (industry_name,))
            company_count = cursor.fetchone()[0]
            cursor.close()
            logger.info(f"导出 {industry_name}: company_list_output 有 {company_count} 条")
            # 分批读,每批 10 万条
            df_company = pd.DataFrame()
            batch_size = 100000
            for offset in range(0, company_count, batch_size):
                chunk = pd.read_sql(
                    f"SELECT 层级1, 层级2, 层级3, 供应商 FROM company_list_output WHERE industry_name = %s LIMIT {batch_size} OFFSET {offset}",
                    conn, params=(industry_name,)
                )
                df_company = pd.concat([df_company, chunk], ignore_index=True)
                if offset % 500000 == 0:
                    logger.info(f"导出 {industry_name}: company_list 已读 {offset} 条")
        except Exception as e:
            logger.error(f"读取 company_list 失败: {e}")
            df_company = pd.DataFrame()

        # 自动补跑 step 10：如果 finallist 有数据但 company_list_output 为空
        if df_company.empty and not df_finallist.empty:
            logger.info(f"导出时发现 company_list_output 为空但 finallist 有 {len(df_finallist)} 条，自动补跑 step 10")
            try:
                from steps.step10_export_online_tables import step10_export_online_tables
                step10_export_online_tables(industry_name, TABLES)
                df_company = pd.read_sql(company_query, conn, params=(industry_name,))
                logger.info(f"step 10 补跑完成，company_list_output 现有 {len(df_company)} 条")
            except Exception as e:
                logger.error(f"导出时自动补跑 step 10 失败: {e}")

        conn.close()

        # 如果所有表都没有数据，返回错误
        if df_finallist.empty and df_structure.empty and df_company.empty:
            raise HTTPException(status_code=404, detail=f"产业链 '{industry_name}' 没有可导出的数据")

        # 创建临时Excel文件
        output_dir = "/root/mix_project/filled_reports"
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{industry_name}_结果_{timestamp}.xlsx"
        filepath = os.path.join(output_dir, filename)

        # 写入Excel文件(超过104万行分多个sheet)
        EXCEL_MAX_ROWS = 1000000  # Excel 单 sheet 最多约104万行,留余量
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            if not df_finallist.empty:
                if len(df_finallist) > EXCEL_MAX_ROWS:
                    for i, start in enumerate(range(0, len(df_finallist), EXCEL_MAX_ROWS)):
                        chunk = df_finallist.iloc[start:start+EXCEL_MAX_ROWS]
                        chunk.to_excel(writer, sheet_name=f'最终名单{i+1}', index=False)
                else:
                    df_finallist.to_excel(writer, sheet_name='最终名单', index=False)
            if not df_structure.empty:
                df_structure.to_excel(writer, sheet_name='结构表', index=False)
            if not df_company.empty:
                if len(df_company) > EXCEL_MAX_ROWS:
                    for i, start in enumerate(range(0, len(df_company), EXCEL_MAX_ROWS)):
                        chunk = df_company.iloc[start:start+EXCEL_MAX_ROWS]
                        chunk.to_excel(writer, sheet_name=f'企业表{i+1}', index=False)
                else:
                    df_company.to_excel(writer, sheet_name='企业表', index=False)
            # 保底:至少一个sheet
            if df_finallist.empty and df_structure.empty and df_company.empty:
                pd.DataFrame({"提示": ["无数据可导出"]}).to_excel(writer, sheet_name='提示', index=False)

        logger.info(f"导出产业链 {industry_name} 结果到: {filepath}")

        # 返回文件
        return FileResponse(
            path=filepath,
            filename=filename,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出失败: {e}")
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@pipeline_router.get("/export/list")
async def get_export_list(current_user: dict = Depends(get_current_user)):
    """
    获取可导出的产业链列表（已完成步骤9或步骤10的产业链）

    返回：产业链名称列表，包含每个产业链的数据统计
    """
    import pymysql

    try:
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data',
            charset='utf8mb4'
        )
        cursor = conn.cursor()

        # 获取有数据的产业链列表
        query = """
        SELECT
            industry_name AS 产业链名称,
            COUNT(*) AS 企业数量
        FROM company_nodes_finallist
        GROUP BY industry_name
        ORDER BY industry_name
        """
        cursor.execute(query)
        results = cursor.fetchall()

        cursor.close()
        conn.close()

        industries = []
        for row in results:
            industries.append({
                "industry_name": row[0],
                "company_count": row[1]
            })

        return {
            "status": "success",
            "data": industries
        }

    except Exception as e:
        logger.error(f"获取导出列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取导出列表失败: {str(e)}")


@pipeline_router.post("/cleanup_old_records")
async def cleanup_old_records(
    days: int = 30,
    current_user: dict = Depends(get_current_user)
):
    """
    清理指定天数之前已完成或已取消的任务记录

    Args:
        days: 保留最近多少天的记录，默认30天

    返回：清理的记录数量
    """
    import pymysql

    try:
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data'
        )
        cursor = conn.cursor()

        # 删除指定天数之前已完成或已取消的记录
        cursor.execute("""
            DELETE FROM pipeline_task_status
            WHERE (status = 'completed' OR status = 'cancelled')
            AND (
                (completed_at IS NOT NULL AND completed_at < DATE_SUB(NOW(), INTERVAL %s DAY))
                OR
                (cancelled_at IS NOT NULL AND cancelled_at < DATE_SUB(NOW(), INTERVAL %s DAY))
            )
        """, (days, days))

        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"清理了 {deleted_count} 条超过 {days} 天的旧任务记录")

        return {
            "status": "success",
            "message": f"已清理 {deleted_count} 条超过 {days} 天的旧任务记录",
            "deleted_count": deleted_count
        }

    except Exception as e:
        logger.error(f"清理旧记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"清理旧记录失败: {str(e)}")


# 后台清理任务
async def cleanup_old_records_task():
    """
    定期清理旧任务记录的后台任务
    每天凌晨2点执行一次，清理30天前的记录
    """
    while True:
        try:
            # 计算距离下次凌晨2点的时间
            import datetime
            now = datetime.datetime.now()
            next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += datetime.timedelta(days=1)

            wait_seconds = (next_run - now).total_seconds()
            logger.info(f"下次清理旧记录任务将在 {next_run} 执行，等待 {wait_seconds} 秒")

            await asyncio.sleep(wait_seconds)

            # 执行清理
            import pymysql
            conn = pymysql.connect(
                host='8.141.5.67',
                user='root',
                password=os.getenv('DB_PASSWORD'),
                database='business_data'
            )
            cursor = conn.cursor()

            # 删除30天前的已完成或已取消记录
            cursor.execute("""
                DELETE FROM pipeline_task_status
                WHERE (status = 'completed' OR status = 'cancelled')
                AND (
                    (completed_at IS NOT NULL AND completed_at < DATE_SUB(NOW(), INTERVAL 30 DAY))
                    OR
                    (cancelled_at IS NOT NULL AND cancelled_at < DATE_SUB(NOW(), INTERVAL 30 DAY))
                )
            """)

            deleted_count = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()

            logger.info(f"定期清理任务完成，清理了 {deleted_count} 条旧记录")

        except Exception as e:
            logger.error(f"定期清理任务失败: {e}")
            # 出错后等待1小时再重试
            await asyncio.sleep(3600)


# ==================== 产业链关键词增删规则 ====================
from steps.chain_keyword_rule import apply_rule, list_rules as list_kw_rules, remove_rule, replay, ensure_rule_table


@pipeline_router.post("/keyword_rule")
async def apply_keyword_rule(request: Request, current_user: dict = Depends(get_current_user)):
    """
    按企业名称关键词补充/删除名单企业 (增量, 不重跑整条链)

    请求体:
    {
        "industry_name": "产业链名称",
        "keyword": "企业名称关键词",
        "action": "add" 或 "delete"
    }
    - add: 从两张底表查含关键词的企业, 自动匹配节点后补充进名单(并持久化规则)
    - delete: 从最终名单 + 过程表删除含关键词的企业(并持久化规则)
    """
    data = await request.json()
    industry_name = (data.get("industry_name") or "").strip()
    keyword = (data.get("keyword") or "").strip()
    action = (data.get("action") or "").strip()
    if not industry_name or not keyword or action not in ("add", "delete"):
        raise HTTPException(status_code=400, detail="industry_name/keyword 必填, action 必须为 add 或 delete")
    try:
        return apply_rule(industry_name, keyword, action)
    except Exception as e:
        logger.error(f"关键词规则执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"执行失败: {e}")


@pipeline_router.get("/keyword_rule/{industry_name}")
async def get_keyword_rules(industry_name: str, current_user: dict = Depends(get_current_user)):
    """查询某条链已保存的关键词增删规则"""
    try:
        return list_kw_rules(industry_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


@pipeline_router.delete("/keyword_rule")
async def remove_keyword_rule(request: Request, current_user: dict = Depends(get_current_user)):
    """删除某条链的某条关键词规则(撤销); action 可选"""
    data = await request.json()
    industry_name = (data.get("industry_name") or "").strip()
    keyword = (data.get("keyword") or "").strip()
    action = (data.get("action") or "").strip() or None
    if not industry_name or not keyword:
        raise HTTPException(status_code=400, detail="industry_name/keyword 必填")
    try:
        n = remove_rule(industry_name, keyword, action)
        return {"status": "ok", "removed": n}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除规则失败: {e}")


@pipeline_router.post("/keyword_rule/replay/{industry_name}")
async def replay_keyword_rules(industry_name: str, current_user: dict = Depends(get_current_user)):
    """重放某条链的所有关键词规则(重跑后自动/手动调用, 先删后补)"""
    try:
        return replay(industry_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重放失败: {e}")
