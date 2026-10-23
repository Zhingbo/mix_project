"""
Pipeline Celery任务

将产业链分析pipeline改造为Celery异步任务
"""

import os
from celery import Task
from celery.utils.log import get_task_logger
import pymysql
import asyncio
from datetime import datetime
from typing import Dict, Any, List

from celery_app import app

logger = get_task_logger(__name__)

# 步骤配置（与pipeline_routes.py保持一致）
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

# 表名配置
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
    'company_nodes_top': 'business_data.company_nodes_top',
}

# 数据库配置
DB_CONFIG = {
    'host': '8.141.5.67',
    'user': 'root',
    'password': os.getenv('DB_PASSWORD'),
    'database': 'business_data',
    'charset': 'utf8mb4',
}


class PipelineTask(Task):
    """Pipeline任务基类，支持状态更新"""

    def update_task_status(self, industry_name: str, status: str, current_step: int = 0,
                          progress: int = 0, error_message: str = None):
        """更新任务状态到数据库"""
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()

        if status == 'running':
            sql = """
                UPDATE pipeline_task_status
                SET status = %s, current_step = %s, progress = %s, updated_at = NOW()
                WHERE industry_name = %s
            """
            cursor.execute(sql, (status, current_step, progress, industry_name))
        elif status == 'completed':
            sql = """
                UPDATE pipeline_task_status
                SET status = %s, current_step = %s, progress = 100, completed_at = NOW(), updated_at = NOW()
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
        elif status == 'cancelled':
            sql = """
                UPDATE pipeline_task_status
                SET status = %s, cancelled_at = NOW(), updated_at = NOW()
                WHERE industry_name = %s
            """
            cursor.execute(sql, (status, industry_name))

        conn.commit()
        cursor.close()
        conn.close()

    def is_task_cancelled(self, industry_name: str) -> bool:
        """检查任务是否被取消"""
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

    def is_task_paused(self, industry_name: str) -> bool:
        """检查任务是否被暂停"""
        try:
            import redis
            r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            paused = r.get(f"pipeline_pause:{industry_name}")
            return paused == "1"
        except:
            return False

    def wait_if_paused(self, industry_name: str, timeout=60):
        """如果任务被暂停，等待恢复"""
        import time
        waited = 0
        while self.is_task_paused(industry_name):
            if waited >= timeout:
                break
            time.sleep(1)
            waited += 1
            # 检查是否被取消
            if self.is_task_cancelled(industry_name):
                raise Exception("任务已取消")


@app.task(base=PipelineTask, bind=True, name='tasks.pipeline_tasks.run_pipeline_task')
def run_pipeline_task(self, industry_name: str, start_step: int = 2) -> Dict[str, Any]:
    """
    执行产业链分析pipeline任务

    Args:
        industry_name: 产业链名称
        start_step: 开始步骤

    Returns:
        执行结果字典
    """
    # 初始化任务状态
    self.update_task_status(industry_name, 'running', current_step=0, progress=0)

    try:
        logger.info(f"开始执行产业链分析: {industry_name}, 从步骤{start_step}开始")

        # 执行步骤
        completed_steps = []
        for step_info in STEPS:
            step_num = step_info['step']
            step_name = step_info['name']
            step_function = step_info['function']

            # 跳过开始步骤之前的步骤
            if step_num < start_step:
                continue

            # 检查是否被取消
            if self.is_task_cancelled(industry_name):
                logger.info(f"任务已取消: {industry_name}")
                self.update_task_status(industry_name, 'cancelled')
                return {'status': 'cancelled', 'industry_name': industry_name}

            # 检查是否被暂停
            self.wait_if_paused(industry_name)

            # 更新状态：步骤开始
            progress = int((step_num - 2) / (10 - 2) * 100)
            self.update_task_status(industry_name, 'running', current_step=step_num, progress=progress)

            # 更新Celery状态
            self.update_state(
                state='PROGRESS',
                meta={
                    'current_step': step_num,
                    'step_name': step_name,
                    'progress': progress,
                    'industry_name': industry_name
                }
            )

            logger.info(f"执行步骤{step_num}: {step_name}")

            # 动态导入并执行步骤函数
            try:
                module = __import__(f'steps.{step_function}', fromlist=[step_function])
                step_func = getattr(module, step_function)

                # 执行步骤（同步函数）
                result = step_func(industry_name, TABLES)

                logger.info(f"步骤{step_num}完成: {result}")
                completed_steps.append(result)

            except Exception as e:
                logger.error(f"步骤{step_num}执行失败: {e}")
                # 步骤失败，记录但继续执行
                completed_steps.append({
                    'step': step_num,
                    'name': step_name,
                    'status': 'error',
                    'error': str(e)
                })

        # 所有步骤完成
        self.update_task_status(industry_name, 'completed', current_step=10, progress=100)

        logger.info(f"产业链分析完成: {industry_name}")

        return {
            'status': 'completed',
            'industry_name': industry_name,
            'completed_steps': completed_steps
        }

    except Exception as e:
        logger.error(f"Pipeline执行失败: {e}")
        self.update_task_status(industry_name, 'error', error_message=str(e))
        raise


@app.task(name='tasks.pipeline_tasks.cancel_pipeline_task')
def cancel_pipeline_task(industry_name: str) -> bool:
    """
    立即取消指定产业链的pipeline任务

    Args:
        industry_name: 产业链名称

    Returns:
        是否成功取消
    """
    import redis

    # 重置任务状态为idle，清除取消标志，允许立即重新执行
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE pipeline_task_status SET status = 'idle', cancelled_at = NULL WHERE industry_name = %s",
        (industry_name,)
    )
    conn.commit()
    cursor.close()
    conn.close()

    # 清理Redis中的暂停标志
    try:
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        r.delete(f"pipeline_pause:{industry_name}")
    except:
        pass

    logger.info(f"任务已停止并重置: {industry_name}")
    return True


@app.task(name='tasks.pipeline_tasks.pause_pipeline_task')
def pause_pipeline_task(industry_name: str) -> bool:
    """
    暂停pipeline任务

    Args:
        industry_name: 产业链名称

    Returns:
        是否成功暂停
    """
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        r.set(f"pipeline_pause:{industry_name}", "1")
        logger.info(f"任务暂停: {industry_name}")
        return True
    except Exception as e:
        logger.error(f"暂停任务失败: {e}")
        return False


@app.task(name='tasks.pipeline_tasks.resume_pipeline_task')
def resume_pipeline_task(industry_name: str) -> bool:
    """
    恢复pipeline任务

    Args:
        industry_name: 产业链名称

    Returns:
        是否成功恢复
    """
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        r.delete(f"pipeline_pause:{industry_name}")
        logger.info(f"任务恢复: {industry_name}")
        return True
    except Exception as e:
        logger.error(f"恢复任务失败: {e}")
        return False


@app.task(name='tasks.pipeline_tasks.get_task_status')
def get_task_status(industry_name: str = None, task_id: str = None) -> Dict[str, Any]:
    """
    获取任务状态

    Args:
        industry_name: 产业链名称
        task_id: Celery任务ID

    Returns:
        任务状态信息
    """
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    if industry_name:
        cursor.execute(
            "SELECT * FROM pipeline_task_status WHERE industry_name = %s",
            (industry_name,)
        )
    elif task_id:
        cursor.execute(
            "SELECT * FROM pipeline_task_status WHERE task_id = %s",
            (task_id,)
        )
    else:
        cursor.close()
        conn.close()
        return {'error': '必须提供industry_name或task_id'}

    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if result:
        return {
            'id': result[0],
            'industry_name': result[1],
            'status': result[2],
            'current_step': result[3],
            'progress': result[4],
            'error_message': result[5],
            'started_at': result[6].isoformat() if result[6] else None,
            'completed_at': result[7].isoformat() if result[7] else None,
            'cancelled_at': result[8].isoformat() if result[8] else None,
            'updated_at': result[12].isoformat() if result[12] else None,
        }
    else:
        return {'error': '任务不存在'}
