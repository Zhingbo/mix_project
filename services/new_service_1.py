from fastapi import APIRouter, Request, Depends, HTTPException, Body
from sse_starlette.sse import EventSourceResponse
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor, Future
import functools
import multiprocessing
import os
import re
from typing import Dict, Any, List
import pymysql
from datetime import datetime, timedelta

from services.industry_service import process_industry
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


max_workers = 150

logger.info(f"初始化线程池，使用 {max_workers} 个工作线程")

# 创建一个线程池执行器
executor = ThreadPoolExecutor(max_workers=max_workers)

# 创建一个字典来跟踪正在进行的任务
# 格式: {industry_name: {"future": future对象, "queue": 消息队列, "user_id": 用户ID}}
active_tasks = {}

industrial_router = APIRouter(prefix="/api/industrial", tags=["industrial"])

@industrial_router.post("/process_stream")
async def process_stream_api(request: Request, current_user: dict = Depends(get_current_user)):
    """
    产业链分析API - 需要用户认证
    """
    data = await request.json()
    industry_name = data.get("industry_name")
    custom_urls = data.get("custom_urls")  # 获取自定义URL
    sites = data.get("sites")  # 获取自定义搜索站点
    
    if not industry_name:
        raise HTTPException(status_code=400, detail="Missing industry_name")
    
    # 使用当前登录用户的ID
    user_id = str(current_user["user_id"])

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
        # 如果任务已经在运行且由同一用户发起，可以选择返回错误
        if active_task["user_id"] == user_id and not active_task["future"].done():
            raise HTTPException(status_code=400, detail=f"产业链 '{industry_name}' 的分析任务已在进行中")

    async def event_generator():
        # 创建取消标志和消息队列（在函数开始时创建）
        queue = asyncio.Queue()
        cancel_flag = asyncio.Event()  # 用于取消任务的标志

        async def send_message(message, message_type):
            # 检查取消标志
            if cancel_flag.is_set():
                return
            await queue.put(json.dumps({"type": message_type, "content": message}))

        # 直接在事件循环中运行process_industry，不使用线程池
        # 这样可以避免事件循环嵌套问题
        async def run_process_industry_async():
            try:
                return await process_industry(
                    industry_name,
                    custom_urls=custom_urls,
                    user_id=user_id,
                    send_message=send_message,
                    sites=sites,
                    cancel_flag=cancel_flag
                )
            except Exception as e:
                logger.error(f"process_industry执行错误: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return None

        # 直接创建异步任务，不使用executor
        loop = asyncio.get_event_loop()
        task = loop.create_task(run_process_industry_async())

        # 将任务信息存储在全局字典中（使用task代替future）
        active_tasks[industry_name] = {
            "future": task,  # 使用task而不是future
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
        industry_name = data.get("industry_name")
        nodes = data.get("nodes")
        relations = data.get("relations")
        
        if not industry_name:
            raise HTTPException(status_code=400, detail="请求数据必须包含 industry_name 字段")
            
        if not isinstance(nodes, list) or not isinstance(relations, list):
            raise HTTPException(status_code=400, detail="nodes 和 relations 必须是列表")
            
        # 使用当前登录用户的ID
        user_id = str(current_user["user_id"])
        
        # 查询industrial_chain_meta表，获取产业链ID
        record_id = None
        conn = None
        try:
            from database.industrial_chain.connection import get_connection
            
            conn = await get_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)  # 明确使用DictCursor
            
            # 查询该产业链名称在industrial_chain_meta表中状态为生成中(1)的记录
            query_sql = "SELECT id FROM industrial_chain_meta WHERE name = %s AND status = 1 ORDER BY created_at DESC LIMIT 1"
            cursor.execute(query_sql, (industry_name,))
            result = cursor.fetchone()
            
            if result:
                record_id = result['id']  # 使用字典键名访问
                logger.info(f"找到产业链 '{industry_name}' 的记录ID: {record_id}")
            else:
                logger.warning(f"未找到产业链 '{industry_name}' 状态为生成中的记录")
                
                # 尝试查找任何状态的产业链记录
                query_any_sql = "SELECT id FROM industrial_chain_meta WHERE name = %s ORDER BY created_at DESC LIMIT 1"
                cursor.execute(query_any_sql, (industry_name,))
                result_any = cursor.fetchone()
                
                if result_any:
                    record_id = result_any['id']  # 使用字典键名访问
                    logger.info(f"找到产业链 '{industry_name}' 的任意状态记录ID: {record_id}")
                else:
                    raise HTTPException(status_code=404, detail=f"未找到产业链 {industry_name} 的记录，请先创建产业链")
            
            # 更新industrial_chain_structure表中的记录状态为已废弃
            update_sql = "UPDATE industrial_chain_structure SET status = %s WHERE chain_name = %s AND (status = 1 OR status IS NULL)"
            cursor.execute(update_sql, (2, industry_name))  # 已废弃状态为2
            updated_count = cursor.rowcount
            conn.commit()
            
            logger.info(f"已将产业链 '{industry_name}' 的 {updated_count} 条三元组记录标记为已废弃")
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
        
        # 确保文件夹存在
        os.makedirs(f"resultTxt/{user_folder}", exist_ok=True)
        
        # 将节点和关系写入文件
        nodes_str = '\n'.join(nodes)
        relations_str = '\n'.join(relations)
        
        nodes_file = f"resultTxt/{user_folder}/nodes_{industry_name}.txt"
        relations_file = f"resultTxt/{user_folder}/relations_{industry_name}.txt"
        
        with open(nodes_file, 'w', encoding='utf-8') as f:
            f.write(nodes_str)
            
        with open(relations_file, 'w', encoding='utf-8') as f:
            f.write(relations_str)
            
        # 调用服务存储数据到数据库，传递record_id
        structure_stored = await IndustryStructureService.parse_and_store_structure(
            industry_name=industry_name,
            user_id=user_id,
            pid=pid,
            record_id=record_id  # 传递找到的产业链记录ID
        )
        
        if not structure_stored:
            raise HTTPException(status_code=500, detail=f"存储产业链 {industry_name} 的结构数据失败")
            
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
            
        # 获取用户ID
        user_id = current_user.get("id") if current_user else None
        
        # 检查是否存在对应的活跃任务
        task_id = f"{user_id}_{industry_name}" if user_id else industry_name
        task_found = False
        
        if task_id in active_tasks:
            active_tasks[task_id]["cancel_flag"].set()
            logger.info(f"任务取消标志已设置: {task_id}")
            task_found = True
            
            # 查询正在生成中的记录ID
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
                    await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 主动取消")
                    
                    # 将相关的产业链结构记录标记为无效
                    structure_update_query = """
                    UPDATE industrial_chain_structure 
                    SET status = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE chain_id = %s
                    """
                    cursor.execute(structure_update_query, (record_id,))
                    affected_rows_structure = cursor.rowcount
                    
                    # 将相关的节点文章链接标记为无效
                    article_update_query = """
                    UPDATE node_article_links 
                    SET status = 0, created_at = CURRENT_TIMESTAMP
                    WHERE chain_name = %s
                    """
                    cursor.execute(article_update_query, (industry_name,))
                    affected_rows_articles = cursor.rowcount
                    
                    conn.commit()
                    
                    logger.info(f"已将产业链记录 {record_id} 标记为失败，同时将 {affected_rows_structure} 条结构记录和 {affected_rows_articles} 条文章链接标记为无效")
                else:
                    logger.info(f"未找到产业链 {industry_name} 的生成中记录")
            except Exception as e:
                logger.error(f"更新数据库记录状态失败: {e}")
                import traceback
                logger.error(f"详细错误信息: {traceback.format_exc()}")
                if conn and conn.open:
                    conn.rollback()
            finally:
                if conn and conn.open:
                    conn.close()
            
            # 返回取消成功的消息
            return {
                "status": "success", 
                "message": f"产业链 {industry_name} 分析任务已取消"
            }
        else:
            # 如果内存中没有找到活跃任务，检查产业链是否在数据库中存在
            conn = None
            try:
                from database.industrial_chain.connection import get_connection
                
                conn = await get_connection()
                cursor = conn.cursor()
                
                # 检查产业链是否存在
                check_query = """
                SELECT COUNT(*) as count FROM industrial_chain_meta WHERE name = %s
                """
                cursor.execute(check_query, (industry_name,))
                result = cursor.fetchone()
                
                # 增强错误处理，避免None访问导致错误
                count = 0
                if result is not None:
                    if isinstance(result, dict):
                        count = result.get('count', 0)
                    else:
                        count = result[0] if result else 0
                
                if count > 0:
                    logger.info(f"产业链 {industry_name} 存在于数据库中，但没有正在运行的任务")
                    return {
                        "status": "warning", 
                        "message": f"产业链 {industry_name} 已存在，但没有正在运行的分析任务"
                    }
                else:
                    logger.info(f"产业链 {industry_name} 在数据库中不存在")
                    return {
                        "status": "error", 
                        "message": f"产业链 {industry_name} 不存在"
                    }
            except Exception as e:
                logger.error(f"检查产业链是否存在时出错: {e}")
                return {
                    "status": "error", 
                    "message": f"检查产业链 {industry_name} 是否存在时出错: {str(e)}"
                }
            finally:
                if conn and conn.open:
                    conn.close()
    except Exception as e:
        logger.error(f"取消产业链分析任务时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"取消产业链分析任务时发生错误: {str(e)}")

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
        # 去掉空格以及空格之后的内容
        industry_name = industry_name.split(' ')[0]
        # 去掉\n以及\n之后的内容
        industry_name = industry_name.split('\n')[0]        
        logger.info(f"处理后的产业链描述: {repr(industry_name)}")

        industry_name = await process_input_industry(input_clean_post_prompts, industry_name, user_id, send_message)
        logger.info(f"二次处理后的产业链描述: {repr(industry_name)}")

        # 如果 industry_name 处理结果为空，直接返回
        if industry_name is None or not industry_name.strip() or industry_name.strip() == '""' or industry_name == '空':
            print("industry_name 为空，直接返回")
            await send_message("错误", "0")
            return {"status": "error", "message": "无内容"}

        await send_message("正确", "0")
        await send_message(f"产业链名称：{repr(industry_name)}", "0")
        print(f"industry_name: {repr(industry_name)}")
        return {"status": "success", "message": "产业链名称有效", "industry_name": repr(industry_name)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证产业链名称时出错: {str(e)}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"验证产业链名称失败: {str(e)}")