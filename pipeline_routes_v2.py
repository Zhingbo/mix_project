"""
产业链自动化处理路由 V2

使用后台线程池执行pipeline，不依赖SSE连接
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
from pipeline_executor import (
    submit_pipeline,
    cancel_pipeline,
    get_task_status,
    reset_task,
    is_running
)
import pymysql

logger = get_logger(__name__)

pipeline_router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


def check_step_status(industry_name: str) -> dict:
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

    # 步骤2: 检查chain_needcomp
    cursor.execute("SELECT COUNT(*) FROM chain_needcomp WHERE chain_name = %s", (industry_name,))
    status[2] = cursor.fetchone()[0] > 0

    # 步骤3: 检查nodes_industry_mapping
    cursor.execute("SELECT COUNT(*) FROM nodes_industry_mapping WHERE industry_name = %s", (industry_name,))
    status[3] = cursor.fetchone()[0] > 0

    # 步骤4: 检查company_nodes_mapping
    cursor.execute("SELECT COUNT(*) FROM company_nodes_mapping WHERE industry_name = %s", (industry_name,))
    status[4] = cursor.fetchone()[0] > 0

    # 步骤5: 检查company_nodes_top
    cursor.execute("SELECT COUNT(*) FROM company_nodes_top WHERE industry_chain = %s", (industry_name,))
    status[5] = cursor.fetchone()[0] > 0

    # 步骤6: 检查company_nodes_info_result
    cursor.execute("SELECT COUNT(*) FROM company_nodes_info_result WHERE industry_name = %s", (industry_name,))
    status[6] = cursor.fetchone()[0] > 0

    # 步骤7: 检查company_nodes_info_split
    cursor.execute("SELECT COUNT(*) FROM company_nodes_info_split WHERE industry_name = %s", (industry_name,))
    status[7] = cursor.fetchone()[0] > 0

    # 步骤8: 检查company_nodes_final
    try:
        cursor.execute("SELECT COUNT(*) FROM company_nodes_final WHERE industry_name = %s", (industry_name,))
        status[8] = cursor.fetchone()[0] > 0
    except:
        status[8] = False

    # 步骤9: 检查company_nodes_finallist
    try:
        cursor.execute("SELECT COUNT(*) FROM company_nodes_finallist WHERE industry_name = %s", (industry_name,))
        status[9] = cursor.fetchone()[0] > 0
    except:
        status[9] = False

    # 步骤10: 检查company_list_output
    try:
        cursor.execute("SELECT COUNT(*) FROM company_list_output WHERE industry_name = %s", (industry_name,))
        status[10] = cursor.fetchone()[0] > 0
    except:
        status[10] = False

    cursor.close()
    conn.close()
    return status

# 全局任务跟踪（用于SSE连接）
running_tasks = {}


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

    # 验证产业链是否存在
    import pymysql
    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        charset='utf8mb4'
    )
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM industrial_chain.industrial_chain_structure WHERE chain_name = %s",
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
    cursor.execute(
        "SELECT nodes, parent_node, node_level FROM industrial_chain.industrial_chain_structure WHERE chain_name = %s",
        (industry_name,)
    )
    node_data = cursor.fetchall()
    cursor.close()
    conn.close()

    logger.info(f"从 industrial_chain_structure 查询到 {len(node_data)} 条节点数据")

    # 先同步数据到 chain_needcomp
    sync_conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data',
        charset='utf8mb4'
    )
    sync_cursor = sync_conn.cursor()
    sync_cursor.execute("DELETE FROM chain_needcomp WHERE chain_name = %s", (industry_name,))
    for nodes, parent_node, node_level in node_data:
        sync_cursor.execute(
            "INSERT INTO chain_needcomp (chain_name, nodes, parent_node, node_level) VALUES (%s, %s, %s, %s)",
            (industry_name, nodes, parent_node, node_level)
        )
    sync_conn.commit()
    sync_cursor.close()
    sync_conn.close()

    logger.info(f"启动后台任务: {industry_name}, start_step={start_step}")

    # 提交后台任务
    task_id = submit_pipeline(industry_name, start_step=start_step)
    logger.info(f"任务已提交: task_id={task_id}")

    # SSE事件生成器 - 仅用于推送实时更新，任务已在后台运行
    async def event_generator():
        last_status = None
        last_progress = -1
        check_count = 0
        max_checks = 7200  # 最多检查2小时

        # 发送初始消息
        yield f"data: {json.dumps({'type': 'start', 'content': '任务已提交，正在后台执行...'})}\n\n"

        while check_count < max_checks:
            try:
                # 从数据库查询任务状态
                status_info = get_task_status(industry_name)

                if 'error' not in status_info:
                    status = status_info['status']
                    step = status_info['current_step']
                    step_name = status_info['current_step_name']
                    progress = status_info['progress']
                    error = status_info['error_message']

                    # 状态变化时发送消息
                    if status != last_status or progress != last_progress:
                        yield f"data: {json.dumps({'type': 'progress', 'content': {
                            'step': step,
                            'step_name': step_name,
                            'progress': progress,
                            'status': status
                        }})}\n\n"
                        last_status = status
                        last_progress = progress

                    # 检查完成状态
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

    # 取消任务
    success = cancel_pipeline(industry_name)

    if success:
        logger.info(f"已取消任务: {industry_name}")
        return {"status": "success", "message": f"任务 {industry_name} 已取消"}
    else:
        raise HTTPException(status_code=500, detail="取消任务失败")


@pipeline_router.get("/status/{industry_name}")
async def get_status(industry_name: str, current_user: dict = Depends(get_current_user)):
    """
    获取任务状态

    返回任务的当前状态、进度等信息
    """
    status_info = get_task_status(industry_name)

    if 'error' in status_info:
        raise HTTPException(status_code=404, detail=status_info['error'])

    return {
        "status": "success",
        "data": status_info
    }


@pipeline_router.get("/industry/{industry_name}/step_status")
async def get_step_status(industry_name: str, current_user: dict = Depends(get_current_user)):
    """获取产业链各步骤的完成状态"""
    try:
        status = check_step_status(industry_name)

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
                "all_completed": next_step is None
            }
        }
    except Exception as e:
        logger.error(f"获取步骤状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pipeline_router.post("/reset")
async def reset_process(request: Request, current_user: dict = Depends(get_current_user)):
    """
    重置任务状态为idle（允许重新执行）

    请求体格式:
    {
        "industry_name": "产业链名称"
    }
    """
    data = await request.json()
    industry_name = data.get("industry_name", "").strip()

    if not industry_name:
        raise HTTPException(status_code=400, detail="缺少 industry_name 参数")

    success = reset_task(industry_name)

    if success:
        logger.info(f"已重置任务状态: {industry_name}")
        return {"status": "success", "message": f"任务 {industry_name} 状态已重置"}
    else:
        raise HTTPException(status_code=500, detail="重置任务状态失败")


@pipeline_router.get("/running")
async def get_running_tasks(current_user: dict = Depends(get_current_user)):
    """
    获取所有正在运行的任务列表
    """
    import pymysql
    conn = pymysql.connect(
        host='8.141.5.67',
        user='root',
        password=os.getenv('DB_PASSWORD'),
        database='business_data',
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    cursor.execute("""
        SELECT industry_name, status, current_step, progress, started_at
        FROM pipeline_task_status
        WHERE status = 'running'
        ORDER BY started_at DESC
    """)
    results = cursor.fetchall()
    cursor.close()
    conn.close()

    tasks = []
    for row in results:
        tasks.append({
            'industry_name': row[0],
            'status': row[1],
            'current_step': row[2],
            'progress': row[3],
            'started_at': row[4].isoformat() if row[4] else None
        })

    return {
        "status": "success",
        "data": tasks,
        "count": len(tasks)
    }
