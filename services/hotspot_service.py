from typing import List, Dict, Any
import time
import asyncio
from datetime import datetime, timedelta
import threading
import traceback
import concurrent.futures
import os
import re
import fcntl
from contextlib import contextmanager

from database.business_data.concept_dao import ConceptDAO
from utils.logger import get_logger
import yaml

# 加载清洗提示词
with open("config/settings_show2.yaml", "r") as file:
    settings = yaml.load(file, Loader=yaml.FullLoader)

input_clean_prompts = settings['prompts']['input_clean']['content']

logger = get_logger(__name__)

BACKGROUND_LOCK_DIR = "/tmp/mix_project_hotspot_locks"
os.makedirs(BACKGROUND_LOCK_DIR, exist_ok=True)

# 创建一个共享的线程池执行器，用于所有IO密集型任务
io_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,  # 适度并行，避免资源过载
    thread_name_prefix="io-worker"
)

class HotspotService:
    """
    热点监控服务，提供概念板块热点数据分析
    """
    # 双缓存数据结构：永远保持一个可用的缓存供读取
    _cache = {
        "top_concepts": {
            "active": {  # 当前活跃缓存，用于读取
                "data": None,
                "timestamp": 0,
                "expires_at": 0
            },
            "building": {  # 正在构建的缓存，用于更新
                "data": None,
                "timestamp": 0,
                "expires_at": 0,
                "is_updating": False
            }
        }
    }
    
    # 初始化状态标志
    _initialized = False
    
    # 缓存配置
    _cache_config = {
        "top_concepts": {
            "ttl": 3600,  # 测试用：缓存10秒
            "update_hour": 10,  # 每天10点更新数据
            "max_age": 86400,  # 最大缓存时间24小时，防止缓存永不更新
            "preload_size": 4,  # 预加载数量，与前端展示数量一致
            "validation_batch_size": 5,  # 批量验证的大小
            "validation_delay": 0.5  # 验证批次间的延迟（秒）
        }
    }
    
    # 缓存锁 - 只用于保护缓存切换操作
    _cache_locks = {
        "top_concepts": threading.RLock()
    }
    
    # 进程池 - 用于CPU密集型任务（如验证操作）
    _process_pool = None

    @staticmethod
    @contextmanager
    def _background_update_lock(cache_key: str):
        lock_path = os.path.join(BACKGROUND_LOCK_DIR, f"{cache_key}.lock")
        lock_file = open(lock_path, "w")
        acquired = False
        try:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                acquired = False
            yield acquired
        finally:
            if acquired:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    @staticmethod
    def _clean_concept_name_locally(concept_name: str):
        if not concept_name:
            return None

        name = str(concept_name).strip()
        name = re.sub(r'[\s\r\n]+', ' ', name).strip()
        name = re.sub(r'(概念|产业链|板块|题材)$', '', name).strip()
        name = name.split()[0].split('\n')[0].strip()

        invalid_exact = {
            '出海', '并购', '发展', '经济', '立案调查', '年报保留意见整理',
            '保留意见', '涨价概念', '重组预期', '摘帽', 'st板块'
        }
        if not name or len(name) <= 1 or name in invalid_exact:
            return None
        if name.isdigit():
            return None
        if len(name) > 20:
            return None
        if re.search(r'(调查|重组预期|保留意见|请问|怎么|如何|整理|公告|披露|问询|监管)', name):
            return None

        return name

    @classmethod
    def _normalize_concept_for_cache(cls, concept: Dict[str, Any]):
        concept_name = concept.get("concept_name", "")
        local_name = cls._clean_concept_name_locally(concept_name)
        if not local_name:
            return None

        concept_copy = concept.copy()
        concept_copy["concept_name"] = local_name
        if local_name != concept_name:
            concept_copy["original_name"] = concept_name
        return concept_copy

    @classmethod
    def _should_update_cache(cls, cache_key: str) -> bool:
        """
        判断是否应该更新缓存
        
        判断条件:
        1. 缓存不存在或已过期
        2. 当前时间已经过了设定的更新时间点（例如10点）
        
        Args:
            cache_key: 缓存键名
            
        Returns:
            是否应该更新缓存
        """
        # 获取活跃缓存
        cache_entry = cls._cache.get(cache_key)
        if not cache_entry:
            return True
            
        active_cache = cache_entry.get("active", {})
        building_cache = cache_entry.get("building", {})
        
        # 如果正在构建新缓存，不重复触发更新
        if building_cache.get("is_updating", False):
            return False
            
        # 检查活跃缓存是否存在且未过期
        if not active_cache.get("data") or time.time() > active_cache.get("expires_at", 0):
            return True
        
        # 检查当前是否已经过了今天的更新时间点
        config = cls._cache_config.get(cache_key, {})
        update_hour = config.get("update_hour")
        
        if update_hour is not None:
            now = datetime.now()
            update_time = now.replace(hour=update_hour, minute=0, second=0, microsecond=0)
            
            # 如果当前时间已经过了更新时间点，且缓存是在更新时间点之前创建的
            if now >= update_time and active_cache.get("timestamp", 0) < update_time.timestamp():
                return True
        
        return False
    
    @classmethod
    def _create_cache_entry(cls, data: Any, ttl: int = 3600) -> Dict:
        """
        创建新的缓存条目
        
        Args:
            data: 缓存数据
            ttl: 缓存有效期（秒）
            
        Returns:
            缓存条目字典
        """
        now = time.time()
        
        # 计算过期时间
        expires_at = now + ttl
        
        return {
            "data": data,
            "timestamp": now,
            "expires_at": expires_at
        }
    
    @classmethod
    def _commit_cache_update(cls, cache_key: str, new_data: Any) -> None:
        """
        提交缓存更新 - 将构建完成的缓存切换为活跃缓存
        
        Args:
            cache_key: 缓存键名
            new_data: 新的缓存数据
        """
        config = cls._cache_config.get(cache_key, {})
        ttl = config.get("ttl", 3600)
        max_age = config.get("max_age", 86400)
        
        now = time.time()
        
        # 计算过期时间
        expires_at = now + ttl
        
        # 确保不会超过最大缓存时间
        tomorrow = datetime.now() + timedelta(days=1)
        tomorrow_update = tomorrow.replace(hour=config.get("update_hour", 10), minute=0, second=0, microsecond=0)
        max_expires_at = tomorrow_update.timestamp()
        
        # 使用较早的过期时间
        final_expires_at = min(expires_at, max_expires_at)
        
        # 准备新的缓存条目
        new_cache_entry = {
            "data": new_data,
            "timestamp": now,
            "expires_at": final_expires_at
        }
        
        # 使用锁保护缓存切换操作
        with cls._cache_locks[cache_key]:
            # 将构建缓存更新为空闲状态
            cls._cache[cache_key]["building"] = {
                "data": None,
                "timestamp": 0,
                "expires_at": 0,
                "is_updating": False
            }
            
            # 将新缓存设置为活跃缓存
            cls._cache[cache_key]["active"] = new_cache_entry
        
        # 记录缓存操作
        expire_time = datetime.fromtimestamp(final_expires_at).strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"提交缓存更新: {cache_key}, 过期时间: {expire_time}, 缓存数据量: {len(new_data) if isinstance(new_data, list) else 0}")
    
    @classmethod
    async def _update_cache_background(cls, cache_key: str):
        """
        无阻塞的缓存更新后台任务
        采用按需验证策略：
        1. 先获取前端需要展示的数量（通常是4条）
        2. 验证这些数据，如果都通过则完成
        3. 如果验证通过数不足，则逐条获取后续数据直到满足需求
        
        Args:
            cache_key: 缓存键名
        """
        with cls._background_update_lock(cache_key) as lock_acquired:
            if not lock_acquired:
                logger.info(f"缓存 {cache_key} 已有其他worker在更新，跳过此次更新请求")
                return

            await cls._update_cache_background_locked(cache_key)

    @classmethod
    async def _update_cache_background_locked(cls, cache_key: str):
        # 首先标记缓存为正在更新状态
        with cls._cache_locks[cache_key]:
            if cls._cache[cache_key]["building"].get("is_updating", False):
                logger.info(f"缓存 {cache_key} 已经在更新中，跳过此次更新请求")
                return
            cls._cache[cache_key]["building"]["is_updating"] = True
        
        logger.debug(f"开始在后台异步构建新缓存: {cache_key}")
        
        try:
            # 获取配置
            config = cls._cache_config.get(cache_key, {})
            # 前端展示数量，默认为4
            display_size = 4
            # 实际预加载数量，为展示数量+2（预留），通常为6
            preload_size = config.get("preload_size", display_size + 2)
            
            # 已验证通过的概念
            valid_concepts = []
            # 用于去重的集合，存储已处理的概念名称
            processed_names = set()
            # 当前处理的数据库偏移量
            current_offset = 0
            # 每次获取的批次大小（按需增加）
            batch_size = display_size
            
            # 循环直到获取足够的有效概念或没有更多数据
            while len(valid_concepts) < display_size:
                # 获取一批概念数据（指定偏移量）
                concepts = await cls._fetch_concepts_batch(batch_size, current_offset)
                
                # 如果没有获取到数据，结束循环
                if not concepts:
                    logger.warning(f"[后台] 没有更多概念数据可用，当前有效概念数: {len(valid_concepts)}")
                    break
                
                logger.debug(f"[后台] 获取了 {len(concepts)} 条概念(偏移量:{current_offset})，开始验证")
                
                # 验证这一批概念
                for concept in concepts:
                    # 更新偏移量
                    current_offset += 1
                    
                    concept_name = concept.get("concept_name", "")
                    if not concept_name:
                        continue
                    
                    # 检查是否已处理过相同名称的概念（去重）
                    if concept_name in processed_names:
                        logger.debug(f"[后台] 跳过重复概念: '{concept_name}'")
                        continue
                    
                    # 添加到已处理集合
                    processed_names.add(concept_name)

                    normalized_concept = cls._normalize_concept_for_cache(concept)
                    if not normalized_concept:
                        logger.debug(f"[后台] 概念 '{concept_name}' 本地过滤，跳过 AI 验证")
                        continue

                    valid_concepts.append(normalized_concept)
                    logger.debug(
                        f"[后台] 概念 '{concept_name}' 本地处理为 '{normalized_concept['concept_name']}'，"
                        f"当前有效概念: {len(valid_concepts)}/{display_size}"
                    )
                    if len(valid_concepts) >= display_size:
                        break
                
                # 如果已经获取足够的有效概念或已经处理了太多数据，结束循环
                if len(valid_concepts) >= display_size or current_offset >= 20:
                    break
            
            # 更新缓存
            if valid_concepts:
                # 排序有效概念（按照原始top_num）
                valid_concepts.sort(key=lambda x: x.get("top_num", 0), reverse=True)
                
                # 提交缓存更新
                cls._commit_cache_update(cache_key, valid_concepts)
                logger.debug(f"[后台] 成功更新缓存 {cache_key}, 有效概念数量: {len(valid_concepts)}")
                
                # 安排下次更新
                cls._schedule_next_update(cache_key)
            else:
                logger.warning(f"[后台] 没有找到有效的概念数据，未更新缓存: {cache_key}")
                with cls._cache_locks[cache_key]:
                    cls._cache[cache_key]["building"]["is_updating"] = False
        
        except Exception as e:
            logger.error(f"[后台] 更新缓存过程中出错: {e}")
            logger.error(traceback.format_exc())
            with cls._cache_locks[cache_key]:
                cls._cache[cache_key]["building"]["is_updating"] = False
    
    @classmethod
    async def _fetch_concepts_batch(cls, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
        """
        从数据库获取一批概念数据
        
        Args:
            limit: 获取的记录数量
            offset: 数据库偏移量
            
        Returns:
            概念列表
        """
        try:
            # 使用线程池执行IO密集型操作(数据库查询)
            def fetch_data():
                # 创建一个新的事件循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # 获取数据库连接并查询数据（带偏移量）
                    return loop.run_until_complete(ConceptDAO.get_top_concepts_with_offset(limit, offset))
                finally:
                    loop.close()
            
            # 在独立线程中异步获取数据
            concepts_future = io_executor.submit(fetch_data)
            return await asyncio.wrap_future(concepts_future)
        except Exception as e:
            logger.error(f"获取概念数据批次时出错: {e}")
            return []
    
    @classmethod
    def _schedule_next_update(cls, cache_key: str) -> None:
        """
        计划下一次缓存更新时间
        
        Args:
            cache_key: 缓存键名
        """
        config = cls._cache_config.get(cache_key, {})
        update_hour = config.get("update_hour")
        ttl = config.get("ttl", 3600)
        
        # 计算下次更新时间
        next_update_time = None
        now = datetime.now()
        
        if update_hour is not None:
            # 计算今天的更新时间点
            today_update = now.replace(hour=update_hour, minute=0, second=0, microsecond=0)
            
            # 如果当前时间已经过了今天的更新时间点，则下次更新是明天
            if now >= today_update:
                next_update_time = today_update + timedelta(days=1)
            else:
                next_update_time = today_update
        
        # 同时考虑TTL过期时间
        active_cache = cls._cache.get(cache_key, {}).get("active", {})
        if active_cache and active_cache.get("expires_at"):
            ttl_update_time = datetime.fromtimestamp(active_cache["expires_at"])
            
            # 使用较早的更新时间
            if next_update_time is None or ttl_update_time < next_update_time:
                next_update_time = ttl_update_time
        
        # 如果没有特定更新时间，使用默认TTL
        if next_update_time is None:
            next_update_time = now + timedelta(seconds=ttl)
        
        # 计算从现在到下次更新的秒数
        seconds_until_update = (next_update_time - now).total_seconds()
        
        # 确保不会太短
        seconds_until_update = max(60, seconds_until_update)  # 至少1分钟后更新
        
        logger.info(f"计划下次更新缓存 {cache_key} 时间: {next_update_time.strftime('%Y-%m-%d %H:%M:%S')}, {seconds_until_update:.0f}秒后")
        
        # 启动一个后台任务定时触发更新
        async def delayed_update():
            await asyncio.sleep(seconds_until_update)
            logger.info(f"定时触发缓存更新: {cache_key}")
            # 启动后台更新任务
            asyncio.create_task(cls._update_cache_background(cache_key))
        
        # 创建无阻塞的定时器任务
        asyncio.create_task(delayed_update())
    
    @classmethod
    async def initialize(cls) -> None:
        """
        初始化缓存服务，预热缓存
        使用完全非阻塞方式，类似process_stream接口
        """
        try:
            # 立即标记为已初始化，确保接口可立即响应
            cls._initialized = True
            logger.info("热点监控服务基础初始化完成，可以立即响应请求")
            
            # 初始化缓存锁
            for cache_key in cls._cache:
                if cache_key not in cls._cache_locks:
                    cls._cache_locks[cache_key] = threading.RLock()
            
            # 使用IO线程池获取临时数据
            async def load_temp_data():
                await asyncio.sleep(1)  # 短暂延迟，避免应用启动时负载过高
                
                # 对每个缓存键进行预加载
                for cache_key in cls._cache:
                    try:
                        # 在IO线程池中异步获取临时数据
                        def fetch_temp_data():
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                return loop.run_until_complete(ConceptDAO.get_top_concepts(10))
                            finally:
                                loop.close()
                        
                        # 提交任务到IO线程池
                        future = io_executor.submit(fetch_temp_data)
                        concepts = await asyncio.wrap_future(future)
                        
                        if concepts:
                            # 创建临时缓存
                            temp_cache = cls._create_cache_entry(concepts, 300)  # 临时数据缓存5分钟
                            
                            # 更新活跃缓存
                            with cls._cache_locks[cache_key]:
                                cls._cache[cache_key]["active"] = temp_cache
                            
                            logger.info(f"已加载临时数据到缓存: {cache_key}")
                            
                            # 启动后台缓存更新任务
                            asyncio.create_task(cls._update_cache_background(cache_key))
                            logger.info(f"已启动后台缓存更新任务: {cache_key}")
                    except Exception as e:
                        logger.error(f"加载临时数据时出错: {e}")
            
            # 启动预加载任务，但不等待完成
            asyncio.create_task(load_temp_data())
            logger.info("热点监控服务初始化完成，临时数据加载任务已在后台启动")
            
        except Exception as e:
            logger.error(f"初始化热点监控服务时出错: {e}")
            logger.error(traceback.format_exc())
            # 即使出错，也设置初始化完成标志
            cls._initialized = True
    
    @classmethod
    async def get_top_concepts(cls, limit: int = 4) -> List[Dict[str, Any]]:
        """
        获取热门金融概念数据，按照热度（top_num）排序
        
        使用完全非阻塞的方式：
        - 永远立即响应请求，不会阻塞
        - 缓存更新在完全独立的进程中进行
        - 读取操作与验证/更新操作完全隔离
        - 确保返回数据不包含重复的概念名称
        
        Args:
            limit: 返回的记录数量限制，默认为4
            
        Returns:
            热门概念列表
        """
        cache_key = "top_concepts"
        
        # 从活跃缓存读取数据，确保立即返回
        active_cache = cls._cache.get(cache_key, {}).get("active", {})
        active_data = active_cache.get("data")
        
        # 如果有缓存数据，立即返回
        if active_data:
            # 如果需要更新缓存，触发后台更新（不等待）
            if cls._should_update_cache(cache_key):
                # 确保不重复触发更新
                with cls._cache_locks[cache_key]:
                    building_updating = cls._cache[cache_key]["building"].get("is_updating", False)
                if not building_updating:
                    # 创建后台任务进行缓存更新
                    asyncio.create_task(cls._update_cache_background(cache_key))
                    logger.info("已触发后台缓存更新，当前请求使用现有缓存数据")
            
            # 记录缓存状态
            cache_age = time.time() - active_cache.get("timestamp", 0)
            expired = time.time() > active_cache.get("expires_at", 0)
            logger.info(f"使用缓存数据，年龄: {cache_age:.1f}秒" + (", 已过期但仍在使用" if expired else ""))
            
            # 确保数据无重复并裁剪
            return cls._deduplicate_concepts(active_data, limit)
        
        # 如果没有缓存数据，快速获取临时数据
        logger.warning("缓存为空，获取临时数据")
        
        # 触发后台更新（如果未在更新中）
        with cls._cache_locks[cache_key]:
            building_updating = cls._cache[cache_key]["building"].get("is_updating", False)
        if not building_updating:
            asyncio.create_task(cls._update_cache_background(cache_key))
            logger.info("已触发后台缓存构建")
        
        try:
            # 直接从数据库获取临时数据
            concepts = await ConceptDAO.get_top_concepts(limit)
            
            if concepts:
                logger.info(f"获取到 {len(concepts)} 条临时数据")
                
                # 去重处理
                unique_concepts = cls._deduplicate_concepts(concepts, limit)
                
                # 在后台任务中更新临时缓存
                async def update_temp_cache():
                    try:
                        temp_cache = cls._create_cache_entry(unique_concepts, 60)
                        with cls._cache_locks[cache_key]:
                            if not cls._cache[cache_key]["active"].get("data"):
                                cls._cache[cache_key]["active"] = temp_cache
                                logger.info("已更新临时缓存")
                    except Exception as e:
                        logger.error(f"更新临时缓存时出错: {e}")
                
                # 启动后台任务
                asyncio.create_task(update_temp_cache())
                
                # 立即返回去重后的数据
                return unique_concepts
            else:
                logger.warning("数据库中未找到数据")
                return []
        except Exception as e:
            logger.error(f"获取临时数据时出错: {e}")
            return []
            
    @staticmethod
    def _deduplicate_concepts(concepts: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """
        去除概念列表中的重复项，并按照热度排序后返回前limit条
        
        Args:
            concepts: 概念列表
            limit: 返回数量限制
            
        Returns:
            去重后的概念列表
        """
        if not concepts:
            return []
            
        # 使用字典去重，保留每个概念名称对应的第一个（热度最高）记录
        unique_concepts = {}
        for concept in concepts:
            normalized_concept = HotspotService._normalize_concept_for_cache(concept)
            if not normalized_concept:
                continue

            name = normalized_concept.get("concept_name", "")
            if name and name not in unique_concepts:
                unique_concepts[name] = normalized_concept
        
        # 转换回列表并排序
        result = list(unique_concepts.values())
        result.sort(key=lambda x: x.get("top_num", 0), reverse=True)
        
        # 裁剪到所需数量
        return result[:limit] if limit else result
