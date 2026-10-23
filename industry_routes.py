from fastapi import APIRouter, Request, Depends, HTTPException, Body, Query, UploadFile, File, Form
from starlette.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor, Future
import functools
import multiprocessing
import os
import re
from typing import Dict, Any, List
import pymysql
import pandas as pd
from datetime import datetime, timedelta

from services.industry_service import process_industry, process_industry_with_historical
from services.industry_service import process_input_industry
from services.industry_storage_service import IndustryStorageService
from services.hotspot_service import HotspotService
from services.industry_status_service import IndustryStatusService
from services.industry_structure_service import IndustryStructureService
from auth_routes import get_current_user
from utils.logger import get_logger
import yaml

with open("config/settings_show2.yaml", "r") as file:
    settings = yaml.load(file, Loader=yaml.FullLoader)

input_clean_prompts = settings['prompts']['input_clean']['content']
input_clean_post_prompts = settings['prompts']['input_clean_post']['content']

# 获取日志记录器
logger = get_logger(__name__)

# 优化线程池配置 - 参考旧版设计，平衡性能和资源
max_workers = 150  # 恢复旧版的高并发配置，提升处理效率

logger.info(f"初始化线程池，使用 {max_workers} 个工作线程")

# 创建一个线程池执行器
executor = ThreadPoolExecutor(max_workers=max_workers)

# 创建一个字典来跟踪正在进行的任务
# 格式: {industry_name: {"future": future对象, "queue": 消息队列, "user_id": 用户ID}}
active_tasks = {}

industrial_router = APIRouter(prefix="/api/industrial", tags=["industrial"])

@industrial_router.post("/process_stream_enhanced")
async def process_stream_enhanced_api(request: Request, current_user: dict = Depends(get_current_user)):
    """
    增强版产业链分析API - 支持历史报告分析，需要用户认证
    
    请求参数:
    {
        "industry_name": "产业名称",
        "custom_urls": ["自定义URL列表"],
        "sites": ["搜索站点列表"],
        "historical_config": {
            "enable": true,
            "report_path": "历史报告文件路径",
            "reference_files": ["参考文件路径列表"]
        }
    }
    """
    # 解析请求数据
    data = await request.json()
    industry_name = data.get("industry_name", "")
    
    # 工业机器人默认历史配置
    default_robot_config = None
    if "工业机器人" in industry_name or "机器人" in industry_name:
        default_robot_config = {
            "enable": True,
            "report_path": "/root/mix_project/historical_data/工业机器人产业相关资料/联东产业研究院-工业机器人研究.pdf",
            "reference_files": [
                "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人数据合集2023.xlsx",
                "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人（修改）-2022-4-9.xlsx",
                "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人产业机会和瓶颈分析-2024.xlsx",
                "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人企业数据汇总-2022-4-1.xlsx",
                "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/2024年机器人产业新增目录企业初步名单.20241111.xlsx"
            ]
        }
    
    # 处理历史报告配置
    if "historical_config" not in data or data["historical_config"] is None:
        if default_robot_config:
            # 对于工业机器人产业，使用默认配置
            data["historical_config"] = default_robot_config
            logger.info(f"为{industry_name}产业自动应用默认历史分析配置")
        else:
            raise HTTPException(status_code=400, detail="historical_config is required for enhanced API")
    
    # 确保启用历史报告分析
    data["historical_config"]["enable"] = True
    
    # 验证历史报告配置
    historical_config = data["historical_config"]
    if not historical_config.get("report_path"):
        if default_robot_config:
            # 补充默认路径
            historical_config.update(default_robot_config)
            logger.info(f"为{industry_name}产业补充默认历史报告路径")
        else:
            raise HTTPException(status_code=400, detail="historical_config.report_path is required")
    
    # 重新构造请求对象
    import io
    import json as json_lib
    modified_body = json_lib.dumps(data).encode('utf-8')
    
    # 创建新的请求对象
    class ModifiedRequest:
        def __init__(self, original_request, new_body):
            self._original = original_request
            self._body = new_body
            self.headers = original_request.headers
            self.method = original_request.method
            self.url = original_request.url
            
        async def json(self):
            return json_lib.loads(self._body.decode('utf-8'))
            
        def __getattr__(self, name):
            return getattr(self._original, name)
    
    modified_request = ModifiedRequest(request, modified_body)
    
    # 调用增强版处理逻辑
    return await process_stream_with_historical_internal(modified_request, current_user)

async def process_stream_with_historical_internal(request: Request, current_user: dict):
    """内部增强版处理函数"""
    data = await request.json()
    industry_name = data.get("industry_name")
    custom_urls = data.get("custom_urls")
    sites = data.get("sites")
    historical_config = data.get("historical_config")
    
    if not industry_name:
        raise HTTPException(status_code=400, detail="Missing industry_name")
    
    # 使用当前登录用户的ID
    user_id = str(current_user["user_id"])
    oa_user_id = current_user.get("oa_user_id") or current_user.get("username")

    # 检查是否已经有同名任务在运行
    if industry_name in active_tasks:
        active_task = active_tasks[industry_name]
        if active_task["user_id"] == user_id and not active_task["future"].done():
            raise HTTPException(status_code=400, detail=f"产业链 '{industry_name}' 的分析任务已在进行中")

    async def event_generator():
        queue = asyncio.Queue()
        cancel_flag = asyncio.Event()

        async def send_message(message, message_type):
            if cancel_flag.is_set():
                return
            await queue.put(json.dumps({"type": message_type, "content": message}))

        async def run_process_industry_async():
            try:
                # 使用历史报告分析
                await process_industry_with_historical(
                    industry_name, custom_urls=custom_urls, user_id=user_id,
                    send_message=send_message, sites=sites, cancel_flag=cancel_flag,
                    historical_config=historical_config, oa_user_id=oa_user_id
                )
            except asyncio.CancelledError:
                logger.info(f"协程任务被取消: {industry_name}")
                await send_message("任务已取消", "End")
                raise
            except Exception as e:
                logger.error(f"任务执行出错: {e}")
                await send_message(f"任务执行出错: {str(e)}", "Error")
                raise

        # 启动协程任务
        future = asyncio.create_task(run_process_industry_async())
        
        # 将任务信息存储在全局字典中
        active_tasks[industry_name] = {
            "future": future,
            "queue": queue,
            "user_id": user_id,
            "cancel_flag": cancel_flag
        }

        try:
            # 定义心跳消息 - 恢复旧版的10秒间隔和heartbeat内容
            heartbeat_message = json.dumps({"type": "heartbeat", "content": "heartbeat"})
            
            # 定时发送心跳消息 - 恢复旧版的逻辑
            async def send_heartbeat():
                while not cancel_flag.is_set():
                    await asyncio.sleep(10)  # 每10秒发送一次心跳
                    await queue.put(heartbeat_message)
            
            # 启动心跳任务
            heartbeat_task = asyncio.create_task(send_heartbeat())
            
            # 使用旧版的消息处理逻辑
            while True:
                try:
                    # 检查任务是否已被取消
                    if cancel_flag.is_set():
                        # 发送取消消息并退出
                        yield f"type: End\ndata: 任务已被取消\n\n"
                        break
                    
                    # 等待消息，但设置超时以便定期检查取消标志
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # 超时，检查取消标志
                        if cancel_flag.is_set():
                            yield f"type: End\ndata: 任务已被取消\n\n"
                            break
                        continue
                    
                    if message is None:
                        break
                        
                    # 解析 JSON 格式的消息
                    message_data = json.loads(message)
                    message_type = message_data["type"]
                    message_content = message_data["content"]
                    
                    # 使用旧版的消息处理逻辑
                    if message_type == "2" and isinstance(message_content, str):
                        logger.debug(f"原始思维链消息格式: {message_content}")
                    
                    if message_type == "3" and isinstance(message_content, str):
                        if message_content.startswith("结果:"):
                            prefix = "结果:"
                            content = message_content[len(prefix):]
                            content = content.replace("data:", "").strip()
                            message_content = f"{prefix}{content}"
                    
                    if message_type == "End":
                        yield f"type: {message_type}\ndata: {message_content}\n\n"
                        break
                    
                    if message_type == "heartbeat":
                        yield f"data: {message_content}\n\n"
                    elif message_type == "2" and message_content.startswith("思维链:data:"):
                        header_line = f"type: {message_type}\n"
                        
                        content = message_content[len("思维链:data:"):]
                        
                        lines = content.splitlines()
                        
                        response_lines = [header_line]
                        
                        # 处理每一行，确保每行前面有"data:"
                        for line in lines:
                            if line.strip():
                                if not line.strip().startswith("data:"):
                                    response_lines.append(f"data: {line.strip()}\n")
                                else:
                                    response_lines.append(f"{line.strip()}\n")
                        
                        response_lines.append("\n")
                        
                        sse_data = "".join(response_lines)
                        logger.debug("生成的思维链SSE数据: " + sse_data.replace('\n', '\\n'))
                        yield sse_data
                    else:
                        # 其他类型消息使用标准格式
                        sse_data = f"type: {message_type}\ndata: {message_content}\n\n"
                        logger.debug("生成的标准SSE数据: " + sse_data.replace('\n', '\\n'))
                        yield sse_data
                except Exception as e:
                    error_message = f"处理消息时出错: {str(e)}"
                    yield f"type: Error\ndata: {error_message}\n\n"
                    break
        finally:
            # 任务完成或发生错误时，从活动任务字典中移除
            if industry_name in active_tasks:
                del active_tasks[industry_name]
            # 取消心跳任务
            heartbeat_task.cancel()

    return EventSourceResponse(event_generator())

@industrial_router.post("/process_stream")
async def process_stream_api(request: Request, current_user: dict = Depends(get_current_user)):
    """
    标准产业链分析API - 需要用户认证
    """
    data = await request.json()
    industry_name = data.get("industry_name")
    custom_urls = data.get("custom_urls")
    sites = data.get("sites")
    historical_config = data.get("historical_config")
    
    # 工业机器人默认历史配置
    if industry_name and ("工业机器人" in industry_name or "机器人" in industry_name):
        default_robot_config = {
            "enable": True,
            "report_path": "/root/mix_project/historical_data/工业机器人产业相关资料/联东产业研究院-工业机器人研究.pdf",
            "reference_files": [
                "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人数据合集2023.xlsx",
                "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人（修改）-2022-4-9.xlsx",
                "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人产业机会和瓶颈分析-2024.xlsx",
                "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/机器人企业数据汇总-2022-4-1.xlsx",
                "/root/mix_project/historical_data/工业机器人产业相关资料/2025_09_09_机器人（修改）-2022-4-9/2024年机器人产业新增目录企业初步名单.20241111.xlsx"
            ]
        }
        
        # 如果没有提供历史配置，使用默认配置
        if not historical_config:
            historical_config = default_robot_config
            logger.info(f"为{industry_name}产业自动应用默认历史分析配置")
        # 如果提供了配置但没有指定路径，补充默认路径
        elif not historical_config.get("report_path"):
            historical_config.update(default_robot_config)
            logger.info(f"为{industry_name}产业补充默认历史报告路径")
    
    if not industry_name:
        raise HTTPException(status_code=400, detail="Missing industry_name")
    
    # 使用当前登录用户的ID
    user_id = str(current_user["user_id"])
    oa_user_id = current_user.get("oa_user_id") or current_user.get("username")

    # 在启动新任务前，将旧的节点文章链接标记为无效
    conn = None
    try:
        from database.industrial_chain.connection import get_connection
        
        conn = await get_connection()
        cursor = conn.cursor()
        
        # 更新node_article_links表中的记录状态为无效
        update_query = """
        UPDATE node_article_links 
        SET status = 0, created_at = CURRENT_TIMESTAMP
        WHERE chain_name = %s AND status = 1
        """
        cursor.execute(update_query, (industry_name,))
        affected_rows = cursor.rowcount
        conn.commit()
        
        logger.info(f"已将产业链 {industry_name} 的 {affected_rows} 条文章链接记录标记为无效")
    except Exception as e:
        logger.error(f"更新node_article_links表记录状态失败: {e}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        if conn and conn.open:
            conn.rollback()
    finally:
        if conn and conn.open:
            conn.close()

    # 检查是否已经有同名任务在运行
    if industry_name in active_tasks:
        active_task = active_tasks[industry_name]
        if active_task["user_id"] == user_id and not active_task["future"].done():
                raise HTTPException(status_code=400, detail=f"产业链 '{industry_name}' 的分析任务已在进行中")

    async def event_generator():
        queue = asyncio.Queue()
        cancel_flag = asyncio.Event()

        async def send_message(message, message_type):
            if cancel_flag.is_set():
                return
            await queue.put(json.dumps({"type": message_type, "content": message}))

        # 使用线程池运行耗时的process_industry函数，避免阻塞事件循环
        def run_process_industry():
            # 创建一个新的事件循环用于线程内部
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # 运行异步函数 - 标准接口不传递historical_config参数
                return loop.run_until_complete(
                    process_industry(industry_name, custom_urls=custom_urls, user_id=user_id, send_message=send_message, sites=sites, cancel_flag=cancel_flag, oa_user_id=oa_user_id)
                )
            finally:
                loop.close()

        # 启动任务并保存Future对象
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(executor, run_process_industry)
        
        # 将任务信息存储在全局字典中
        active_tasks[industry_name] = {
            "future": future,
            "queue": queue,
            "user_id": user_id,
            "cancel_flag": cancel_flag
        }

        try:
            # 定义心跳消息
            heartbeat_message = json.dumps({"type": "heartbeat", "content": "heartbeat"})

            # 定时发送心跳消息
            async def send_heartbeat():
                while not cancel_flag.is_set():
                    await asyncio.sleep(10)  # 每10秒发送一次心跳
                    await queue.put(heartbeat_message)

            # 启动心跳任务
            heartbeat_task = asyncio.create_task(send_heartbeat())

            while True:
                try:
                    # 检查任务是否已被取消
                    if cancel_flag.is_set():
                        # 发送取消消息并退出
                        yield f"type: End\ndata: 任务已被取消\n\n"
                        break
                    
                    # 等待消息，但设置超时以便定期检查取消标志
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # 超时，检查取消标志
                        if cancel_flag.is_set():
                            yield f"type: End\ndata: 任务已被取消\n\n"
                            break
                        continue
                    
                    if message is None:
                        break
                        
                    # 解析 JSON 格式的消息
                    message_data = json.loads(message)
                    message_type = message_data["type"]
                    message_content = message_data["content"]
                    
                    if message_type == "2" and isinstance(message_content, str):
                        logger.debug(f"原始思维链消息格式: {message_content}")
                    
                    if message_type == "3" and isinstance(message_content, str):
                        if message_content.startswith("结果:"):
                            prefix = "结果:"
                            content = message_content[len(prefix):]
                            content = content.replace("data:", "").strip()
                            message_content = f"{prefix}{content}"
                    
                    if message_type == "End":
                        yield f"type: {message_type}\ndata: {message_content}\n\n"
                        break
                    
                    if message_type == "heartbeat":
                        yield f"data: {message_content}\n\n"
                    elif message_type == "2" and message_content.startswith("思维链:data:"):
                        header_line = f"type: {message_type}\n"
                        
                        content = message_content[len("思维链:data:"):]
                        
                        lines = content.splitlines()
                        
                        response_lines = [header_line]
                        
                        # 处理每一行，确保每行前面有"data:"
                        for line in lines:
                            if line.strip():
                                if not line.strip().startswith("data:"):
                                    response_lines.append(f"data: {line.strip()}\n")
                                else:
                                    response_lines.append(f"{line.strip()}\n")
                        
                        response_lines.append("\n")
                        
                        sse_data = "".join(response_lines)
                        logger.debug("生成的思维链SSE数据: " + sse_data.replace('\n', '\\n'))
                        yield sse_data
                    else:
                        # 其他类型消息使用标准格式
                        sse_data = f"type: {message_type}\ndata: {message_content}\n\n"
                        logger.debug("生成的标准SSE数据: " + sse_data.replace('\n', '\\n'))
                        yield sse_data
                except Exception as e:
                    error_message = f"处理消息时出错: {str(e)}"
                    yield f"type: Error\ndata: {error_message}\n\n"
                    break
        finally:
            # 任务完成或发生错误时，从活动任务字典中移除
            if industry_name in active_tasks:
                del active_tasks[industry_name]
            # 取消心跳任务
            heartbeat_task.cancel()

    return EventSourceResponse(event_generator())

@industrial_router.post("/store_structure")
async def store_structure_api(
    data: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """
    存储产业链结构数据API - 接收用户传递的三元组数据
    
    请求体格式:
    {
        "industry_name": "产业链名称",
        "nodes": ["节点1", "节点2", ...],
        "relations": ["节点1-1,节点2-2,is-a", "节点3-3,节点4-4,part-of", ...]
    }
    
    Args:
        data: 包含产业链名称、节点和关系的字典
        current_user: 当前登录用户
        
    Returns:
        存储结果状态
    """
    try:
        # 验证请求数据
        industry_name = (data.get("industry_name") or "").strip()
        original_industry_name = (data.get("original_industry_name") or "").strip()
        nodes = data.get("nodes")
        relations = data.get("relations")
        
        if not industry_name:
            raise HTTPException(status_code=400, detail="请求数据必须包含 industry_name 字段")
            
        if not isinstance(nodes, list) or not isinstance(relations, list):
            raise HTTPException(status_code=400, detail="nodes 和 relations 必须是列表")
            
        # 使用当前登录用户的ID
        user_id = str(current_user["user_id"])
        
        lookup_names = [industry_name]
        if original_industry_name and original_industry_name != industry_name:
            lookup_names.append(original_industry_name)

        # 查询industrial_chain_meta表，获取产业链ID
        record_id = None
        matched_name = None
        conn = None
        try:
            from database.industrial_chain.connection import get_connection
            
            conn = await get_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)  # 明确使用DictCursor
            
            for lookup_name in lookup_names:
                # 优先查询状态为生成中的记录，查不到再查询任意状态记录
                query_sql = """
                    SELECT id, name
                    FROM industrial_chain_meta
                    WHERE name = %s AND status = 1
                    ORDER BY created_at DESC
                    LIMIT 1
                """
                cursor.execute(query_sql, (lookup_name,))
                result = cursor.fetchone()

                if not result:
                    query_any_sql = """
                        SELECT id, name
                        FROM industrial_chain_meta
                        WHERE name = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                    """
                    cursor.execute(query_any_sql, (lookup_name,))
                    result = cursor.fetchone()

                if result:
                    record_id = result['id']  # 使用字典键名访问
                    matched_name = result['name']
                    logger.info(f"找到产业链 '{matched_name}' 的记录ID: {record_id}")
                    break

            if not record_id:
                raise HTTPException(
                    status_code=404,
                    detail=f"未找到产业链 {industry_name} 的记录，请先创建产业链"
                )

            if matched_name != industry_name:
                cursor.execute(
                    "SELECT id FROM industrial_chain_meta WHERE name = %s AND id <> %s LIMIT 1",
                    (industry_name, record_id)
                )
                duplicate = cursor.fetchone()
                if duplicate:
                    raise HTTPException(
                        status_code=409,
                        detail=f"产业链名称 {industry_name} 已存在，不能重命名为该名称"
                    )

                cursor.execute(
                    "UPDATE industrial_chain_meta SET name = %s WHERE id = %s",
                    (industry_name, record_id)
                )
                logger.info(
                    f"产业链重命名: '{matched_name}' -> '{industry_name}', record_id={record_id}"
                )
            
            # 删除旧名称和新名称下的旧结构数据，随后按新名称完整重存
            delete_names = tuple(dict.fromkeys([matched_name, industry_name]))
            delete_placeholders = ', '.join(['%s'] * len(delete_names))
            delete_sql = f"DELETE FROM industrial_chain_structure WHERE chain_name IN ({delete_placeholders})"
            cursor.execute(delete_sql, delete_names)
            deleted_count = cursor.rowcount
            conn.commit()

            logger.info(f"已删除产业链 '{industry_name}' 的 {deleted_count} 条旧节点数据")
        except Exception as e:
            logger.error(f"查询产业链记录或标记旧三元组数据为已废弃时出错: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
        
        # 创建用户文件夹 - 使用时间戳作为pid
        import time
        pid = str(int(time.time()))
        user_folder = f"user_{user_id}_pid_{pid}"
        
        # 确保文件夹存在 - 已禁用
        os.makedirs(f"resultTxt/{user_folder}", exist_ok=True)
        
        # 将节点和关系写入文件 - 已禁用
        nodes_str = '\n'.join(nodes)
        relations_str = '\n'.join(relations)
        
        nodes_file = f"resultTxt/{user_folder}/nodes_{industry_name}.txt"
        relations_file = f"resultTxt/{user_folder}/relations_{industry_name}.txt"
        
        # 文件写入已禁用，直接使用内存中的数据
        # with open(nodes_file, 'w', encoding='utf-8') as f:
        #     f.write(nodes_str)
        
        # with open(relations_file, 'w', encoding='utf-8') as f:
        #     f.write(relations_str)
            
        # 调用服务存储数据到数据库，直接传递节点和关系数据
        structure_stored = await IndustryStructureService.parse_and_store_structure(
            industry_name=industry_name,
            user_id=user_id,
            pid=pid,
            record_id=record_id,  # 传递找到的产业链记录ID
            nodes=nodes,          # 传递节点列表
            relations=relations   # 传递关系列表
        )
        
        if not structure_stored:
            raise HTTPException(status_code=500, detail=f"存储产业链 {industry_name} 的结构数据失败")

        # 图谱生成成功，发送钉钉通知
        try:
            from services.dingtalk_service import get_bot
            oa_user_id = current_user.get("oa_user_id") or current_user.get("username")
            if oa_user_id:
                bot = get_bot("industry_chain")
                dinguserid = bot.get_dinguserid_by_alias(oa_user_id)
                if not dinguserid:
                    logger.info(f"图谱通知: 用户 {oa_user_id} 未绑定 dinguserid，跳过")
                else:
                    notification_title = f"📊 {industry_name}产业链图谱生成完毕"
                    notification_content = f"""## 📊 产业链图谱生成完成

---

**产业链名称：** {industry_name}

**生成时间：** 刚刚

---

### ✅ 图谱已生成

产业链节点和关系图谱已成功生成并保存。

---

### 📋 节点数量

共 {len(nodes)} 个节点，{len(relations)} 条关系。

---

📌 **产业链智能体** 自动通知
"""
                    bot.send_single_markdown([dinguserid], notification_title, notification_content)
                    logger.info(f"已发送图谱生成钉钉通知到用户 {oa_user_id}")
        except Exception as dingtalk_error:
            logger.warning(f"发送图谱生成钉钉通知失败: {str(dingtalk_error)}")

        return {
            "status": "success",
            "message": f"成功存储产业链 {industry_name} 的结构数据"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"存储产业链结构数据时出错: {str(e)}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"存储产业链结构数据失败: {str(e)}")


@industrial_router.post("/notify_task5_complete")
async def notify_task5_complete(request: Request, current_user: dict = Depends(get_current_user)):
    """
    前端确认"任务五完成"渲染后，由前端触发该端点发送第一阶段钉钉通知。
    通知内容为"产业链图谱生成完成"（即原任务五完成通知文案）。
    """
    try:
        data = await request.json()
        industry_name = data.get("industry_name")
        if not industry_name:
            raise HTTPException(status_code=400, detail="缺少 industry_name")

        oa_user_id = current_user.get("oa_user_id") or current_user.get("username")
        if oa_user_id:
            from services.dingtalk_service import get_bot
            bot = get_bot("industry_chain")
            dinguserid = bot.get_dinguserid_by_alias(oa_user_id)
            if dinguserid:
                notification_title = f"📊 {industry_name}产业链图谱生成完毕"
                notification_content = f"""## 📊 产业链图谱生成完成

---

**产业链名称：** {industry_name}

**生成时间：** 刚刚

---

### ✅ 产业链图谱已生成

产业链图谱已经成功生成，包含上中下游节点和关系三元组。

---

### 📋 后续步骤

如需生成企业名单，请继续执行第二阶段（Pipeline 10步骤）。

---

📌 **产业链智能体** 自动通知
"""
                bot.send_single_markdown([dinguserid], notification_title, notification_content)
                logger.info(f"已发送钉钉通知到用户 {oa_user_id}（产业链图谱生成完成）")

        return {"status": "success", "message": "发送通知成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"发送钉钉通知失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"发送钉钉通知失败: {str(e)}")


# 热点监控相关路由
@industrial_router.get("/hotspot/top_concepts")
async def get_top_concepts(limit: int = 4, current_user: dict = Depends(get_current_user)):
    """
    获取热门金融概念数据，按照热度(top_num)降序排序
    
    使用缓存策略:
    - 数据在内存中缓存，默认有效期1小时
    - 每天10点自动刷新缓存（与数据库更新时间同步）
    
    Args:
        limit: 返回数据的数量限制，默认为4
        current_user: 当前登录用户
        
    Returns:
        热门金融概念列表，包含缓存信息
    """
    try:
        result = await HotspotService.get_top_concepts(limit)
        
        # 获取缓存信息
        cache_info = {
            "is_cached": False,
            "cache_time": None,
            "expires_at": None,
            "next_update": None
        }
        
        # 如果HotspotService有缓存数据，添加缓存信息
        if hasattr(HotspotService, '_cache') and HotspotService._cache.get("top_concepts", {}).get("data"):
            cache = HotspotService._cache["top_concepts"]
            cache_time = datetime.fromtimestamp(cache["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
            expires_at = datetime.fromtimestamp(cache["expires_at"]).strftime('%Y-%m-%d %H:%M:%S')
            
            # 计算下次更新时间（明天的更新时间点）
            update_hour = HotspotService._cache_config["top_concepts"]["update_hour"]
            tomorrow = datetime.now() + timedelta(days=1)
            next_update = tomorrow.replace(hour=update_hour, minute=0, second=0, microsecond=0)
            
            # 今天的更新时间点
            today_update = datetime.now().replace(hour=update_hour, minute=0, second=0, microsecond=0)
            
            # 如果当前时间小于今天的更新时间点，则下次更新是今天
            if datetime.now() < today_update:
                next_update = today_update
                
            cache_info = {
                "is_cached": True,
                "cache_time": cache_time,
                "expires_at": expires_at,
                "next_update": next_update.strftime('%Y-%m-%d %H:%M:%S')
            }
        
        if not result:
            return {
                "status": "success",
                "message": "没有找到热门概念数据",
                "data": [],
                "cache_info": cache_info
            }
        
        return {
            "status": "success", 
            "message": f"成功获取{len(result)}条热门概念数据",
            "data": result,
            "cache_info": cache_info
        }
    except Exception as e:
        logger.error(f"获取热门概念数据时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取热门概念数据失败: {str(e)}")

@industrial_router.get("/chains/status")
async def get_industry_chains_status(current_user: dict = Depends(get_current_user)):
    """
    获取所有产业链名称，按状态分组（已完成、生成中和未生成）

    状态说明:
    - completed: 已完成的产业链 (status=2)
    - in_progress: 生成中的产业链 (status=1)
    - not_started: 未生成的产业链 (status=0)

    Args:
        current_user: 当前登录用户

    Returns:
        包含已完成、生成中和未生成产业链名称的字典
    """
    try:
        result = await IndustryStatusService.get_industry_chains_by_status()

        return {
            "status": "success",
            "message": "成功获取产业链状态数据",
            "data": result
        }
    except Exception as e:
        logger.error(f"获取产业链状态数据时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取产业链状态数据失败: {str(e)}")

@industrial_router.get("/chains/status-with-details")
async def get_industry_chains_status_with_details(current_user: dict = Depends(get_current_user)):
    """
    获取所有产业链的详细信息（包括节点数量、更新时间等）
    优化版本：一次查询返回所有数据，避免N+1查询问题

    状态说明:
    - completed: 已完成的产业链 (status=2)
    - in_progress: 生成中的产业链 (status=1)
    - not_started: 未生成的产业链 (status=0)

    Args:
        current_user: 当前登录用户

    Returns:
        包含已完成、生成中和未生成产业链详细信息的字典
        每个产业链包含: name, nodes, updateTime
    """
    try:
        result = await IndustryStatusService.get_industry_chains_with_details()

        return {
            "status": "success",
            "message": "成功获取产业链详细信息",
            "data": result
        }
    except Exception as e:
        logger.error(f"获取产业链详细信息时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取产业链详细信息失败: {str(e)}")

@industrial_router.post("/get_db_structure")
async def get_db_structure_api(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    获取产业链结构数据API（从数据库读取）
    
    Args:
        request: 包含industry_name的请求体
        current_user: 当前登录用户
        
    Returns:
        包含节点和关系的字典
    """
    try:
        # 从请求体获取产业链名称
        industry_name = request.get("industry_name")
        
        if not industry_name:
            raise HTTPException(status_code=400, detail="缺少industry_name参数")
        
        # 从数据库获取结构数据
        result = await IndustryStructureService.get_structure_from_db(industry_name)
        
        return {
            "status": "success",
            "message": f"成功从数据库获取产业链 {industry_name} 的结构数据",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"从数据库获取产业链结构数据时出错: {str(e)}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"从数据库获取产业链结构数据失败: {str(e)}")

@industrial_router.post("/cancel_process")
async def cancel_process(
    request: Request,
    industry_name: str = None,
    current_user: dict = Depends(get_current_user)
):
    """
    取消产业链分析任务
    支持两种参数传递方式：
    1. 查询参数: /cancel_process?industry_name=xxx
    2. 请求体JSON: {"industry_name": "xxx"}
    """
    try:
        # 尝试从请求体获取产业链名称
        if not industry_name:
            try:
                data = await request.json()
                industry_name = data.get("industry_name")
            except:
                # JSON解析失败，可能是空请求体
                pass
        
        # 如果两种方式都没有获取到industry_name，返回错误
        if not industry_name:
            raise HTTPException(status_code=400, detail="缺少industry_name参数")
        
        # 检查是否存在对应的活跃任务
        task_found = False
        
        if industry_name in active_tasks:
            # 设置取消标志
            active_tasks[industry_name]["cancel_flag"].set()
            logger.info(f"任务取消标志已设置: {industry_name}")
            task_found = True
            
            # 尝试取消任务
            future = active_tasks[industry_name]["future"] 
            if not future.done():
                # 对于线程池任务，主要通过cancel_flag来停止
                logger.info(f"任务正在执行，通过cancel_flag停止: {industry_name}")
            
            # 查询正在生成中的记录ID并标记为失败
            conn = None
            try:
                from database.industrial_chain.connection import get_connection
                
                conn = await get_connection()
                cursor = conn.cursor()
                
                # 查询最新的生成中的记录
                query = """
                SELECT id FROM industrial_chain_meta WHERE name = %s AND status = 1 
                ORDER BY created_at DESC LIMIT 1
                """
                cursor.execute(query, (industry_name,))
                record = cursor.fetchone()
                
                if record:
                    record_id = record[0]
                    # 将产业链记录标记为失败
                    from services.industry_storage_service import IndustryStorageService
                    await IndustryStorageService.mark_as_failed(record_id, f"用户取消了任务")
                    logger.info(f"已将产业链记录 {record_id} 标记为失败状态")
                    
            except Exception as e:
                logger.error(f"更新产业链记录状态失败: {e}")
            finally:
                if conn and conn.open:
                    conn.close()
            
        if not task_found:
            return {
                "status": "warning",
                "message": f"未找到产业链 '{industry_name}' 的活跃任务"
            }

        return {
            "status": "success",
            "message": f"产业链 '{industry_name}' 的分析任务取消请求已发送"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消任务时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")

@industrial_router.post("/node_articles")
async def get_node_articles(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    获取特定产业链中特定节点的相关文章链接
    
    请求体格式:
    {
        "chain_name": "产业链名称",
        "node_name": "节点名称"
    }
    
    返回:
    {
        "status": "success",
        "data": {
            "chain_name": "产业链名称",
            "total_articles": 总有效文章数量,
            "node_articles": [
                {
                    "id": 文章ID,
                    "url": "文章URL",
                    "title": "文章标题",
                    "created_at": "创建时间"
                },
                ...
            ]
        }
    }
    """
    try:
        # 从请求体获取参数
        data = await request.json()
        chain_name = data.get("chain_name")
        node_name = data.get("node_name")
        
        if not chain_name:
            raise HTTPException(status_code=400, detail="缺少chain_name参数")
        if not node_name:
            raise HTTPException(status_code=400, detail="缺少node_name参数")
            
        conn = None
        try:
            from database.industrial_chain.connection import get_connection
            
            conn = await get_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            # 查询指定节点的文章
            node_query = """
            SELECT id, url, title, created_at
            FROM node_article_links
            WHERE chain_name = %s AND node_name = %s AND status = 1
            ORDER BY created_at DESC
            """
            
            cursor.execute(node_query, (chain_name, node_name))
            articles = cursor.fetchall()
            
            # 查询整个产业链的有效文章总数
            total_query = """
            SELECT COUNT(*) as total
            FROM node_article_links
            WHERE chain_name = %s AND status = 1
            """
            
            cursor.execute(total_query, (chain_name,))
            total_result = cursor.fetchone()
            total_articles = total_result['total'] if total_result else 0
            
            # 格式化日期时间
            for article in articles:
                if 'created_at' in article and article['created_at']:
                    article['created_at'] = article['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            
            logger.info(f"获取到产业链 {chain_name} 节点 {node_name} 的 {len(articles)} 篇文章，产业链总文章数: {total_articles}")
            
            return {
                "status": "success",
                "data": {
                    "chain_name": chain_name,
                    "total_articles": total_articles,
                    "node_articles": articles
                }
            }
        except Exception as e:
            logger.error(f"获取节点文章失败: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            if conn and conn.open:
                conn.rollback()
            raise
        finally:
            if conn and conn.open:
                conn.close()
    except Exception as e:
        logger.error(f"获取节点文章时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"获取文章数据失败: {str(e)}")
    
@industrial_router.post("/validate_industry_name")
async def validate_industry_name(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    验证产业链名称是否有效
    请求体格式:
    {
        "industry_name": "产业链名称"
    }
    """
    try:
        # 从请求体获取参数
        data = await request.json()
        industry_name = data.get("industry_name")
        user_id = str(current_user["user_id"])

        # 判断 industry_name 是否为空
        if not industry_name:
            raise HTTPException(status_code=400, detail="缺少 industry_name 参数")

        # 调用 process_input_industry 函数处理 industry_name
        async def send_message(message, message_type):
            return {"type": message_type, "content": message}

        # 调用处理函数
        industry_name = await process_input_industry(input_clean_prompts, industry_name, user_id, send_message)
        # 检查处理结果是否为空
        if industry_name is None:
            logger.warning(f"产业链名称 AI处理结果为空")
            return {"status": "error", "message": "AI处理结果为空"}
        # 去掉空格以及空格之后的内容
        industry_name = industry_name.split(' ')[0]
        # 去掉\n以及\n之后的内容
        industry_name = industry_name.split('\n')[0]        
        logger.info(f"处理后的产业链描述: {repr(industry_name)}")

        industry_name = await process_input_industry(input_clean_post_prompts, industry_name, user_id, send_message)
        logger.info(f"二次处理后的产业链描述: {repr(industry_name)}")

        # 如果 industry_name 处理结果为空，直接返回
        if industry_name is None or not industry_name.strip() or industry_name.strip() == '""' or industry_name == '空' or industry_name == '[空]':
            print("industry_name 为空，直接返回")
            await send_message("错误", "0")
            return {"status": "error", "message": "无内容"}

        # 最终清理：确保返回纯文本，去除可能残留的引号
        industry_name = industry_name.strip().strip('"\'').strip()
        
        await send_message("正确", "0")
        await send_message(f"产业链名称：{industry_name}", "0")
        print(f"industry_name: {industry_name}")
        return {"status": "success", "message": "产业链名称有效", "industry_name": industry_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证产业链名称时出错: {str(e)}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"验证产业链名称失败: {str(e)}")

@industrial_router.post("/export_structure")
async def export_structure_api(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    导出产业链结构数据API
    
    请求体格式:
    {
        "industry_name": "产业链名称",
        "format": "json|excel|graphml|csv"  # 可选，默认为json
    }
    
    Args:
        request: 包含产业链名称和导出格式的请求体
        current_user: 当前登录用户
        
    Returns:
        导出结果和下载链接
    """
    try:
        # 从请求体获取参数
        industry_name = request.get("industry_name")
        export_format = request.get("format", "json")
        
        if not industry_name:
            raise HTTPException(status_code=400, detail="缺少industry_name参数")
        
        # 验证导出格式
        valid_formats = ["json", "excel", "graphml", "csv"]
        if export_format.lower() not in valid_formats:
            raise HTTPException(
                status_code=400, 
                detail=f"不支持的导出格式: {export_format}，支持的格式: {', '.join(valid_formats)}"
            )
        
        # 执行导出
        result = await IndustryStructureService.export_structure(industry_name, export_format)
        
        if result["status"] == "error":
            raise HTTPException(status_code=500, detail=result["message"])
        
        return {
            "status": "success",
            "message": f"成功导出产业链 {industry_name} 的结构数据",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出产业链结构数据时出错: {str(e)}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"导出产业链结构数据失败: {str(e)}")

@industrial_router.get("/download/{filename}")
async def download_file(filename: str):
    """
    下载导出的文件
    
    Args:
        filename: 文件名
        
    Returns:
        文件下载响应
    """
    try:
        from fastapi.responses import FileResponse
        import mimetypes
        
        file_path = os.path.join("exports", filename)
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 确定MIME类型
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = 'application/octet-stream'
        
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=mime_type
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载文件时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"下载文件失败: {str(e)}")

# 添加兼容的图谱接口
@industrial_router.get("/industry-chain")
async def get_industry_chain_compat(
    industry_name: str = Query(..., description="产业链名称"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取产业链图谱数据 - 兼容旧版本API
    重定向到 /api/industrial/get_db_structure
    """
    try:
        # 调用现有的获取结构数据方法
        result = await IndustryStructureService.get_structure_from_db(industry_name)
        
        # 转换为前端期望的格式
        return {
            "status": "success",
            "data": {
                "nodes": result.get("nodes", []),
                "links": result.get("relations", [])
            }
        }
    except Exception as e:
        logger.error(f"获取产业链图谱数据失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取图谱数据失败: {str(e)}")

@industrial_router.post("/industry-chain")
async def save_industry_chain_compat(
    data: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """
    保存产业链图谱数据 - 兼容旧版本API
    重定向到 /api/industrial/store_structure
    """
    try:
        # 转换数据格式
        industry_name = data.get("industry_name")
        nodes_data = data.get("nodes", [])
        links_data = data.get("links", [])

        logger.info(f"保存产业链图谱 - 产业链: {industry_name}")
        logger.info(f"保存产业链图谱 - 收到节点数: {len(nodes_data)}")
        logger.info(f"保存产业链图谱 - 收到关系数: {len(links_data)}")

        # 提取节点名称
        nodes = [node.get("name", "") for node in nodes_data if isinstance(node, dict)]

        # 转换连线为关系格式
        relations = []
        for link in links_data:
            if isinstance(link, dict):
                source = link.get("source", "")
                target = link.get("target", "")
                relation_type = link.get("relation", "related-to")  # 修复：使用relation而不是type
                if source and target:
                    relations.append(f"{source},{target},{relation_type}")

        logger.info(f"保存产业链图谱 - 提取节点数: {len(nodes)}")
        logger.info(f"保存产业链图谱 - 提取关系数: {len(relations)}")

        # 调用现有的存储方法
        store_data = {
            "industry_name": industry_name,
            "nodes": nodes,
            "relations": relations
        }

        # 重用现有的存储逻辑
        return await store_structure_api(store_data, current_user)

    except Exception as e:
        logger.error(f"保存产业链图谱数据失败: {str(e)}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"保存图谱数据失败: {str(e)}")


@industrial_router.get("/chains/list")
async def get_chains_list(current_user: dict = Depends(get_current_user)):
    """
    获取所有可用的产业链列表

    从 business_data.chain_needcomp 表中获取所有产业链名称
    """
    try:
        import pymysql

        # 连接数据库
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data',
            charset='utf8mb4'
        )
        cursor = conn.cursor()

        # 查询 chain_needcomp 表中的所有产业链名称
        query = """
        SELECT DISTINCT chain_name
        FROM business_data.chain_needcomp
        ORDER BY chain_name
        """
        cursor.execute(query)
        chains = [row[0] for row in cursor.fetchall()]

        cursor.close()
        conn.close()

        logger.info(f"从 chain_needcomp 表获取到 {len(chains)} 条产业链")

        return {
            "status": "success",
            "message": f"成功获取 {len(chains)} 条产业链",
            "data": chains
        }

    except Exception as e:
        logger.error(f"获取产业链列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取产业链列表失败: {str(e)}")


@industrial_router.post("/stop_pipeline")
async def stop_pipeline_process(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    停止正在运行的产业链处理任务（强制停止）
    """
    industry_name = request.get("industry_name")
    if not industry_name:
        raise HTTPException(status_code=400, detail="产业链名称不能为空")

    # 导入 running_tasks 来访问任务状态
    from pipeline_routes import running_tasks

    # 强制停止：直接杀掉相关进程
    import os
    import subprocess

    # 设置取消标志
    if industry_name in running_tasks:
        running_tasks[industry_name]["cancelled"] = True

    # 调用 cancel_token 设置取消令牌
    from steps.cancel_token import cancel_task
    cancel_task(industry_name)

    # 强制杀掉所有相关的子进程（包含step或pipeline的Python进程）
    try:
        # 查找所有相关的Python子进程
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True
        )

        killed_pids = []
        for line in result.stdout.split('\n'):
            if 'python' in line.lower() and ('step' in line.lower() or 'pipeline' in line.lower() or industry_name in line):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1])
                        # 不杀掉主进程
                        if pid != os.getpid():
                            os.kill(pid, 9)  # SIGKILL
                            killed_pids.append(pid)
                    except (ValueError, ProcessLookupError):
                        pass

        logger.info(f"强制停止 {industry_name}，杀掉进程: {killed_pids}")
    except Exception as e:
        logger.error(f"强制停止时出错: {e}")

    # 更新数据库状态
    try:
        import pymysql
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data'
        )
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pipeline_task_status
            (industry_name, status, current_step, progress, cancelled_at)
            VALUES (%s, 'cancelled', current_step, progress, NOW())
            ON DUPLICATE KEY UPDATE
            status = 'cancelled',
            cancelled_at = NOW(),
            updated_at = NOW()
        """, (industry_name,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        pass  # 忽略数据库更新错误

    return {"status": "success", "message": f"已强制停止 {industry_name}"}


@industrial_router.delete("/delete_industry/{industry_name}")
async def delete_industry_api(
    industry_name: str,
    current_user: dict = Depends(get_current_user)
):
    """
    删除产业链及其相关数据
    """
    try:
        import pymysql
        import traceback
        logger.info(f"收到删除请求，产业链名称: {industry_name}")

        # 连接到 industrial_chain 数据库
        conn = pymysql.connect(
            host='8.141.5.67',
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='industrial_chain',
            charset='utf8mb4'
        )
        cursor = conn.cursor()

        try:
            # 1. 从 industrial_chain_meta 表中删除
            delete_meta_sql = "DELETE FROM industrial_chain_meta WHERE name = %s"
            cursor.execute(delete_meta_sql, (industry_name,))
            meta_deleted = cursor.rowcount
            logger.info(f"从 industrial_chain_meta 删除 {meta_deleted} 行")

            # 2. 从 industrial_chain_structure 表中删除
            delete_structure_sql = "DELETE FROM industrial_chain_structure WHERE chain_name = %s"
            cursor.execute(delete_structure_sql, (industry_name,))
            structure_deleted = cursor.rowcount
            logger.info(f"从 industrial_chain_structure 删除 {structure_deleted} 行")

            conn.commit()
            logger.info(f"数据库事务已提交")

            total_deleted = meta_deleted + structure_deleted
            message = f"成功删除产业链「{industry_name}」，共删除 {total_deleted} 条数据（meta: {meta_deleted}, structure: {structure_deleted}）"

            return {"status": "success", "message": message}

        except Exception as db_err:
            conn.rollback()
            logger.error(f"数据库操作失败，已回滚: {str(db_err)}")
            raise db_err
        finally:
            cursor.close()
            conn.close()

    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"删除产业链失败，详细堆栈:\n{error_trace}")
        raise HTTPException(status_code=500, detail=f"删除产业链失败: {str(e)}")


# ==================== 图谱导入功能 ====================

TEMPLATE_FILE = "/root/mix_project/database/图谱导入模版.xlsx"


@industrial_router.get("/graph/template")
async def download_graph_template(current_user: dict = Depends(get_current_user)):
    """
    下载图谱导入模板

    Returns:
        FileResponse: Excel模板文件
    """
    if not os.path.exists(TEMPLATE_FILE):
        raise HTTPException(status_code=404, detail="模板文件不存在")

    return FileResponse(
        path=TEMPLATE_FILE,
        filename="图谱导入模版.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@industrial_router.post("/graph/import")
async def import_graph_structure(
    file: UploadFile = File(...),
    industry_name: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """
    导入图谱结构

    Args:
        file: Excel文件，包含列：编码、产业环节、父级id、级别
        industry_name: 产业链名称
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持Excel文件格式")

    conn_business = None
    conn_industrial = None

    try:
        # 读取Excel文件
        contents = await file.read()
        import io
        df = pd.read_excel(io.BytesIO(contents))

        # 验证必需列
        required_columns = ['编码', '产业环节', '父级id', '级别']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=f"Excel文件缺少必需列: {', '.join(missing_columns)}"
            )

        # 连接数据库
        conn_business = pymysql.connect(
            host='8.141.5.67',
            port=3306,
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='business_data',
            charset='utf8mb4'
        )
        conn_industrial = pymysql.connect(
            host='8.141.5.67',
            port=3306,
            user='root',
            password=os.getenv('DB_PASSWORD'),
            database='industrial_chain',
            charset='utf8mb4'
        )

        cursor_business = conn_business.cursor()
        cursor_industrial = conn_industrial.cursor()

        # 删除旧数据
        cursor_industrial.execute(
            "DELETE FROM industrial_chain_structure WHERE chain_name = %s",
            (industry_name,)
        )
        cursor_business.execute(
            "DELETE FROM chain_needcomp WHERE chain_name = %s",
            (industry_name,)
        )

        # 构建节点ID映射 (excel_id -> actual_db_id)
        node_id_map = {}

        # 获取或创建chain_id
        cursor_industrial.execute(
            "SELECT id FROM industrial_chain_meta WHERE name = %s",
            (industry_name,)
        )
        result = cursor_industrial.fetchone()
        if result:
            chain_id = result[0]
            # 更新现有记录状态为已完成
            cursor_industrial.execute(
                "UPDATE industrial_chain_meta SET status = 2 WHERE id = %s",
                (chain_id,)
            )
        else:
            # 创建新记录，状态直接设为已完成
            now = datetime.now()
            cursor_industrial.execute(
                "INSERT INTO industrial_chain_meta (name, status, created_at) VALUES (%s, 2, %s)",
                (industry_name, now)
            )
            chain_id = cursor_industrial.lastrowid

        now_for_data = datetime.now()

        # 第一步：创建根节点（产业链名称本身），level=0
        cursor_industrial.execute("""
            INSERT INTO industrial_chain_structure
            (chain_name, nodes, parent_node, parent_id, node_level, create_time, update_time, chain_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (industry_name, industry_name, None, None, 0, now_for_data, now_for_data, chain_id, 1))
        root_db_id = cursor_industrial.lastrowid
        # 根节点用特殊ID存储
        node_id_map['__root__'] = root_db_id

        # 第二步：构建Excel数据中节点名称到编码的映射
        excel_id_to_name = {}
        for _, row in df.iterrows():
            excel_id = row['编码']
            node_name = str(row['产业环节']).strip()
            excel_id_to_name[excel_id] = node_name

        # 第三步：按级别分组，确保先插入父节点
        df_by_level = {}
        for _, row in df.iterrows():
            level = int(row['级别']) if pd.notna(row['级别']) else 1
            if level not in df_by_level:
                df_by_level[level] = []
            df_by_level[level].append(row)

        # 第四步：按级别从小到大插入节点
        for level in sorted(df_by_level.keys()):
            for _, row in df.iterrows():
                row_level = int(row['级别']) if pd.notna(row['级别']) else 1
                if row_level != level:
                    continue

                excel_id = row['编码']
                node_name = str(row['产业环节']).strip()
                parent_id_excel = row['父级id'] if pd.notna(row['父级id']) else None

                # 确定父节点
                parent_node = None
                parent_db_id = None

                if row_level == 1:
                    # Level 1 节点（上中下游）的父级是产业链名称（根节点）
                    parent_node = industry_name
                    parent_db_id = root_db_id
                elif pd.notna(parent_id_excel) and int(parent_id_excel) in node_id_map:
                    # Level 2+ 节点的父级从Excel数据中查找
                    parent_db_id = node_id_map[int(parent_id_excel)]
                    parent_node = excel_id_to_name.get(int(parent_id_excel), '')

                # 插入到industrial_chain表 (status=1 表示有效数据，可被图谱查看)
                cursor_industrial.execute("""
                    INSERT INTO industrial_chain_structure
                    (chain_name, nodes, parent_node, parent_id, node_level, create_time, update_time, chain_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (industry_name, node_name, parent_node, parent_db_id, row_level, now_for_data, now_for_data, chain_id, 1))

                # 获取实际插入的ID并存储到映射表
                actual_db_id = cursor_industrial.lastrowid
                node_id_map[excel_id] = actual_db_id

                # 插入到business_data表
                cursor_business.execute("""
                    INSERT INTO chain_needcomp
                    (chain_name, nodes, parent_node, parent_id, node_level, create_time, update_time, chain_id, STATUS, nodes_definition)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (industry_name, node_name, parent_node, parent_db_id, row_level, now_for_data, now_for_data, chain_id, 1, f'{node_name}是{industry_name}产业链的重要环节。'))

        conn_industrial.commit()
        conn_business.commit()

        logger.info(f"成功导入图谱结构: {industry_name}, 共{len(df)}个节点")

        return {
            "status": "success",
            "message": f"成功导入{len(df)}个节点",
            "industry_name": industry_name,
            "node_count": len(df)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入图谱结构失败: {e}")
        if conn_industrial:
            conn_industrial.rollback()
        if conn_business:
            conn_business.rollback()
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")
    finally:
        if conn_business:
            conn_business.close()
        if conn_industrial:
            conn_industrial.close()
