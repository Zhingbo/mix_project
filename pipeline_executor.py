"""
Pipeline 后台执行器

使用线程池执行pipeline任务，不依赖SSE连接
任务一旦启动就会在后台运行，状态通过数据库查询
"""
import os

import asyncio
import threading
import time
import pymysql
from typing import Dict, Any, Callable, Optional
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 全局线程池
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pipeline_worker")

# 运行中的任务
_running_tasks: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


# 数据库配置
DB_CONFIG = {
    'host': '8.141.5.67',
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'charset': 'utf8mb4',
}


def update_status(industry_name: str, status: str, current_step: int = 0,
                  progress: int = 0, error_message: str = None, step_name: str = None):
    """更新任务状态到数据库"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()

        if status == 'running':
            sql = """
                UPDATE pipeline_task_status
                SET status = %s, current_step = %s, progress = %s,
                    current_step_name = %s, updated_at = NOW()
                WHERE industry_name = %s
            """
            cursor.execute(sql, (status, current_step, progress, step_name or '', industry_name))
        elif status == 'completed':
            sql = """
                UPDATE pipeline_task_status
                SET status = %s, current_step = %s, progress = 100,
                    completed_at = NOW(), updated_at = NOW()
                WHERE industry_name = %s
            """
            cursor.execute(sql, (status, current_step, industry_name))
        elif status == 'error':
            sql = """
                UPDATE pipeline_task_status
                SET status = %s, error_message = %s, updated_at = NOW()
                WHERE industry_name = %s
            """
            cursor.execute(sql, (status, error_message, industry_name))

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"更新状态失败: {e}")


def is_cancelled(industry_name: str) -> bool:
    """检查任务是否被取消"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT cancelled_at FROM pipeline_task_status WHERE industry_name = %s",
            (industry_name,)
        )
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result and result[0] is not None
    except:
        return False


def run_pipeline_sync(industry_name: str, start_step: int = 2,
                     progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """在线程中同步执行pipeline"""
    logger.info(f"[Pipeline Executor] 开始执行: {industry_name}, start_step={start_step}")

    # 步骤配置
    STEPS = [
        {'step': 2, 'name': '生成节点定义', 'function': 'step2_generate_definition'},
        {'step': 3, 'name': '节点匹配行业', 'function': 'step3_match_industryry'},
        {'step': 4, 'name': '公司匹配节点', 'function': 'step4_company_match_nodes'},
        {'step': 5, 'name': '搜索头部企业', 'function': 'step5_search_top_companies'},
        {'step': 6, 'name': '头部企业匹配节点', 'function': 'step6_top_company_match'},
        {'step': 7, 'name': '拆分结果', 'function': 'step7_split_results'},
        {'step': 8, 'name': '合并去重清理', 'function': 'step8_merge_and_clean'},
        {'step': 9, 'name': '输出最终名单', 'function': 'step9_export_finallist'},
        {'step': 10, 'name': '输出上线表', 'function': 'step10_export_online_tables'},
    ]

    TABLES = {
        'source_chain': 'industrial_chain.industrial_chain_structure',
        'whitelist_company': 'business_data.whitelist_company',
        'chain_needcomp': 'business_data.chain_needcomp',
        'company_nodes_mapping': 'business_data.company_nodes_mapping',
        'company_nodes_info_result': 'business_data.company_nodes_info_result',
        'company_nodes_info_split': 'business_data.company_nodes_info_split',
        'company_nodes_top': 'business_data.company_nodes_top',
        'company_nodes_final': 'business_data.company_nodes_final',
        'company_nodes_finallist': 'business_data.company_nodes_finallist',
        'industry_structure_output': 'business_data.industry_structure_output',
        'company_list_output': 'business_data.company_list_output',
        'mapping_industry_info_new': 'business_data.mapping_industry_info_new',
        'ent_industry_class_old': 'business_data.ent_industry_class_chain_scope_20260928_converted',
        'nodes_industry_mapping': 'business_data.nodes_industry_mapping',
        'company_nodes_mapping_temp': 'business_data.company_nodes_mapping_temp',
    }

    completed_steps = []

    try:
        for step_info in STEPS:
            step_num = step_info['step']
            step_name = step_info['name']
            step_function = step_info['function']

            # 跳过开始步骤之前的步骤
            if step_num < start_step:
                continue

            # 检查是否被取消
            if is_cancelled(industry_name):
                update_status(industry_name, 'cancelled')
                return {'status': 'cancelled', 'industry_name': industry_name}

            # 更新状态
            progress = int((step_num - 2) / (10 - 2) * 100)
            update_status(industry_name, 'running', current_step=step_num,
                         progress=progress, step_name=step_name)

            if progress_callback:
                progress_callback('progress', {'step': step_num, 'step_name': step_name, 'progress': progress})

            # 执行步骤
            try:
                module = __import__(f'steps.{step_function}', fromlist=[step_function])
                step_func = getattr(module, step_function)
                result = step_func(industry_name, TABLES)

                completed_steps.append(result)

            except Exception as e:
                error_msg = f"步骤{step_num}执行失败: {e}"
                update_status(industry_name, 'error', error_message=error_msg)
                if progress_callback:
                    progress_callback('error', error_msg)
                return {
                    'status': 'error',
                    'industry_name': industry_name,
                    'error': error_msg,
                    'completed_steps': completed_steps
                }

        # 完成
        update_status(industry_name, 'completed', current_step=10)
        if progress_callback:
            progress_callback('completed', '任务完成')

        return {
            'status': 'completed',
            'industry_name': industry_name,
            'completed_steps': completed_steps
        }

    except Exception as e:
        error_msg = f"Pipeline执行失败: {e}"
        update_status(industry_name, 'error', error_message=error_msg)
        if progress_callback:
            progress_callback('error', error_msg)
        return {'status': 'error', 'industry_name': industry_name, 'error': error_msg}


def submit_pipeline(industry_name: str, start_step: int = 2,
                   progress_callback: Optional[Callable] = None) -> str:
    """提交pipeline任务到后台执行

    Returns:
        任务ID（使用industry_name）
    """
    logger.info(f"[Pipeline Executor] 提交任务: {industry_name}, start_step={start_step}")

    # 初始化状态
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pipeline_task_status
            (industry_name, status, current_step, progress)
            VALUES (%s, 'running', 0, 0)
            ON DUPLICATE KEY UPDATE
            status = 'running',
            current_step = 0,
            progress = 0,
            started_at = NOW(),
            completed_at = NULL,
            cancelled_at = NULL,
            error_message = NULL
        """, (industry_name,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"初始化状态失败: {e}")

    # 提交到��程池
    future = _executor.submit(run_pipeline_sync, industry_name, start_step, progress_callback)
    logger.info(f"[Pipeline Executor] 任务已提交到线程池: {industry_name}")

    # 记录任务
    with _lock:
        _running_tasks[industry_name] = {
            'future': future,
            'started_at': datetime.now()
        }

    return industry_name


def cancel_pipeline(industry_name: str) -> bool:
    """取消pipeline任务"""
    # 设置取消标志
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE pipeline_task_status SET cancelled_at = NOW() WHERE industry_name = %s",
            (industry_name,)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except:
        pass

    # 从运行列表中移除
    with _lock:
        if industry_name in _running_tasks:
            # 尝试取消Future（已启动的任务无法取消）
            future = _running_tasks[industry_name]['future']
            future.cancel()
            del _running_tasks[industry_name]

    return True


def get_task_status(industry_name: str) -> Dict[str, Any]:
    """获取任务状态"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT industry_name, status, current_step, current_step_name,
                   progress, error_message, started_at, completed_at, cancelled_at, updated_at
            FROM pipeline_task_status
            WHERE industry_name = %s
        """, (industry_name,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return {
                'industry_name': result[0],
                'status': result[1],
                'current_step': result[2],
                'current_step_name': result[3],
                'progress': result[4],
                'error_message': result[5],
                'started_at': result[6].isoformat() if result[6] else None,
                'completed_at': result[7].isoformat() if result[7] else None,
                'cancelled_at': result[8].isoformat() if result[8] else None,
                'updated_at': result[9].isoformat() if result[9] else None,
            }
    except Exception as e:
        pass

    return {'error': '任务不存在'}


def reset_task(industry_name: str) -> bool:
    """重置任务状态为idle"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE pipeline_task_status
            SET status = 'idle', current_step = 0, progress = 0,
                cancelled_at = NULL, error_message = NULL
            WHERE industry_name = %s
        """, (industry_name,))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except:
        return False


def is_running(industry_name: str) -> bool:
    """检查任务是否正在运行"""
    with _lock:
        task_info = _running_tasks.get(industry_name)
        if task_info:
            future = task_info['future']
            if future.done():
                # 任务已完成，从列表移除
                del _running_tasks[industry_name]
                return False
            return True
        return False
