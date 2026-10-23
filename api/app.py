"""
产业链自动化处理 API

功能：
1. 接收产业链名称参数
2. 自动执行步骤2-10
3. 实时推送进度
4. 返回处理结果
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import json
import asyncio
import uuid
from datetime import datetime

# 导入主流程模块
from auto_industry_chain_pipeline import (
    TABLES, STEPS, DB_CONFIG,
    ensure_tables_exist, load_whitelist_data
)

# 导入步骤模块
from steps.step2_generate_definition import step2_generate_definition
from steps.step3_match_industry import step3_match_industry
from steps.step4_company_match_nodes import step4_company_match_nodes
from steps.step5_search_top_companies import step5_search_top_companies
from steps.step6_top_company_match import step6_top_company_match
from steps.step7_split_results import step7_split_results
from steps.step8_merge_and_clean import step8_merge_and_clean
from steps.step9_export_finallist import step9_export_finallist
from steps.step10_export_online_tables import step10_export_online_tables

# ==================== FastAPI 应用 ====================
app = FastAPI(
    title="产业链自动化处理 API",
    description="自动执行产业链处理流程（步骤2-10），实时推送进度",
    version="1.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 数据模型 ====================
class ProcessRequest(BaseModel):
    industry_name: str
    """产业链名称，必须与数据库中的 chain_name 完全匹配"""

class ProcessResponse(BaseModel):
    task_id: str
    message: str

class TaskStatus(BaseModel):
    task_id: str
    status: str
    current_step: Optional[int] = None
    total_steps: int = 9
    completed_steps: List[dict] = []
    error: Optional[str] = None
    result: Optional[dict] = None

# ==================== 任务管理 ====================
class TaskManager:
    def __init__(self):
        self.active_tasks = {}
        self.task_results = {}
        self.websocket_connections = {}

    def create_task(self, industry_name: str) -> str:
        task_id = str(uuid.uuid4())
        self.active_tasks[task_id] = {
            'industry_name': industry_name,
            'status': 'pending',
            'current_step': 0,
            'completed_steps': [],
            'created_at': datetime.now().isoformat()
        }
        return task_id

    def update_task(self, task_id: str, **kwargs):
        if task_id in self.active_tasks:
            self.active_tasks[task_id].update(kwargs)

    def complete_task(self, task_id: str, result: dict):
        if task_id in self.active_tasks:
            self.active_tasks[task_id]['status'] = 'completed'
            self.active_tasks[task_id]['completed_at'] = datetime.now().isoformat()
            self.task_results[task_id] = result

    def fail_task(self, task_id: str, error: str):
        if task_id in self.active_tasks:
            self.active_tasks[task_id]['status'] = 'failed'
            self.active_tasks[task_id]['error'] = error
            self.active_tasks[task_id]['failed_at'] = datetime.now().isoformat()

    def get_task(self, task_id: str) -> Optional[dict]:
        return self.active_tasks.get(task_id)

    async def broadcast(self, task_id: str, message: dict):
        if task_id in self.websocket_connections:
            disconnected = []
            for websocket in self.websocket_connections[task_id]:
                try:
                    await websocket.send_json(message)
                except:
                    disconnected.append(websocket)
            for ws in disconnected:
                self.websocket_connections[task_id].remove(ws)

task_manager = TaskManager()

# ==================== 步骤执行函数映射 ====================
STEP_FUNCTIONS = {
    2: step2_generate_definition,
    3: step3_match_industry,
    4: step4_company_match_nodes,
    5: step5_search_top_companies,
    6: step6_top_company_match,
    7: step7_split_results,
    8: step8_merge_and_clean,
    9: step9_export_finallist,
    10: step10_export_online_tables,
}

# ==================== 后台任务执行 ====================
async def execute_pipeline(task_id: str, industry_name: str):
    """执行产业链处理流程"""
    try:
        await task_manager.broadcast(task_id, {
            'type': 'status',
            'message': f'开始处理产业链: {industry_name}',
            'status': 'running'
        })

        # 确保表存在
        await task_manager.broadcast(task_id, {
            'type': 'progress',
            'message': '检查并创建数据库表...',
            'step': 0,
            'step_name': '准备环境'
        })
        ensure_tables_exist()

        results = []

        for step_info in STEPS:
            step_num = step_info['step']
            step_name = step_info['name']
            step_function_name = step_info['function']

            task_manager.update_task(task_id, current_step=step_num)

            await task_manager.broadcast(task_id, {
                'type': 'progress',
                'message': f'开始执行步骤{step_num}: {step_name}',
                'step': step_num,
                'step_name': step_name
            })

            try:
                # 加载白名单数据（如果需要）
                whitelist_data = None
                if step_info.get('need_whitelist', False):
                    whitelist_data = load_whitelist_data()

                # 执行步骤函数
                step_func = STEP_FUNCTIONS.get(step_num)
                if step_func:
                    # 使用同步执行，因为步骤函数是同步的
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,
                        step_func,
                        industry_name,
                        TABLES,
                        whitelist_data
                    )

                    results.append({
                        'step': step_num,
                        'name': step_name,
                        'status': 'completed',
                        'result': result
                    })

                    task_manager.update_task(
                        task_id,
                        completed_steps=task_manager.get_task(task_id)['completed_steps'] + [{
                            'step': step_num,
                            'name': step_name,
                            'status': 'completed'
                        }]
                    )

                    await task_manager.broadcast(task_id, {
                        'type': 'step_completed',
                        'message': f'步骤{step_num}完成: {step_name}',
                        'step': step_num,
                        'step_name': step_name,
                        'result': result
                    })
                else:
                    raise Exception(f"步骤{step_num}函数未找到")

            except Exception as e:
                error_msg = f"步骤{step_num}失败: {str(e)}"
                await task_manager.broadcast(task_id, {
                    'type': 'error',
                    'message': error_msg,
                    'step': step_num,
                    'step_name': step_name
                })
                task_manager.fail_task(task_id, error_msg)
                return

        # 完成
        final_result = {
            'industry_name': industry_name,
            'status': 'completed',
            'total_steps': len(STEPS),
            'completed': len(results),
            'results': results
        }

        task_manager.complete_task(task_id, final_result)

        await task_manager.broadcast(task_id, {
            'type': 'completed',
            'message': f'产业链 {industry_name} 处理完成！',
            'result': final_result
        })

    except Exception as e:
        error_msg = f"流程执行失败: {str(e)}"
        await task_manager.broadcast(task_id, {
            'type': 'error',
            'message': error_msg
        })
        task_manager.fail_task(task_id, error_msg)

# ==================== API 端点 ====================
@app.get("/")
async def root():
    """API 根路径"""
    return {
        "message": "产业链自动化处理 API",
        "version": "1.0.0",
        "endpoints": {
            "POST /api/process": "启动产业链处理流程",
            "GET /api/task/{task_id}": "查询任务状态",
            "WebSocket /ws/{task_id}": "实时进度推送"
        }
    }

@app.get("/api/industries")
async def get_industries():
    """获取所有可用的产业链列表"""
    import pymysql
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT chain_name FROM chain_needcomp ORDER BY chain_name")
        industries = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return {"industries": industries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/industry/{industry_name}/info")
async def get_industry_info(industry_name: str):
    """获取产业链信息"""
    import pymysql
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # 检查产业链是否存在
        cursor.execute(
            "SELECT COUNT(*) FROM chain_needcomp WHERE chain_name = %s",
            (industry_name,)
        )
        count = cursor.fetchone()[0]

        if count == 0:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=404, detail=f"产业链 '{industry_name}' 不存在")

        # 获取节点数量
        cursor.execute(
            "SELECT COUNT(*) FROM chain_needcomp WHERE chain_name = %s",
            (industry_name,)
        )
        node_count = cursor.fetchone()[0]

        # 检查是否有白名单
        cursor.execute(
            "SELECT COUNT(*) FROM whitelist_company WHERE industry_name = %s",
            (industry_name,)
        )
        whitelist_count = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return {
            "industry_name": industry_name,
            "exists": True,
            "node_count": node_count,
            "whitelist_count": whitelist_count,
            "steps": len(STEPS)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/process", response_model=ProcessResponse)
async def start_process(request: ProcessRequest, background_tasks: BackgroundTasks):
    """启动产业链处理流程"""
    industry_name = request.industry_name.strip()

    # 验证产业链是否存在
    import pymysql
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM chain_needcomp WHERE chain_name = %s",
        (industry_name,)
    )
    count = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    if count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"产业链 '{industry_name}' 不存在，请检查名称是否正确"
        )

    # 创建任务
    task_id = task_manager.create_task(industry_name)

    # 启动后台任务
    asyncio.create_task(execute_pipeline(task_id, industry_name))

    return ProcessResponse(
        task_id=task_id,
        message=f"产业链 '{industry_name}' 处理已启动"
    )

@app.get("/api/task/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """查询任务状态"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return TaskStatus(
        task_id=task_id,
        status=task.get('status', 'unknown'),
        current_step=task.get('current_step'),
        total_steps=len(STEPS),
        completed_steps=task.get('completed_steps', []),
        error=task.get('error'),
        result=task_manager.task_results.get(task_id)
    )

@app.get("/api/task/{task_id}/result")
async def get_task_result(task_id: str):
    """获取任务结果"""
    result = task_manager.task_results.get(task_id)
    if not result:
        task = task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.get('status') != 'completed':
            raise HTTPException(status_code=400, detail="任务尚未完成")
    return result

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket 实时进度推送"""
    await websocket.accept()

    task = task_manager.get_task(task_id)
    if not task:
        await websocket.send_json({
            'type': 'error',
            'message': f"任务 {task_id} 不存在"
        })
        await websocket.close()
        return

    # 添加到连接列表
    if task_id not in task_manager.websocket_connections:
        task_manager.websocket_connections[task_id] = []
    task_manager.websocket_connections[task_id].append(websocket)

    try:
        # 发送当前状态
        await websocket.send_json({
            'type': 'connected',
            'message': f"已连接到任务 {task_id}",
            'task': task
        })

        # 保持连接，接收心跳
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        if task_id in task_manager.websocket_connections:
            task_manager.websocket_connections[task_id].remove(websocket)
    except Exception as e:
        if task_id in task_manager.websocket_connections:
            task_manager.websocket_connections[task_id].remove(websocket)

# ==================== 启动脚本 ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
