import os
import json
import yaml
import asyncio
from datetime import datetime, timedelta
import time
import requests
from openai import OpenAI
from urllib.parse import urlparse
import re
import html
from playwright.async_api import async_playwright
from utils.logger import get_logger
from services.crawler_service import Crawler, log_message
from services.jina_search_service import JinaSearcher
from services.baidu_search_service import BaiduSearcher
from services.industry_storage_service import IndustryStorageService
from services.industry_structure_service import IndustryStructureService
from services.oss_service import OssService  # 导入OSS服务
from services.optimized_report_orchestrator import OptimizedReportOrchestrator
from services.global_managers import get_global_key_manager, get_global_jina_searcher
from services.accurate_token_calculator import calculate_jina_search_tokens, calculate_jina_reader_tokens
 
from lxml import etree
from concurrent.futures import ThreadPoolExecutor
import redis

# 全局线程池，用于执行同步API调用
_executor = ThreadPoolExecutor(max_workers=4)

logger = get_logger(__name__)

AI_NAME_TIMEOUT_SECONDS = 90

INDUSTRY_NAME_KEYS = (
    'industry_name',
    'industry',
    'output',
    'result',
    'industry_keyword',
    '产业关键词',
    'processed_content',
    'retained_content',
    'retained',
)

INVALID_INDUSTRY_NAME_VALUES = {
    '',
    '{}',
    '[]',
    'null',
    'none',
    '""',
    "''",
    '{"result": ""}',
    '{"result":""}',
    '{"retained": ""}',
    '{"retained":""}',
    '{"retained_content": ""}',
    '{"retained_content":""}',
    '{"output": ""}',
    '{"output":""}',
    '{"industry": ""}',
    '{"industry":""}',
}

EXPLANATION_NAME_MARKERS = (
    '包含具体产业名称',
    '符合可检索',
    '实体产品标准',
    '保留标准',
    '排除标准',
    '匹配原因',
    '处理流程',
    '核心产业名称',
    '清理后的产业链名称',
    'JSON',
)

FILLER_NAME_CHARS = set('哈啊哦嗯呃呀啦嘛呢')


def _strip_industry_name_text(value) -> str:
    """Normalize a model-produced industry name candidate."""
    if value is None:
        return ''

    text = str(value).replace('data:', '').strip()
    text = text.replace('```json', '').replace('```', '').strip()

    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()

    prefix_pairs = (
        ('输出："', '"'),
        ('output:"', '"'),
        ('输出：', ''),
        ('output:', ''),
        ('结果：', ''),
        ('result:', ''),
    )
    for prefix, suffix in prefix_pairs:
        if text.startswith(prefix):
            text = text[len(prefix):]
            if suffix and text.endswith(suffix):
                text = text[:-len(suffix)]
            text = text.strip()
            break

    return text.strip().strip('"\'').strip()


def _looks_like_invalid_industry_name(value: str) -> bool:
    if value is None:
        return True

    name = _strip_industry_name_text(value)
    compact = name.strip().lower()

    if compact in INVALID_INDUSTRY_NAME_VALUES:
        return True
    if not name:
        return True
    if len(name) <= 1:
        return True
    if all(ch in FILLER_NAME_CHARS for ch in name):
        return True
    if name.isdigit():
        return True
    if name.startswith('{') or name.endswith('}'):
        return True
    if '\n' in name or '\r' in name:
        return True
    if any(marker in name for marker in EXPLANATION_NAME_MARKERS):
        return True
    if len(name) > 50:
        return True
    if re.search(r'(原因|理由|标准|符合|不符合|输入|输出|返回|分析|判断|任务|示例|流程)', name):
        return True

    return False


def extract_industry_name_from_ai_response(raw_content, original_input: str, user_id=None) -> str:
    """
    Extract a safe industry name from model output.

    The parser intentionally does not fall back to the first arbitrary JSON
    string value, because explanatory text can otherwise pollute chain names.
    """
    original_name = _strip_industry_name_text(original_input)

    if raw_content is None:
        return original_name if not _looks_like_invalid_industry_name(original_name) else None

    cleaned = str(raw_content).replace('data:', '').strip()
    candidate = None

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            for key in INDUSTRY_NAME_KEYS:
                value = parsed.get(key)
                if value is not None and str(value).strip():
                    candidate = _strip_industry_name_text(value)
                    break

            if candidate is None:
                log_message(user_id, "AI返回JSON未包含受支持的产业链名称字段，使用原始输入兜底", log_type="WARNING")
        elif isinstance(parsed, str):
            candidate = _strip_industry_name_text(parsed)
    except (json.JSONDecodeError, TypeError, ValueError):
        candidate = _strip_industry_name_text(cleaned)

    if candidate and not _looks_like_invalid_industry_name(candidate):
        return candidate

    if candidate:
        log_message(user_id, f"AI返回的产业链名称候选无效: {candidate[:120]}，使用原始输入", log_type="WARNING")

    if original_name and not _looks_like_invalid_industry_name(original_name):
        return original_name

    return None


async def deduplicate_content(content: str, user_id: str = None) -> str:
    """
    对内容进行智能去重处理，移除重复的段落和模板内容
    改进策略：
    1. 过滤PDF模板和boilerplate内容（版权、免责声明等）
    2. 使用句子级别的去重而非段落级别
    3. 设置最小保留比例（50%），避免过度去重

    Args:
        content: 原始内容
        user_id: 用户ID（用于日志）

    Returns:
        去重后的内容
    """
    if not content or len(content) == 0:
        return content

    original_size = len(content.encode('utf-8')) / 1024
    original_paragraphs = len(content.split('\n'))
    original_chars = len(content)
    log_message(user_id, f"开始智能内容去重，原始大小: {original_size:.2f} KB, 段落数: {original_paragraphs}", log_type="INFO")

    # 1. 预过滤：移除PDF模板和boilerplate内容
    lines = content.split('\n')
    filtered_lines = []
    template_patterns = [
        'number of pages', 'markdown content:', 'pdf', 'doc2.askci.com',
        '扫一扫领取', '免费报告', '中商产业研究院', 'askci consulting',
        '版权声明', '免责声明', '侵权责任', '报告版权归',
        'source:', 'published time:', 'url source:'
    ]

    template_count = 0
    for line in lines:
        line_lower = line.lower().strip()
        # 跳过空行
        if not line.strip():
            continue
        # 跳过模板行
        is_template = any(pattern in line_lower for pattern in template_patterns)
        # 跳过纯符号行（如****、----等）
        is_symbol_line = len(line.strip()) > 0 and all(c in '*- \t' for c in line.strip())
        # 跳过太短的模板行（如单个字符或数字）
        is_short_template = len(line.strip()) <= 2 and not any(c.isalpha() for c in line.strip())

        if is_template or is_symbol_line or is_short_template:
            template_count += 1
            continue
        filtered_lines.append(line)

    log_message(user_id, f"预过滤完成: 移除 {template_count} 个模板行", log_type="DEBUG")

    # 2. 合并短段落以提高去重效果
    merged_paragraphs = []
    current_para = ""

    for line in filtered_lines:
        stripped = line.strip()
        if not stripped:
            if current_para:
                merged_paragraphs.append(current_para)
                current_para = ""
            continue

        # 如果当前行很短（<50字符），尝试与下一行合并
        if len(stripped) < 50:
            current_para = f"{current_para} {stripped}" if current_para else stripped
        else:
            if current_para:
                merged_paragraphs.append(current_para)
            current_para = stripped

    # 添加最后一个段落
    if current_para:
        merged_paragraphs.append(current_para)

    log_message(user_id, f"段落合并后数量: {len(merged_paragraphs)}", log_type="DEBUG")

    # 3. 智能去重：使用更宽松的去重策略
    unique_paragraphs = []
    seen_content = set()
    duplicate_count = 0

    # 定义去重阈值：只去除高度相似（>90%相同）的内容
    for para in merged_paragraphs:
        # 清理段落
        cleaned_para = ' '.join(para.split())
        if not cleaned_para:
            continue

        # 计算段落指纹（基于前100个字符和长度）
        fingerprint = (cleaned_para[:100].lower(), len(cleaned_para))
        if fingerprint not in seen_content:
            seen_content.add(fingerprint)
            unique_paragraphs.append(para)
        else:
            duplicate_count += 1
            if duplicate_count <= 3:
                preview = cleaned_para[:50] + "..." if len(cleaned_para) > 50 else cleaned_para
                log_message(user_id, f"发现重复段落 {duplicate_count}: {preview}", log_type="DEBUG")

    # 4. 重新组合
    deduplicated = '\n'.join(unique_paragraphs)
    final_size = len(deduplicated.encode('utf-8')) / 1024
    reduction = (1 - final_size / original_size) * 100 if original_size > 0 else 0

    # 5. 如果去重过度（保留<50%），使用更保守的策略
    min_retention_ratio = 0.5  # 最小保留50%
    actual_ratio = final_size / original_size if original_size > 0 else 1

    if actual_ratio < min_retention_ratio:
        log_message(user_id, f"警告: 去重后仅保留 {actual_ratio*100:.1f}%，使用保守策略重新去重", log_type="WARNING")

        # 使用更宽松的去重：只去除完全相同的段落
        seen_exact = set()
        conservative_paragraphs = []
        for para in merged_paragraphs:
            cleaned = ' '.join(para.split()).strip()
            if not cleaned:
                continue
            # 完全相同的才去除
            if cleaned.lower() not in seen_exact:
                seen_exact.add(cleaned.lower())
                conservative_paragraphs.append(para)

        deduplicated = '\n'.join(conservative_paragraphs)
        final_size = len(deduplicated.encode('utf-8')) / 1024
        reduction = (1 - final_size / original_size) * 100 if original_size > 0 else 0
        final_paragraphs = len(conservative_paragraphs)
    else:
        final_paragraphs = len(unique_paragraphs)

    log_message(user_id, f"智能去重完成: 去重后大小 {final_size:.2f} KB (减少 {reduction:.1f}%), 保留比例 {100-reduction:.1f}%", log_type="INFO")
    log_message(user_id, f"去重统计: 原始段落 {original_paragraphs}, 去重后段落 {final_paragraphs}, 移除重复 {duplicate_count + template_count} 个", log_type="INFO")

    return deduplicated


# 添加Redis缓存
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# 全局浏览器管理
_global_browser = None
_browser_lock = asyncio.Lock()


async def get_shared_browser():
    global _global_browser
    async with _browser_lock:
        if _global_browser is None:
            p = await async_playwright().start()
            _global_browser = await p.firefox.launch(headless=True)
    return _global_browser

# 批量搜索器类
class BatchJinaSearcher:
    def __init__(self, api_url, headers, batch_size=5):
        self.api_url = api_url
        self.headers = headers
        self.batch_size = batch_size
    
    async def batch_search(self, search_queries, user_id=None):
        """批量执行搜索请求"""
        results = []
        for i in range(0, len(search_queries), self.batch_size):
            batch = search_queries[i:i + self.batch_size]
            batch_tasks = []
            
            for query in batch:
                jina_searcher = JinaSearcher(
                    self.api_url, 
                    self.headers, 
                    query['industry_name'],
                    default_sites=query.get('sites')
                )
                task = jina_searcher.jina_search(
                    limit=query.get('limit', 6),
                    isNode=query.get('isNode', False),
                    node=query.get('node', ''),
                    user_id=user_id
                )
                batch_tasks.append(task)
            
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            results.extend(batch_results)
            
            # 批次间短暂延迟避免API限制
            await asyncio.sleep(1)
        
        return results

# 读取项目配置文件
with open("config/settings_show.yaml", "r") as file:
    settings = yaml.load(file, Loader=yaml.FullLoader)

# headers = settings['system_settings']['headers']
# google_api_url = settings['system_settings']['google_api_url']
deepseek_api_key = settings['system_settings']['deepseek_api_key']
deepseek_url = settings['system_settings']['deepseek_url']
input_clean_prompts = settings['prompts']['input_clean']['content']
clean_info_prompts = settings['prompts']['clean_info']['content']
clean_node_info_prompts = settings['prompts']['clean_node_info']['content']
words_from_ocr_prompts = settings['prompts']['words_from_ocr']['content']
get_entity_prompts = settings['prompts']['get_entity']['content']
jina_api_url = settings['system_settings']['jina_api_url']
jina_api_headers = settings['system_settings']['jina_api_headers']
jina_api_keys = settings['system_settings']['jina_api_keys']
jina_api_headers_template = settings['system_settings']['jina_api_headers_template']
get_triples_prompts = settings['prompts']['get_triples']['content']
check_triples_prompts = settings['prompts']['check_triples']['content']
modify_triples_prompts = settings['prompts']['modify_triples']['content']


client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)


# 初始化OSS服务
oss_service = OssService()

# 处理用户输入产业链名称
async def process_input_industry(input_clean_prompts, raw_content, user_id, send_message):
    try:
        # 如果输入内容过长，进行截断
        max_length = 65536
        if len(raw_content) > max_length:
            raw_content = raw_content[:max_length]
            log_message(user_id, "输入内容过长，已截断", log_type="WARNING")

        # 构造消息
        messages = [
            {"role": "system", "content": input_clean_prompts + "\n请以json格式返回结果。"},
            {"role": "user", "content": raw_content}
        ]
        
        try:
            # 在线程池中调用API，避免阻塞事件循环
            def call_api():
                client_sync = OpenAI(
                    api_key=os.getenv("DASHSCOPE_API_KEY"),
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                )
                return client_sync.chat.completions.create(
                    model="deepseek-v4.1-flash",
                    messages=messages,
                    temperature=0.6,
                    response_format={"type": "json_object"}
                )

            loop = asyncio.get_running_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(_executor, call_api),
                timeout=AI_NAME_TIMEOUT_SECONDS
            )

            content = response.choices[0].message.content
            content = extract_industry_name_from_ai_response(content, raw_content, user_id)
            if not content:
                error_msg = "无法提取有效的产业链名称，请检查输入内容"
                log_message(user_id, error_msg, log_type="ERROR")
                await send_message(error_msg, "Error")
                return None

            content_preview = content[:500]

            # 将日志信息发送给用户
            await send_message(f"结果:{content_preview}", "3")

            return content
        except AttributeError as e:
            # 处理可能的属性错误
            log_message(user_id, f"AttributeError in model response: {e}", log_type="ERROR")
            if hasattr(response, 'choices') and hasattr(response.choices[0], 'message'):
                content = response.choices[0].message.content
                log_message(user_id, f"尽管有错误，仍然获取到内容，长度: {len(content)}")
                await send_message(f"{content[:500]}...", "Result")
                return content
            else:
                log_message(user_id, f"无法从响应中获取内容: {e}", log_type="ERROR")
                raise e
        except asyncio.TimeoutError:
            log_message(user_id, f"AI调用超时（{AI_NAME_TIMEOUT_SECONDS}秒）", log_type="ERROR")
            await send_message("AI调用超时，请稍后重试", "Error")
            return None
        except Exception as e:
            log_message(user_id, f"调用模型时发生错误: {e}", log_type="ERROR")
            await send_message(f"{e}", "Error")
            raise e
    except Exception as e:
        log_message(user_id, f"Error in process_industry_data: {e}", log_type="ERROR")
        # 将错误信息发送给用户
        await send_message(f"{e}", "Error")
        return None
    
# 处理行业数据
async def process_industry_data(clean_info_prompts, raw_content, user_id, send_message, cancel_flag=None):
    
    # 确保send_message函数可用 - 修复 'NoneType' object is not callable 错误
    if send_message is None:
        # 创建一个空操作函数作为后备
        async def send_message(message, message_type):
            log_message(user_id, f"[{message_type}] {message}", log_type="INFO")

    # 检查是否已取消
    if cancel_flag and cancel_flag.is_set():
        log_message(user_id, "操作已取消（process_industry_data初始阶段）", log_type="WARNING")
        return None

    # 构建消息
    messages = [
        {"role": "system", "content": "你是一个产业链分析专家。请根据用户提供的信息，按照指定的格式进行分析。请以json格式返回结果。"},
        {"role": "user", "content": f"{clean_info_prompts}\n\n{raw_content}"}
    ]

    # 智能重试机制
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            # 检查是否已取消
            if cancel_flag and cancel_flag.is_set():
                log_message(user_id, "操作已取消（API调用前）", log_type="WARNING")
                return None
        
            # 使用阿里云百炼密钥创建客户端（同步版本）
            # OpenAI 已在文件顶部导入

            # 创建一个同步客户端用于执行器
            def call_api():
                client_sync = OpenAI(
                    api_key=os.getenv("DASHSCOPE_API_KEY"),
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                )
                return client_sync.chat.completions.create(
                    model="deepseek-v4.1-flash",
                    messages=messages,
                    temperature=0.6,
                    response_format={"type": "json_object"}
                )

            log_message(user_id, f"🔑 使用阿里云百炼密钥，第 {attempt + 1}/{max_attempts} 次尝试", log_type="INFO")

            # 记录输入内容大小，便于调试
            content_size = len(raw_content.encode('utf-8')) / 1024
            log_message(user_id, f"📊 输入内容大小: {content_size:.1f} KB", log_type="DEBUG")

            # 根据内容大小动态调整超时时间
            # 小内容（<10KB）: 120秒, 中等内容（10-50KB）: 180秒, 大内容（>50KB）: 300秒
            if content_size < 10:
                timeout_seconds = 120
            elif content_size < 50:
                timeout_seconds = 180
            else:
                timeout_seconds = 300

            # 使用全局线程池运行API调用，避免事件循环问题
            loop = asyncio.get_running_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(_executor, call_api),
                timeout=timeout_seconds
            )
            
            # 获取模型的输出内容和思维链内容
            try:
                reasoning_content = response.choices[0].message.reasoning_content
                content = response.choices[0].message.content

                # 记录思维链内容到日志
                log_message(user_id, f"Reasoning Content: {reasoning_content}", log_type="DEBUG")

                # 处理思维链内容，确保每一行都有"data:"前缀
                formatted_content = f"{reasoning_content.strip()}"

                # 将日志信息发送给用户 - 确保send_message可用
                try:
                    await send_message(formatted_content, "4")
                except Exception as e:
                    log_message(user_id, f"发送消息失败: {e}", log_type="WARNING")

                # 清理内容中可能存在的"data:"前缀
                content_preview = content.replace("data:", "").strip()

                # 将日志信息发送给用户 - 确保send_message可用
                try:
                    await send_message(f"结果:{content_preview}", "3")
                except Exception as e:
                    log_message(user_id, f"发送消息失败: {e}", log_type="WARNING")
                
                return content
            except AttributeError:
                # 如果没有reasoning_content，直接获取content
                content = response.choices[0].message.content
                
                # 清理内容中可能存在的"data:"前缀
                content_preview = content.replace("data:", "").strip()
                
                # 记录内容到日志
                log_message(user_id, f"获取到内容（无思维链），长度: {len(content)}")
                # 将日志信息发送给用户
                await send_message(f"结果:{content_preview}", "3")
                return content

        except asyncio.TimeoutError:
            log_message(user_id, f"阿里云百炼API调用超时（{timeout_seconds}秒），第{attempt + 1}次尝试失败", log_type="WARNING")
            if attempt == max_attempts - 1:
                await send_message("阿里云百炼API调用超时，请稍后重试", "Error")
                return None
        except Exception as e:
            error_msg = str(e).lower()

            # 智能错误处理
            if "429" in error_msg or "rate limit" in error_msg:
                log_message(user_id, f"🚫 阿里云百炼API达到速率限制", log_type="WARNING")
            elif "401" in error_msg or "unauthorized" in error_msg:
                log_message(user_id, f"🔐 阿里云百炼API密钥无效", log_type="WARNING")
            elif "402" in error_msg or "payment" in error_msg:
                log_message(user_id, f"💳 阿里云百炼API余额不足", log_type="WARNING")
            else:
                log_message(user_id, f"❌ 阿里云百炼API调用异常: {e}", log_type="ERROR")

            if attempt == max_attempts - 1:
                log_message(user_id, f"调用阿里云百炼模型时发生错误，已达最大重试次数: {e}", log_type="ERROR")
                await send_message(f"阿里云百炼模型调用失败: {str(e)}", "Error")
                return None
            
            # 指数退避延迟
            await asyncio.sleep(min(2 ** attempt, 10))

    return None

async def tool_search_with_enhanced_cache(industry_name, custom_urls=None, isNode=False, node="", **kwargs):
    """带增强缓存的搜索函数"""
    user_id = kwargs.get('user_id')
    cancel_flag = kwargs.get('cancel_flag')
    
    # 检查是否已取消
    if cancel_flag and cancel_flag.is_set():
        log_message(user_id, "操作已取消（缓存搜索初始阶段）", log_type="WARNING")
        return '无内容', []
    
    # 生成缓存键
    cache_key = f"search:{industry_name}:{node}:{hash(str(custom_urls))}"
    
    # 尝试从Redis获取缓存
    try:
        cached_result = redis_client.get(cache_key)
        if cached_result:
            log_message(user_id, f"🎯 使用缓存结果: {cache_key[:50]}...", log_type="INFO")
            cached_data = json.loads(cached_result)
            # 返回缓存的内容和文章数据
            return cached_data.get('content', '无内容'), cached_data.get('articles', [])
    except Exception as e:
        log_message(user_id, f"缓存读取失败: {e}", log_type="WARNING")
    
    # 执行搜索
    try:
        result, articles = await tool_search(industry_name, custom_urls, isNode, node, **kwargs)
    
        # 检查搜索结果
        if result is None or result == '无内容':
            log_message(user_id, f"搜索未返回有效结果: {industry_name}", log_type="WARNING")
            return '无内容', []
    
        # 优化缓存策略（2小时有效期，减少重复搜索）
        try:
            if result and result != '无内容':
                cache_data = {
                    'content': result,
                    'articles': articles,
                    'timestamp': time.time()
                }
                redis_client.setex(cache_key, 7200, json.dumps(cache_data, ensure_ascii=False))  # 2小时缓存
                log_message(user_id, f"💾 缓存搜索结果和文章数据: {cache_key[:50]}...", log_type="INFO")
        except Exception as e:
                log_message(user_id, f"缓存写入失败: {e}", log_type="WARNING")
    
        return result, articles
        
    except Exception as e:
        log_message(user_id, f"❌ 缓存搜索异常: {str(e)}", log_type="ERROR")
    return '无内容', []

# 工具函数：搜索行业信息
async def tool_search(industry_name, custom_urls=None, isNode=False, node="", isAux=True, user_id=None, send_message=None, sites=None, cancel_flag=None):

    # 检查是否已取消
    if cancel_flag and cancel_flag.is_set():
        log_message(user_id, f"搜索已被取消: {industry_name}", log_type="INFO")
        return '无内容', []
    
    original_industry_name = industry_name
    
    # 如果是节点搜索，使用"产业链名称 + 节点名称"作为搜索关键词
    if isNode and node:
        search_keyword = f"{industry_name} {node}"
        log_message(user_id, f"🔍 节点搜索模式: 使用 '{search_keyword}' 作为搜索关键词", log_type="INFO")
    else:
        search_keyword = industry_name

    # 搜索相关信息
    try:
        # 1. 优先尝试Jina搜索
        search_success = False
        raw_content = None
        
        if sites and len(sites) > 0:
            # 使用指定的搜索源
            for site in sites:
                if cancel_flag and cancel_flag.is_set():
                    log_message(user_id, f"搜索已被取消: {search_keyword}", log_type="INFO")
                    return '无内容', []

                try:
                    log_message(user_id, f"🔍 使用{site}搜索: {search_keyword}", log_type="INFO")

                    # 搜索时添加"产业链"后缀以提高搜索质量
                    search_term = f"{search_keyword} 产业链"
                    log_message(user_id, f"📝 搜索关键词: {search_term}", log_type="DEBUG")

                    # 支持中英文站点名映射
                    site_mapping = {
                        "中商情报网": "site:askci.com",
                        "askci.com": "site:askci.com",
                        "前瞻网": "site:qianzhan.com",
                        "qianzhan.com": "site:qianzhan.com",
                        "艾瑞网": "site:iresearch.cn",
                        "iresearch.cn": "site:iresearch.cn",
                        "易观网": "site:analysys.cn",
                        "analysys.cn": "site:analysys.cn",
                    }

                    if site in site_mapping:
                        site_name = site if site in ["中商情报网", "前瞻网", "艾瑞网", "易观网"] else (
                            "中商���报网" if site_mapping[site] == "site:askci.com" else
                            "前瞻网" if site_mapping[site] == "site:qianzhan.com" else
                            "艾瑞网" if site_mapping[site] == "site:iresearch.cn" else "易观网"
                        )
                        
                        # 先尝试百度搜索
                        searcher = BaiduSearcher()
                        raw_content = await searcher.search_with_site(search_term, site_mapping[site])
                        log_message(user_id, f"📊 {site_name}(百度)搜索结果: type={type(raw_content)}, has_results={raw_content and raw_content.get('results') is not None}", log_type="DEBUG")
                        
                        
                        if raw_content and raw_content.get('results'):
                            search_success = True
                            break
                        else:
                            log_message(user_id, f"⚠️ {site_name}所有搜索方式均无结果", log_type="WARNING")
                    elif site == "通用搜索":
                        searcher = BaiduSearcher()
                        raw_content = await searcher.search(search_term)
                        if raw_content and raw_content.get('results'):
                            search_success = True
                            break
                    else:
                        # 未知站点，尝试作为通用搜索
                        log_message(user_id, f"⚠️ 未知站点 '{site}'，尝试通用搜索", log_type="WARNING")
                        searcher = BaiduSearcher()
                        raw_content = await searcher.search(search_term)
                        if raw_content and raw_content.get('results'):
                            search_success = True
                            break
                
                except Exception as e:
                    log_message(user_id, f"⚠️ {site}搜索异常: {e}", log_type="WARNING")
                    # 检查是否是API余额不足
                    if "402" in str(e) or "payment required" in str(e).lower():
                        log_message(user_id, f"❌ API余额不足，停止所有搜索", log_type="ERROR")
                        return '无内容', []
        else:
            # 默认搜索策略
            try:
                log_message(user_id, f"🔍 百度搜索: {search_keyword}", log_type="INFO")
                searcher = BaiduSearcher()
                raw_content = await searcher.search(search_keyword)
                
                if raw_content and raw_content.get('results'):
                    search_success = True
                else:
                    log_message(user_id, f"🔄 尝试备用搜索策略...", log_type="INFO")
                    # 尝试不同的搜索词
                    search_terms = [
                        f"{search_keyword}产业链",
                        f"{search_keyword}行业分析",
                        f"{search_keyword}市场研究"
                    ]
                    
                    for term in search_terms:
                        if cancel_flag and cancel_flag.is_set():
                            return '无内容', []
                        
                        try:
                            raw_content = await searcher.search(term)
                            if raw_content and raw_content.get('results'):
                                search_success = True
                                break
                        except Exception as e:
                            log_message(user_id, f"⚠️ 备用搜索词 '{term}' 失败: {e}", log_type="WARNING")
                            # 检查是否是API余额不足
                            if "402" in str(e) or "payment required" in str(e).lower():
                                log_message(user_id, f"❌ API余额不足，停止所有搜索", log_type="ERROR")
                                return '无内容', []
                    
            except Exception as e:
                log_message(user_id, f"⚠️ Jina搜索异常: {e}", log_type="WARNING")
                # 检查是否是API余额不足
                if "402" in str(e) or "payment required" in str(e).lower():
                    log_message(user_id, f"❌ API余额不足，停止所有搜索", log_type="ERROR")
                    return '无内容', []
            
            # 2. 如果Jina失败，尝试通用搜索
            if not search_success:
                try:
                    log_message(user_id, f"🔄 尝试通用搜索: {search_keyword}", log_type="INFO")
                    searcher = BaiduSearcher()
                    raw_content = await searcher.search(f"{search_keyword} 产业链分析")
                    if raw_content and raw_content.get('results'):
                        search_success = True
                except Exception as e:
                    log_message(user_id, f"⚠️ 通用搜索异常: {e}", log_type="WARNING")
                    # 检查是否是API余额不足
                    if "402" in str(e) or "payment required" in str(e).lower():
                        log_message(user_id, f"❌ API余额不足，停止所有搜索", log_type="ERROR")
                        return '无内容', []

            # 3. 尝试更多搜索关键词（针对技术类、产业类关键词）
            if not search_success:
                log_message(user_id, f"🔄 尝试扩展搜索关键词...", log_type="INFO")
                extended_search_terms = [
                    f"{search_keyword} 产业",
                    f"{search_keyword} 行业",
                    f"{search_keyword} 发展前景",
                    f"{search_keyword} 市场规模",
                ]
                for term in extended_search_terms:
                    if cancel_flag and cancel_flag.is_set():
                        return '无内容', []
                    try:
                        searcher = BaiduSearcher()
                        raw_content = await searcher.search(term)
                        if raw_content and raw_content.get('results'):
                            search_success = True
                            log_message(user_id, f"✅ 扩展搜索成功: {term}", log_type="INFO")
                            break
                    except Exception as e:
                        log_message(user_id, f"⚠️ 扩展搜索词 '{term}' 失败: {e}", log_type="WARNING")

            # 4. 尝试不带site限制的通用搜索
            if not search_success:
                log_message(user_id, f"🔄 尝试全网搜索...", log_type="INFO")
                try:
                    searcher = BaiduSearcher()
                    # 不限制特定网站，使用通用搜索
                    raw_content = await searcher.search(f"{search_keyword} 产业链 行业分析 发展前景 市场规模")
                    if raw_content and raw_content.get('results'):
                        search_success = True
                        log_message(user_id, f"✅ 全网搜索成功", log_type="INFO")
                except Exception as e:
                    log_message(user_id, f"⚠️ 全网搜索异常: {e}", log_type="WARNING")

            # 5. 如果所有搜索都失败，直接返回无内容，不生成fallback
            if not search_success:
                log_message(user_id, f"❌ 所有搜索策略都失败了，关键词: {search_keyword}", log_type="ERROR")
                return '无内容', []

        # 处理搜索结果
        urls = []
        titles = {}

        # URL黑名单 - 只排除真正的二进制文件，Jina Reader可以读取PDF/DOC等格式
        url_blacklist = ['.zip', '.rar', '.mp4', '.mp3', '.exe', '.dmg', '.pkg', '.bin', '.iso']

        def is_crawlable_url(url):
            """检查URL是否可以直接爬取（排除真正的二进制文件下载链接）"""
            url_lower = url.lower()
            for ext in url_blacklist:
                if url_lower.endswith(ext):
                    return False
            return True

        if isinstance(raw_content, dict):
            urls = [r['url'] for r in raw_content.get('results', []) if 'url' in r and is_crawlable_url(r['url'])]
            titles = {r['url']: r.get('title') for r in raw_content.get('results', []) if 'url' in r and is_crawlable_url(r['url'])}
            log_message(user_id, f"📊 处理搜索结果: {len(raw_content.get('results', []))} 个原始结果, 提取到 {len(urls)} 个有效URL", log_type="DEBUG")
        elif isinstance(raw_content, list):
            urls = [r['url'] for r in raw_content if 'url' in r and is_crawlable_url(r['url'])]
            titles = {r['url']: r.get('title') for r in raw_content if 'url' in r and is_crawlable_url(r['url'])}
            log_message(user_id, f"📊 处理搜索结果: {len(raw_content)} 个原始结果, 提取到 {len(urls)} 个有效URL", log_type="DEBUG")
        
        if custom_urls:
            urls.extend(custom_urls)

        # 保存URL列表
        with open(f"materials/url_list_{original_industry_name}.txt", 'a') as f:
            f.write(f"搜索词: {industry_name}\n")
            f.write('\n'.join(urls) + '\n\n')

        # 结果收集器
        results = []
        url_status = []
        collected_articles = []

        # 内容验证函数
        def is_valid_content(content):
            if not content or content['status'] == 'error':
                return False
            
            text_content = content.get('content', '')
            if not text_content or len(text_content.strip()) < 100:
                return False

            # 检查是否包含有意义的内容
            meaningful_keywords = ['产业', '行业', '市场', '发展', '分析', '研究', '报告']
            return any(keyword in text_content for keyword in meaningful_keywords)

        # 使用Baidu搜索获取内容（替换Jina Reader）
        if urls:
            log_message(user_id, f"🔄 开始使用百度搜索获取 {len(urls)} 个URL的内容...", log_type="INFO")

            # 创建BaiduSearcher实例用于读取内容
            baidu_searcher = BaiduSearcher()

            # 并发获取内容
            semaphore = asyncio.Semaphore(5)  # 限制并发数为5

            async def fetch_with_baidu(url):
                async with semaphore:
                    if cancel_flag and cancel_flag.is_set():
                        return None

                    try:
                        # 使用百度搜索获取完整内容
                        content = await baidu_searcher.get_page_content(url, user_id)
                        title = titles.get(url, '未知标题')

                        if content and len(content.strip()) >= 100:
                            log_message(user_id, f"✅ 成功获取: {title[:30]}... ({len(content)} 字符)", log_type="DEBUG")
                            return {
                                'url': url,
                                'title': title,
                                'content': content[:8000],  # 限制内容长度
                                'status': 'success'
                            }
                        else:
                            content_len = len(content) if content else 0
                            log_message(user_id, f"⚠️ 内容太短或为空: {title[:30]}... ({content_len} 字符)", log_type="WARNING")
                            return {'url': url, 'status': 'error', 'error': f'内容太短 ({content_len} 字符)'}

                    except Exception as e:
                        log_message(user_id, f"❌ 获取失败: {url[:50]}... - {str(e)}", log_type="ERROR")
                        return {'url': url, 'status': 'error', 'error': str(e)}

            # 创建爬取任务（根据搜索类型限制URL数量）
            # 任务一：最多10个URL；节点搜索：最多5个URL；辅助节点：最多3个URL
            if isNode:
                if node:  # 正式节点
                    max_urls = 5
                else:  # 辅助节点
                    max_urls = 3
            else:  # 任务一
                max_urls = 10

            tasks = []
            for url in urls[:max_urls]:
                if cancel_flag and cancel_flag.is_set():
                    break
                tasks.append(fetch_with_baidu(url))

            # 执行并发爬取
            if tasks:
                crawl_results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in crawl_results:
                    if isinstance(result, dict) and result:
                        if result.get('status') == 'success':
                            results.append(result)
                            # 对标题进行URL解码，修复乱码问题
                            from urllib.parse import unquote
                            decoded_title = unquote(result.get('title', '未知标题'))
                            collected_articles.append({
                                'title': decoded_title,
                                'url': result['url'],
                                'content': result['content'][:1000]  # 限制长度
                            })
                            # 任务一：实时发送文章给前端（修复任务一文章不显示问题）
                            if send_message and not isNode:
                                await send_message(f"{decoded_title}url:{result['url']}", "5")
                        url_status.append({
                            'url': result['url'],
                            'status': result.get('status', 'unknown'),
                            'title': titles.get(result['url'], '未知标题')
                        })

            log_message(user_id, f"✅ Jina Reader获取完成: {len([r for r in results if r.get('status')=='success'])}/{len(tasks)} 成功", log_type="INFO")

        # 处理结果
        if not results:
            log_message(user_id, f"❌ 未能获取到有效内容: {industry_name}", log_type="ERROR")
            return '无内容', []

        # 合并内容
        combined_content = []
        for result in results:
            content = result.get('content', '')
            if content:
                combined_content.append(f"来源: {result.get('title', '未知')}\n内容: {content}\n")

        final_content = '\n'.join(combined_content)
        
        log_message(user_id, f"✅ 搜索完成，获取到 {len(results)} 个有效结果", log_type="INFO")
        return final_content, collected_articles

    except Exception as e:
        log_message(user_id, f"搜索过程中发生异常: {str(e)}", log_type="ERROR")
        import traceback
        log_message(user_id, f"异常详情: {traceback.format_exc()}", log_type="ERROR")
        return '无内容', []

# 工具函数：总搜索
async def tool_total_search(industry_name, custom_urls=None, user_id=None, send_message=None, sites=None, cancel_flag=None):
    # 检查是否已取消
    if cancel_flag and cancel_flag.is_set():
        log_message(user_id, f"总搜索已被取消: {industry_name}", log_type="INFO")
        return '无内容', [], []
        
    log_message(user_id, f"开始对产业链 '{industry_name}' 进行搜索", log_type="INFO")
    
    # 任务一：执行主搜索 
    max_search_attempts = 2
    center_node_info = None
    center_articles = []
    
    for search_attempt in range(max_search_attempts):
        try:
            # 检查是否已取消
            if cancel_flag and cancel_flag.is_set():
                log_message(user_id, f"总搜索已被取消: {industry_name}", log_type="INFO")
                return '无内容', [], []

            log_message(user_id, f"任务一搜索尝试 {search_attempt + 1}/{max_search_attempts}", log_type="INFO")
            
            # 发送前端搜索提示
            if send_message and search_attempt == 0:  # 只在第一次尝试时发送
                if sites:
                    sites_str = "、".join(sites)
                else:
                    await send_message(f'正在搜索{industry_name}产业链信息，搜索来源：中商情报网和前瞻', "2")
            
            center_node_info, center_articles = await tool_search_with_enhanced_cache(
                industry_name,
                custom_urls=custom_urls,
                user_id=user_id,
                send_message=send_message,
                sites=sites,
                cancel_flag=cancel_flag
            )

            # 检查搜索结果 - 不将fallback内容视为成功
            if center_node_info and center_node_info not in ['无内容', ''] and 'example.com/fallback' not in str(center_node_info):
                log_message(user_id, f"任务一搜索成功: {center_node_info[:200]}...", log_type="INFO")

                # 保存中心节点（产业链名称）的文章到数据库
                if center_articles:
                    for article in center_articles:
                        title = article.get('title', '未知标题')
                        url = article.get('url', '#')
                        try:
                            await save_node_article(storage_name, industry_name, url, title)
                        except Exception as save_error:
                            log_message(user_id, f"保存中心节点文章失败: {save_error}", log_type="WARNING")
                            # 继续处理，不中断流程

                break
            else:
                log_message(user_id, f"第{search_attempt + 1}次搜索未获取到有效内容", log_type="WARNING")
                if search_attempt == max_search_attempts - 1:
                    log_message(user_id, "所有搜索尝试均失败，将跳过任务二、三直接执行任务四", log_type="ERROR")
                    if send_message:
                        await send_message(f"任务一：搜索{industry_name}产业链信息失败，跳过任务二、三", "Error")
                        await send_message(f"任务二：提取{search_name}产业链节点跳过", "Error") 
                        await send_message(f"任务三：搜索{search_name}产业链节点信息跳过", "Error")
                    # 返回基础信息，让任务四继续执行
                    return f"搜索失败，将基于{industry_name}产业名称由大模型构建产业链", [], []
        except Exception as e:
            log_message(user_id, f"第{search_attempt + 1}次搜索异常: {e}", log_type="ERROR")
            if search_attempt == max_search_attempts - 1:
                log_message(user_id, "搜索过程发生异常，将跳过任务二、三直接执行任务四", log_type="ERROR")
                if send_message:
                    await send_message(f"任务一：搜索{industry_name}产业链信息异常，跳过任务二、三", "Error")
                    await send_message(f"任务二：提取{search_name}产业链节点跳过", "Error")
                    await send_message(f"任务三：搜索{search_name}产业链节点信息跳过", "Error")
                # 返回基础信息，让任务四继续执行  
                return f"搜索异常，将基于{industry_name}产业名称由大模型构建产业链", [], []
    
    # 初始化收集的文章数据
    all_collected_articles = center_articles.copy() if center_articles else []

    # 检查是否已取消
    if cancel_flag and cancel_flag.is_set():
        log_message(user_id, f"总搜索已被取消: {industry_name}", log_type="INFO")
        return '无内容', [], []

    # 任务二：提取节点信息 
    log_message(user_id, "开始提取节点信息")
    if send_message:
        await send_message(f"任务二：提取{search_name}产业链节点", "1")
    
    try:
        nodes = await process_industry_data(
            get_entity_prompts.format(industry=search_name), 
            center_node_info, 
            user_id, 
            send_message, 
            cancel_flag
        )
    
        # 检查是否已取消
        if cancel_flag and cancel_flag.is_set():
            log_message(user_id, f"总搜索已被取消: {industry_name}", log_type="INFO")
            return '无内容', [], []
        
        # 添加None检查
        if nodes is None:
                log_message(user_id, "节点提取结果为空（None），可能是因为API调用超时，将跳过任务二三直接进入任务四", log_type="WARNING")
                if send_message:
                    await send_message(f"任务二：提取{search_name}产业链节点失败，API调用超时", "Error")
                    await send_message(f"任务三：搜索{search_name}产业链节点信息失败，API调用超时", "Error")
                # 返回搜索到的基础信息，让任务四继续执行 - 保持流程连续性
                return center_node_info, [], all_collected_articles
            
    except Exception as e:
        log_message(user_id, f"任务二节点提取异常: {e}", log_type="ERROR")
        if send_message:
            await send_message(f"任务二：提取{search_name}产业链节点异常", "Error")
            await send_message(f"任务三：搜索{search_name}产业链节点信息跳过", "Error")
        # 即使任务二失败，也返回基础信息继续流程
        return center_node_info, [], all_collected_articles
        
    log_message(user_id, f"节点有: {nodes}")
    
    # 发送任务二完成消息
    if send_message:
        await send_message(f"任务二：提取{search_name}产业链节点完成", "2")
        
    # 检查是否已取消
    if cancel_flag and cancel_flag.is_set():
        log_message(user_id, f"总搜索已被取消: {industry_name}", log_type="INFO")
        return '无内容', [], []
        
    # 任务三：搜索节点信息 
    if send_message:
        await send_message(f"任务三：搜索{search_name}产业链节点信息", "1")      
    
    # 节点JSON解析
    parsed_nodes = None
    attempts = 0
    max_attempts = 3
    
    while attempts < max_attempts and parsed_nodes is None:
        try:
            # 检查是否已取消
            if cancel_flag and cancel_flag.is_set():
                log_message(user_id, f"总搜索已被取消: {industry_name}", log_type="INFO")
                return '无内容', [], []
                
            attempts += 1
            log_message(user_id, f"尝试解析节点JSON，第{attempts}次尝试", log_type="INFO")
            
            # 清理和解析节点数据
            cleaned_nodes = nodes.replace("```", "").replace("json", "").strip()
            parsed_nodes = json.loads(cleaned_nodes)
            
            # 如果解析结果是字典，提取nodes列表
            if isinstance(parsed_nodes, dict):
                if 'nodes' in parsed_nodes:
                    parsed_nodes = parsed_nodes['nodes']
                elif 'node' in parsed_nodes:
                    parsed_nodes = parsed_nodes['node']
                else:
                    # 尝试获取第一个列表类型的值
                    for v in parsed_nodes.values():
                        if isinstance(v, list):
                            parsed_nodes = v
                            break
            
            # 确保parsed_nodes是列表
            if not isinstance(parsed_nodes, list):
                log_message(user_id, f"节点数据格式异常，期望列表但得到: {type(parsed_nodes)}", log_type="WARNING")
                parsed_nodes = []
            
            log_message(user_id, f"成功解析节点JSON，节点数量: {len(parsed_nodes)}")
            log_message(user_id, f"节点内容: {parsed_nodes}", log_type="INFO")
            
            # 将具体的节点内容发送给用户
            nodes_json = json.dumps(parsed_nodes, ensure_ascii=False)
            nodes_json = nodes_json.replace("data:", "").strip()
            await send_message(f"结果:{nodes_json}", "3")

            break
            
        except json.JSONDecodeError as e:
            log_message(user_id, f"节点JSON解析失败，第{attempts}次尝试: {e}", log_type="ERROR")
            
            if attempts >= max_attempts:
                log_message(user_id, "节点解析失败达到最大尝试次数，跳过任务三", log_type="WARNING")
                if send_message:
                    await send_message(f"任务二：提取{search_name}产业链节点完成（部分成功）", "2")
                    await send_message(f"任务三：搜索{search_name}产业链节点信息失败，节点解析错误", "Error")
                # 返回基础信息，跳过节点搜索
                return center_node_info, [], all_collected_articles
            
            # 重新获取节点数据
            try:
                log_message(user_id, f"重新获取节点数据，第{attempts}次重试", log_type="INFO")
                nodes = await process_industry_data(
                    get_entity_prompts.format(industry=search_name), 
                    center_node_info, 
                    user_id, 
                    send_message, 
                    cancel_flag
                )

                if nodes is None:
                    log_message(user_id, f"重试第{attempts}次节点提取结果为空，跳过任务三", log_type="WARNING")
                    if send_message:
                        await send_message(f"任务二：提取{search_name}产业链节点完成（部分成功）", "2")
                        await send_message(f"任务三：搜索{search_name}产业链节点信息失败，API调用超时", "Error")
                    return center_node_info, [], all_collected_articles
                    
            except Exception as retry_e:
                log_message(user_id, f"重新获取节点数据异常: {retry_e}", log_type="ERROR")
                if attempts >= max_attempts:
                    if send_message:
                        await send_message(f"任务二：提取{search_name}产业链节点完成（部分成功）", "2")
                        await send_message(f"任务三：搜索{search_name}产业链节点信息失败，重试异常", "Error")
                    return center_node_info, [], all_collected_articles
                    
        except Exception as e:
            log_message(user_id, f"节点处理异常，第{attempts}次尝试: {e}", log_type="ERROR")
            if attempts >= max_attempts:
                log_message(user_id, "节点处理异常达到最大尝试次数，跳过任务三", log_type="WARNING")
                if send_message:
                    await send_message(f"任务二：提取{search_name}产业链节点完成（部分成功）", "2")
                    await send_message(f"任务三：搜索{search_name}产业链节点信息失败，处理异常", "Error")
                return center_node_info, [], all_collected_articles
    
    # 如果解析失败，使用空节点列表继续流程
    if parsed_nodes is None:
        log_message(user_id, "所有节点解析尝试均失败，使用空节点列表继续", log_type="WARNING")
        parsed_nodes = []
        if send_message:
            await send_message(f"任务二：提取{search_name}产业链节点完成（部分成功）", "2")
            await send_message(f"任务三：搜索{search_name}产业链节点信息跳过", "Error")
        return center_node_info, [], all_collected_articles
    
    # 使用解析后的节点
    nodes = parsed_nodes
    
    # 确保materials目录存在
    os.makedirs("materials", exist_ok=True)
    try:
        with open(f'materials/white_list_{industry_name}.txt', 'r', encoding='utf-8') as file:
            white_list = file.read().splitlines()
            for item in white_list:
                if item not in nodes:
                    nodes.append(item)
        log_message(user_id, f"加入白名单后的节点有: {nodes}")          
    except FileNotFoundError:
        log_message(user_id, f"文件 materials/white_list_{industry_name}.txt 不存在。", log_type="WARNING")
    
    # 检查是否已取消
    if cancel_flag and cancel_flag.is_set():
        log_message(user_id, f"总搜索已被取消: {industry_name}", log_type="INFO")
        return '无内容', [], []

    total_info = []
    
    # 创建进度管理器确保有序显示
    class NodeProgressManager:
        def __init__(self, total_nodes):
            self.total_nodes = total_nodes
            self.current_display = 0
            self.completed_nodes = {}
            self.lock = asyncio.Lock()
        
        async def update_progress(self, node_index, node_name, status="searching"):
            async with self.lock:
                if status == "searching" and send_message:
                    # 只显示当前应该显示的节点
                    if node_index == self.current_display:
                        await send_message(f"搜索节点 {node_index+1}/{self.total_nodes}: {node_name}", "2")
                        self.current_display += 1
                        
                        # 检查是否有待显示的后续节点
                        while self.current_display in self.completed_nodes:
                            next_node = self.completed_nodes[self.current_display]
                            await send_message(f"搜索节点 {self.current_display+1}/{self.total_nodes}: {next_node}", "2")
                            self.current_display += 1
                elif status == "completed":
                    # 记录已完成的节点，但不立即显示
                    if node_index > self.current_display:
                        self.completed_nodes[node_index] = node_name
    
    progress_manager = NodeProgressManager(len(nodes))
    
    # 创建并行任务（保留取消检查）
    async def search_node_with_progress(i, node):
        # 检查是否已取消
        if cancel_flag and cancel_flag.is_set():
            log_message(user_id, f"节点搜索已被取消: {industry_name}", log_type="INFO")
            return None
        
        # 按顺序显示进度消息
        await progress_manager.update_progress(i, node, "searching")

        result, articles = await tool_search(
            industry_name,
            custom_urls=custom_urls,
            isNode=True,
            node=node,
            isAux=False,
            user_id=user_id,
            send_message=send_message,
            sites=sites,
            cancel_flag=cancel_flag
        )

        # 立即发送文章数据给前端（修复任务三问题1）
        if articles and send_message:
            for article in articles:
                title = article.get('title', '未知标题')
                url = article.get('url', '#')
                await send_message(f"{title}url:{url}", "5")

        # 保存节点文章到数据库
        if articles:
            for article in articles:
                title = article.get('title', '未知标题')
                url = article.get('url', '#')
                try:
                    await save_node_article(storage_name, node, url, title)
                except Exception as save_error:
                    log_message(user_id, f"保存节点 {node} 文章失败: {save_error}", log_type="WARNING")
                    # 继续处理，不中断流程
        
        # 标记完成（用于内部管理，不显示）
        await progress_manager.update_progress(i, node, "completed")
        
        return (result, articles) if result is not None and result != '无内容' else ('无内容', [])
    
    # 优化并发数量，提高搜索效率
    semaphore = asyncio.Semaphore(5)  # 增加到5个并发搜索，提高速度
    
    async def search_with_semaphore(i, node):
        async with semaphore:
            return await search_node_with_progress(i, node)
    
    # 创建异步并发任务
    tasks = [search_with_semaphore(i, node) for i, node in enumerate(nodes)]
    
    # 并发搜索节点 
    try:
        log_message(user_id, f"开始并发搜索 {len(nodes)} 个节点", log_type="INFO")
        results_data = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果，过滤掉异常和无效结果
        results = []
        successful_nodes = 0
        failed_nodes = 0
        
        for i, result_data in enumerate(results_data):
            if cancel_flag and cancel_flag.is_set():
                log_message(user_id, f"节点搜索已被取消: {industry_name}", log_type="INFO")
                return '无内容', [], []
                
            node_name = nodes[i] if i < len(nodes) else f"节点{i}"
                
            if isinstance(result_data, Exception):
                failed_nodes += 1
                log_message(user_id, f"节点 {node_name} 搜索异常: {result_data}", log_type="ERROR")
                # 继续处理其他节点，不中断整个流程
                continue
                
            if result_data and result_data[0] is not None and result_data[0] != '无内容':
                successful_nodes += 1
                result, articles = result_data
                results.append(result)
                # 收集节点文章数据
                if articles:
                    all_collected_articles.extend(articles)
                log_message(user_id, f"节点 {node_name} 搜索成功", log_type="INFO")
            else:
                failed_nodes += 1
                log_message(user_id, f"节点 {node_name} 搜索无结果", log_type="WARNING")
        
        log_message(user_id, f"节点搜索完成: 成功 {successful_nodes}/{len(nodes)}，失败 {failed_nodes}", log_type="INFO")
        
        # 即使部分节点失败，只要有成功的节点就继续流程
        if successful_nodes > 0:
            if send_message:
                await send_message(f"任务三：搜索{search_name}产业链节点信息完成（{successful_nodes}/{len(nodes)}成功）", "2")
        else:
            log_message(user_id, "所有节点搜索均失败，但继续基于基础信息生成结果", log_type="WARNING")
            if send_message:
                await send_message(f"任务三：搜索{search_name}产业链节点信息失败，所有节点搜索无结果", "Error")
        
    except asyncio.CancelledError:
        log_message(user_id, f"节点搜索任务被用户取消: {industry_name}", log_type="INFO")
        if send_message:
            await send_message(f"任务三：搜索{search_name}产业链节点信息被取消", "Error")
        return '无内容', [], []
    except Exception as e:
        log_message(user_id, f"节点搜索过程异常: {e}", log_type="ERROR")
        if send_message:
            await send_message(f"任务三：搜索{search_name}产业链节点信息异常", "Error")
        results = []
        # 即使搜索异常，也继续基于已有信息生成结果
    
    # 收集有效结果
    for result in results:
        if isinstance(result, str) and result:
            total_info.append(result)

    # 来源去重：避免同一网站的重复文章
    seen_domains = {}
    unique_articles = []
    for article in all_collected_articles:
        url = article.get('url', '')
        # 提取域名
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # 提取主要内容（如 askci.com）
            main_domain = '.'.join(domain.split('.')[-2:]) if '.' in domain else domain

            # 如果这个域名已经有过文章，检查内容是否高度相似
            if main_domain in seen_domains:
                # 保留第一个，跳过相似的
                continue
            else:
                seen_domains[main_domain] = True
                unique_articles.append(article)
        except:
            # 如果解析失败，保留文章
            unique_articles.append(article)

    all_collected_articles = unique_articles
    log_message(user_id, f"来源去重后保留 {len(all_collected_articles)} 篇独特文章", log_type="DEBUG")

    total_info = '\n'.join(total_info)

    # 检查是否已取消
    if cancel_flag and cancel_flag.is_set():
        log_message(user_id, f"总搜索已被取消: {industry_name}", log_type="INFO")
        return '无内容', [], []

    final = f'# 1 {industry_name}整体产业链知识\n{center_node_info}\n' + f'# 2 有关{industry_name}中其他节点的产业链知识\n{total_info}'
    
    log_message(user_id, f"总搜索完成，收集了 {len(all_collected_articles)} 篇文章", log_type="INFO")
    
    # 修复：移除重复的文章展示，因为文章已在每个节点搜索完成时立即发送
    # 这里不再重复发送文章数据，避免任务一重复显示的问题
    log_message(user_id, f"文章数据已在节点搜索过程中发送给前端", log_type="INFO")
    
    return final, nodes, all_collected_articles

# 清理和解析三元组
async def clean_and_parse(triples_raw, user_id=None, send_message=None):
    
    try:
        if triples_raw is None:
            log_message(user_id, "Error: triples_raw is None", log_type="ERROR")
            # if send_message:
            await send_message("Error: triples_raw is None", "Error")
            return None
            
        # 记录原始输入长度
        log_message(user_id, f"原始三元组字符串长度: {len(triples_raw)}")
        
        # 清理字符串
        cleaned_triples_raw = triples_raw.replace("```json", "").replace("```", "").strip()
        log_message(user_id, f"清理后的字符串长度: {len(cleaned_triples_raw)}")
        
        # if send_message:
        #     await send_message(f"{cleaned_triples_raw}", "2")
            
        try:
            result = json.loads(cleaned_triples_raw)
            log_message(user_id, f"成功解析 JSON: {list(result.keys())}")
            
            # 打印解析后的 JSON 内容
            if 'nodes' in result:
                log_message(user_id, f"解析出的节点: {result['nodes']}", log_type="INFO")
            if 'relations' in result:
                log_message(user_id, f"解析出的关系: {result['relations']}", log_type="INFO")
                
            return result
        except json.JSONDecodeError as e:
            log_message(user_id, f"JSON 解析错误: {e}", log_type="ERROR")
            
            # 尝试修复常见的 JSON 格式问题
            if cleaned_triples_raw.startswith('{') and not cleaned_triples_raw.endswith('}'):
                cleaned_triples_raw += '}'
                log_message(user_id, "尝试修复 JSON 格式：添加结束括号")
                
            # 再次尝试解析
            try:
                result = json.loads(cleaned_triples_raw)
                log_message(user_id, f"修复后成功解析 JSON: {list(result.keys())}")
                return result
            except json.JSONDecodeError:
                log_message(user_id, "JSON 解析失败，返回 None", log_type="ERROR")
                # if send_message:
                await send_message("JSON 解析失败", "Error")
                return None
    except Exception as e:
        log_message(user_id, f"解析 triples_raw 时出错: {e}", log_type="ERROR")
        # if send_message:
        await send_message(f"解析 triples_raw 时出错: {e}", "Error")
        return None

# 保存节点文章链接
async def save_node_article(chain_name, node_name, url, title):
    """
    保存节点相关的文章链接到数据库
    
    Args:
        chain_name: 产业链名称
        node_name: 节点名称
        url: 文章链接
        title: 文章标题
    """
    conn = None
    try:
        from database.industrial_chain.connection import get_connection
        
        # 添加参数验证和详细日志
        if not chain_name or chain_name.strip() == "":
            log_message(None, f"保存节点文章失败: chain_name为空", log_type="ERROR")
            return False
            
        log_message(None, f"准备保存节点文章: chain_name='{chain_name}', node_name='{node_name}'", log_type="INFO")
        
        conn = await get_connection()
        cursor = conn.cursor()
        
        # 清理title，防止过长
        if title and len(title) > 250:
            title = title[:250]
        
        sql = """
        INSERT INTO node_article_links 
        (chain_name, node_name, url, title) 
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
        title = VALUES(title),
        created_at = CURRENT_TIMESTAMP
        """
        
        # 记录SQL执行前的参数
        log_message(None, f"执行SQL参数: chain_name='{chain_name}', node_name='{node_name}', title='{title}'", log_type="INFO")
        
        cursor.execute(sql, (chain_name, node_name, url, title))
        affected_rows = cursor.rowcount
        conn.commit()
        
        log_message(None, f"保存节点文章成功: chain_name='{chain_name}', node_name='{node_name}', 影响行数: {affected_rows}", log_type="INFO")
        
        return True
    except Exception as e:
        log_message(None, f"保存节点文章链接失败: {e}", log_type="ERROR")
        import traceback
        log_message(None, f"详细错误信息: {traceback.format_exc()}", log_type="ERROR")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

# 处理行业逻辑
async def process_industry_with_historical(industry_name, custom_urls=None, user_id=None, send_message=None,
                                         sites=None, cancel_flag=None, historical_config=None, oa_user_id=None):
    """
    处理产业链分析（支持历史报告分析）

    Args:
        industry_name: 产业名称
        custom_urls: 自定义URL列表
        user_id: 用户ID
        send_message: 发送消息函数
        sites: 网站列表
        cancel_flag: 取消标志
        historical_config: 历史报告配置 {
            "report_path": "历史报告文件路径",
            "reference_files": ["参考文件路径列表"],
            "enable": True/False
        }
        oa_user_id: 用户OA账号别名（用于钉钉通知）
    """

    return await process_industry(
        industry_name, custom_urls, user_id, send_message, sites, cancel_flag, historical_config, oa_user_id
    )

async def process_industry(industry_name, custom_urls=None, user_id=None, send_message=None, sites=None, cancel_flag=None, historical_config=None, oa_user_id=None):
    record_id = None
    record_id = None
    has_failure = False  # 失败标志

    # ============ 新增：测试模式支持 ============
    # 自动检测测试后缀，实现"搜索用原名，存储用测试名"
    test_suffixes = ['测试', '_测试', 'test', '_test', 'v2', '_v2', '新版', '_新版', 'V2', '_V2']

    search_name = industry_name      # 用于搜索和AI上下文
    storage_name = industry_name     # 用于数据库存储
    is_test_mode = False

    for suffix in test_suffixes:
        if industry_name.endswith(suffix):
            # 提取基础名称用于搜索
            search_name = industry_name.replace(suffix, '').strip('_').strip()
            storage_name = industry_name
            is_test_mode = True
            log_message(user_id, f"🧪 检测到测试模式 - 搜索关键词：'{search_name}', 存储名称：'{storage_name}'", log_type="INFO")
            break

    if not is_test_mode:
        log_message(user_id, f"📊 正常模式 - 产业名称：'{industry_name}'", log_type="INFO")
    # ============ 测试模式支持结束 ============

    try:
        # 确保send_message函数可用
        if send_message is None:
            # 创建一个空操作函数作为后备
            async def send_message(message, message_type):
                log_message(user_id, f"[{message_type}] {message}", log_type="INFO")
        
        # 初始化产业链分析记录（使用存储名称）
        try:
            record_id = await IndustryStorageService.initialize_record(storage_name, user_id, custom_urls, sites=sites)
            log_message(user_id, f"成功初始化产业链记录，record_id: {record_id}, 存储名称: {storage_name}", log_type="INFO")
        except Exception as e:
            log_message(user_id, f"初始化记录失败: {e}", log_type="ERROR")
            import traceback
            log_message(user_id, f"初始化记录失败详细信息: {traceback.format_exc()}", log_type="ERROR")
            # 继续执行，即使没有record_id，但发送错误消息
            await send_message(f"初始化产业链记录失败: {e}", "Error")
        
        # 检查是否已取消
        if cancel_flag and cancel_flag.is_set():
            log_message(user_id, f"产业链分析已被用户取消: {industry_name}", log_type="INFO")
            if record_id:
                try:
                    await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 主动取消")
                    has_failure = True  # 标记失败
                    log_message(user_id, f"已将产业链记录 {record_id} 标记为失败（用户取消）", log_type="INFO")
                except Exception as mark_error:
                    log_message(user_id, f"标记失败状态时出错: {mark_error}", log_type="ERROR")
            await send_message(f"产业链分析已被取消", "End")
            return
        
        # 任务一：搜索产业链信息（真正执行搜索，使用搜索名称）
        await send_message(f"任务一：搜索{search_name}产业链信息", "1")
        
        # 获取当前进程的PID
        pid = os.getpid()
        user_folder = f"user_{user_id}_pid_{pid}"
        
        # 检查是否已取消
        if cancel_flag and cancel_flag.is_set():
            log_message(user_id, f"产业链分析已被取消: {industry_name}", log_type="INFO")
            if record_id:
                await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 取消了任务")
                has_failure = True  # 标记失败
            await send_message(f"产业链分析已被取消", "End")
            return
        
        # 确保目录存在
        try:
            os.makedirs("resultTxt", exist_ok=True)
            os.makedirs("resultImg", exist_ok=True)
            os.makedirs(f"resultTxt/{user_folder}", exist_ok=True)
            os.makedirs(f"resultImg/{user_folder}", exist_ok=True)
        except Exception as e:
            log_message(user_id, f"创建目录失败: {e}", log_type="ERROR")

        # 清理输入的产业链名称（使用搜索名称）
        industry_name_raw = await process_industry_data(input_clean_prompts, search_name, user_id, send_message, cancel_flag)

        # 从JSON响应中提取纯文本产业链名称
        # 保存原始产业链名称，以便在API返回无效结果时使用
        original_industry_name = search_name  # 使用搜索名称
        
        if industry_name_raw:
            parsed_industry_name = extract_industry_name_from_ai_response(
                industry_name_raw,
                original_industry_name,
                user_id
            )
            if parsed_industry_name:
                search_name = parsed_industry_name  # 更新搜索名称
            else:
                log_message(user_id, f"无法提取有效产业链名称，使用原始名称: {original_industry_name}", log_type="WARNING")
                search_name = original_industry_name

            # 最终清理：去除可能残留的引号和空白
            if search_name:
                search_name = search_name.strip().strip('"\'').strip()
                # 再次验证清理后的名称不为空
                if _looks_like_invalid_industry_name(search_name):
                    log_message(user_id, f"清理后的产业链名称为空，使用原始名称: {original_industry_name}", log_type="WARNING")
                    search_name = original_industry_name
                log_message(user_id, f"清理后的搜索名称: {search_name}", log_type="INFO")
            else:
                log_message(user_id, f"产业链名称为空，使用原始名称: {original_industry_name}", log_type="WARNING")
                search_name = original_industry_name

        # 同步更新meta表中的产业链名称（使用存储名称）
        if record_id and storage_name:
            try:
                await IndustryStorageService.update_name(record_id, storage_name)
                log_message(user_id, f"已同步更新产业链存储名称: {storage_name}, 搜索名称: {search_name}", log_type="INFO")
            except Exception as e:
                log_message(user_id, f"更新产业链名称失败: {e}", log_type="WARNING")
        
        # 检查是否已取消
        if cancel_flag and cancel_flag.is_set():
            log_message(user_id, f"产业链分析已被取消: {industry_name}", log_type="INFO")
            if record_id:
                await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 取消了任务")
                has_failure = True  # 标记失败
            await send_message(f"产业链分析已被取消", "End")
            return
            
        # 执行搜索函数 - 任务一的核心搜索逻辑（使用搜索名称）
        try:
            final_info, nodes, collected_articles = await tool_total_search(
                search_name,  # 使用搜索名称
                custom_urls=custom_urls,
                user_id=user_id,
                send_message=send_message,
                sites=sites,
                cancel_flag=cancel_flag
            )

            # 检查搜索结果
            if final_info and final_info != '无内容':
                # 任务一完成
                await send_message(f"任务一：搜索{search_name}产业链信息完成", "2")
                log_message(user_id, f"搜索完成，收集了 {len(collected_articles)} 篇文章用于报告生成", log_type="INFO")
            else:
                log_message(user_id, f"搜索结果为空或无内容，但继续执行后续任务", log_type="WARNING")
                await send_message(f"任务一：搜索{search_name}产业链信息完成（结果有限）", "2")

        except Exception as e:
            log_message(user_id, f"搜索过程中发生异常: {e}", log_type="ERROR")
            import traceback
            log_message(user_id, f"搜索异常详情: {traceback.format_exc()}", log_type="ERROR")

            # 即使搜索失败，也尝试继续执行后续任务 - 保持流程连续性
            final_info = f"搜索过程中遇到问题，但将基于{search_name}产业的基础信息继续分析。"
            nodes = []
            collected_articles = []
            await send_message(f"任务一：搜索{search_name}产业链信息异常，但将继续分析", "Error")
        
        # 发送文章数据给前端
        log_message(user_id, f"准备发送文章数据，collected_articles数量: {len(collected_articles) if collected_articles else 0}", log_type="INFO")
        if collected_articles and len(collected_articles) > 0:
            log_message(user_id, f"开始发送 {len(collected_articles)} 篇文章数据给前端", log_type="INFO")
            for i, article in enumerate(collected_articles):
                title = article.get('title', '未知标题')
                url = article.get('url', '#')
                log_message(user_id, f"发送文章 {i+1}: {title} - {url}", log_type="DEBUG")
                await send_message(f"{title}url:{url}", "5")
            log_message(user_id, f"已发送 {len(collected_articles)} 篇文章数据给前端", log_type="INFO")
        else:
            log_message(user_id, "未收集到文章数据", log_type="WARNING")

        # 检查是否已取消
        if cancel_flag and cancel_flag.is_set():
            log_message(user_id, f"产业链分析已被取消: {industry_name}", log_type="INFO")
            if record_id:
                await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 取消了任务")
                has_failure = True  # 标记失败
            await send_message(f"产业链分析已被取消", "End")
            return

        # 检查搜索结果是否有效 - 包括检查fallback内容
        is_search_failed = (final_info in ['无内容', ''] or not final_info or 
                           'example.com/fallback' in str(final_info) or 
                           '基于产业名称由大模型构建产业链' in str(final_info))
        
        if is_search_failed:
            log_message(user_id, f"任务一搜索失败，将跳过任务二、三，直接执行任务四由大模型构建", log_type="WARNING")
            await send_message(f"任务一：搜索{industry_name}产业链信息失败，跳过任务二、三", "Error")
            await send_message(f"任务二：提取{search_name}产业链节点跳过", "Error") 
            await send_message(f"任务三：搜索{search_name}产业链节点信息跳过", "Error")
            
            # 设置空的搜索结果，但继续执行任务四
            final_info = f"由于搜索未找到{industry_name}产业链的具体信息，将基于产业名称由大模型直接构建产业链结构。"
            nodes = []
            collected_articles = []
            
            # 设置标志跳过任务二和任务三
            skip_tasks_2_3 = True
            log_message(user_id, f"将直接执行任务四，由大模型自行构建{industry_name}产业链", log_type="INFO")
        else:
            skip_tasks_2_3 = False
            log_message(user_id, f"任务一搜索成功，收集到内容长度: {len(final_info)}", log_type="INFO")

        # 确保目录存在
        try:
            os.makedirs(f"resultTxt/{user_folder}", exist_ok=True)
        except Exception as e:
            log_message(user_id, f"创建目录失败: {e}", log_type="ERROR")

        # 写入总信息文件
        try:
            total_info_path = f"resultTxt/{user_folder}/{industry_name}_total_info.txt"
            with open(total_info_path, "w", encoding='utf-8') as f:
                f.write(final_info)
            
            # 检查文件是否成功写入
            if not os.path.exists(total_info_path):
                log_message(user_id, f"文件写入失败: {total_info_path}", log_type="ERROR")
                if record_id:
                    await IndustryStorageService.mark_as_failed(record_id, f"文件写入失败: {total_info_path}")
                    has_failure = True  # 标记失败
                await send_message("文件写入失败，分析结束", "End")
                return
            
            with open(total_info_path, "r", encoding='utf-8') as f:
                final_info = f.read()
        except Exception as e:
            log_message(user_id, f"写入或读取总信息文件时出错: {e}", log_type="ERROR")
            if record_id:
                await IndustryStorageService.mark_as_failed(record_id, f"写入或读取总信息文件时出错: {e}")
                has_failure = True  # 标记失败
            await send_message("文件处理失败，分析结束", "End")
            return

        # 初始化 white_list 为一个空集合
        white_list = set()

        # 注意：任务二和任务三已经在 tool_total_search 函数中执行完成
        # 这里的 skip_tasks_2_3 标志用于控制是否跳过任务二、三
        # 如果已经执行过，就不需要再执行了

        # 尝试读取白名单文件
        try:
            with open(f'materials/white_list_{industry_name}.txt', 'r', encoding='utf-8') as f:
                white_list = set(line.strip() for line in f.readlines())
        except FileNotFoundError:
            log_message(user_id, f"文件 materials/white_list_{industry_name}.txt 不存在。", log_type="WARNING")

        await send_message(f"任务四：构建{industry_name}产业链节点关系", "1")

        # 检查是否已取消
        if cancel_flag and cancel_flag.is_set():
            log_message(user_id, f"产业链分析已被取消: {industry_name}", log_type="INFO")
            if record_id:
                await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 取消了任务")
                has_failure = True  # 标记失败
            await send_message(f"产业链分析已被取消", "End")
            return

        max_attempts = 5
        attempts = 0

        while attempts < max_attempts:
            try:
                # 检查是否已取消
                log_message(user_id, f"尝试第 {attempts + 1} 次处理", log_type="INFO")
                if cancel_flag and cancel_flag.is_set():
                    log_message(user_id, f"产业链分析已被取消: {industry_name}", log_type="INFO")
                    if record_id:
                        await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 取消了任务")
                        has_failure = True  # 标记失败
                    await send_message(f"产业链分析已被取消", "End")
                    return
                
                # 确保等待异步函数的结果
                white_list_str = ", ".join(white_list)

                # 对final_info进行去重，减少输入长度
                final_info_dedup = await deduplicate_content(final_info, user_id)

                # 优化：限制输入内容大小，避免AI处理超时
                # 如果去重后内容仍然很大（>50KB），进一步截取关键部分
                max_content_size = 50 * 1024  # 50KB
                if len(final_info_dedup.encode('utf-8')) > max_content_size:
                    log_message(user_id, f"去重后内容仍较大（{len(final_info_dedup.encode('utf-8'))/1024:.1f}KB），截取关键部分", log_type="WARNING")
                    # 保留开头的产业链整体信息（最重要）
                    # 以及每个节点搜索结果的前500字符
                    lines = final_info_dedup.split('\n')
                    kept_lines = []
                    current_length = 0
                    in_section = False  # 标记是否在有效内容区域

                    for line in lines:
                        # 保留产业链整体信息标题和后续内容
                        if line.startswith('# 1') or line.startswith('# 2'):
                            in_section = True
                            kept_lines.append(line)
                            current_length += len(line.encode('utf-8'))
                            continue
                        
                        # 保留每个节点信息（以"来源:"开头的行及其内容）
                        if line.startswith('来源:'):
                            if len(line) > 500:
                                line = line[:500]
                            kept_lines.append(line)
                            current_length += len(line.encode('utf-8'))
                            continue
                        
                        if line.startswith('内容:'):
                            if len(line) > 3000:
                                line = line[:3000]
                            kept_lines.append(line)
                            current_length += len(line.encode('utf-8'))
                            continue
                        
                        # 如果在有效区域内，保留普通行（限制长度）
                        if in_section and line.strip():
                            if len(line) > 1000:
                                line = line[:1000]
                            kept_lines.append(line)
                            current_length += len(line.encode('utf-8'))
                        
                        # 如果已经接近50KB，停止添加
                        if current_length > max_content_size:
                            break

                    # 如果截取后内容太少（<5KB），说明格式不匹配，直接截取前50KB
                    if current_length < 5 * 1024:
                        log_message(user_id, f"按格式截取内容太少（{current_length/1024:.1f}KB），改用直接截取前50KB", log_type="WARNING")
                        content_bytes = final_info_dedup.encode('utf-8')[:max_content_size]
                        try:
                            truncated_str = content_bytes.decode('utf-8', errors='ignore')
                            last_newline = truncated_str.rfind('\n')
                            if last_newline > 0:
                                final_info_dedup = truncated_str[:last_newline]
                            else:
                                final_info_dedup = truncated_str
                        except:
                            final_info_dedup = final_info_dedup[:50000]
                    else:
                        final_info_dedup = '\n'.join(kept_lines)
                    
                    log_message(user_id, f"截取后内容大小: {len(final_info_dedup.encode('utf-8'))/1024:.1f}KB", log_type="INFO")

                triples_raw = await process_industry_data(
                    get_triples_prompts.format(industry=search_name,white_list=white_list_str) + "。需要特别注意：不要无限循环输出，不要有重复。",
                    final_info_dedup + "。需要特别注意：不要无限循环输出，不要有重复。",
                    user_id,
                    send_message,
                    cancel_flag
                )
                if triples_raw is None:
                    raise ValueError("process_industry_data 返回了 None")
                
                # 检查是否已取消
                if cancel_flag and cancel_flag.is_set():
                    log_message(user_id, f"产业链分析已被取消: {industry_name}", log_type="INFO")
                    if record_id:
                        await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 取消了任务")
                        has_failure = True  # 标记失败
                    await send_message(f"产业链分析已被取消", "End")
                    return
                
                triples_raw_dict = await clean_and_parse(triples_raw, user_id, send_message)
                if triples_raw_dict is None:
                    raise ValueError("clean_and_parse 返回了 None")

                relations = triples_raw_dict['关系-relations']
                nodes = triples_raw_dict['节点-nodes']

                # 打印节点和关系信息，便于调试
                log_message(user_id, f"节点数量: {len(nodes)}", log_type="INFO")
                log_message(user_id, f"关系数量: {len(relations)}", log_type="INFO")
                
                # 打印具体的节点和关系内容
                log_message(user_id, f"节点内容: {nodes}", log_type="INFO")
                log_message(user_id, f"关系内容: {relations}", log_type="INFO")
                
                # 将节点和关系信息发送给用户
                await send_message(f"节点数量: {len(nodes)}", "2")
                await send_message(f"关系数量: {len(relations)}", "2")
                
                # 将具体的节点和关系内容转换为JSON
                nodes_json = json.dumps(nodes, ensure_ascii=False)
                relations_json = json.dumps(relations, ensure_ascii=False)
                
                # 清理JSON中可能存在的"data:"前缀
                nodes_json = nodes_json.replace("data:", "").strip()
                relations_json = relations_json.replace("data:", "").strip()
                
                # 发送任务四完成消息
                await send_message(f"任务四：构建{industry_name}产业链节点关系完成", "2")
                
                # 检查是否已取消
                if cancel_flag and cancel_flag.is_set():
                    log_message(user_id, f"产业链分析已被取消: {industry_name}", log_type="INFO")
                    if record_id:
                        await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 取消了任务")
                        has_failure = True  # 标记失败
                    await send_message(f"产业链分析已被取消", "End")
                    return
                
                # 发送任务五开始消息
                await send_message(f"任务五：生成{industry_name}产业链图谱", "1")
                
                # 将具体的节点和关系内容发送给用户
                await send_message(f"节点-nodes:{nodes_json}", "3")
                await send_message(f"关系-relations:{relations_json}", "3")

                nodes_set = set(nodes)
                try:
                    # nodes_set.update(white_list)
                    pass
                except Exception as e:
                    log_message(user_id, f"更新节点时出错: {e}", log_type="ERROR")
                #     continue

                nodes = list(nodes_set)

                relations_str = '\n'.join(relations)
                nodes_str = '\n'.join(nodes)

                # 写入节点和关系文件 - 已启用
                try:
                    with open(f'resultTxt/{user_folder}/nodes_{industry_name}.txt', 'w', encoding='utf-8') as f:
                        f.write(nodes_str)

                    with open(f'resultTxt/{user_folder}/relations_{industry_name}.txt', 'w', encoding='utf-8') as f:
                        f.write(relations_str)
                    
                    # 检查文件是否成功写入
                    if not os.path.exists(f'resultTxt/{user_folder}/nodes_{industry_name}.txt') or not os.path.exists(f'resultTxt/{user_folder}/relations_{industry_name}.txt'):
                        log_message(user_id, f"节点或关系文件写入失败", log_type="ERROR")
                        await send_message(f"节点或关系文件写入失败", "Error")

                except Exception as e:
                    log_message(user_id, f"写入节点或关系文件时出错: {e}", log_type="ERROR")
                    await send_message(f"写入节点或关系文件时出错: {e}", "Error")

                
                # 检查是否已取消
                if cancel_flag and cancel_flag.is_set():
                    log_message(user_id, f"产业链分析已被取消: {industry_name}", log_type="INFO")
                    if record_id:
                        await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 取消了任务")
                        has_failure = True  # 标记失败
                    await send_message(f"产业链分析已被取消", "End")
                    return
                
                # 存储产业链结构数据
                await send_message(f"正在存储产业链 {industry_name} 的结构数据", "Processing")
                
                # 检查文件是否存在 - 已禁用，直接使用内存中的数据
                nodes_file = f"resultTxt/{user_folder}/nodes_{industry_name}.txt"
                relations_file = f"resultTxt/{user_folder}/relations_{industry_name}.txt"
                
                if not os.path.exists(nodes_file) or not os.path.exists(relations_file):
                    log_message(user_id, f"节点或关系文件不存在: {nodes_file} 或 {relations_file}", log_type="ERROR")
                    await send_message(f"节点或关系文件不存在，无法存储结构数据", "Error")
                #     # 不再更新状态
                #     # if record_id:
                #     #     await IndustryStorageService.mark_as_failed(record_id, "节点或关系文件不存在")
                has_failure = True  # 标记失败
                #     return
                
                structure_stored = await IndustryStructureService.parse_and_store_structure(
                    storage_name, user_id, pid, record_id  # 使用存储名称
                )

                if structure_stored:
                    structure_data = await IndustryStructureService.get_structure_from_db(storage_name)  # 使用存储名称

                    # 修改：将图谱数据作为内部消息发送，不在聊天界面显示
                    # 使用特殊的消息类型"graph_internal"来标识这是内部图谱数据
                    graph_message = f"relations:{json.dumps(structure_data['relations'])}\nnodes:{json.dumps(structure_data['nodes'])}"
                    await send_message(graph_message, "3")

                    # 只显示完成提示给用户，使用type "2"确保在聊天界面显示
                    await send_message(f"任务五：生成{storage_name}产业链图谱完成", "2")

                    # 钉钉通知已移至前端触发：前端确认"任务五完成"渲染后调用 notify_task5_complete 端点
                    try:
                        import pymysql
                        meta_conn = pymysql.connect(
                            host=os.getenv('DB_HOST', '8.141.5.67'),
                            user=os.getenv('DB_USER', 'root'),
                            password=os.getenv('DB_PASSWORD'),
                            database=os.getenv('DB_NAME_CHAIN', 'industrial_chain'),
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
                        log_message(user_id, f"✅ 任务五完成，已将产业链 {industry_name} 状态设置为已完成(2)", log_type="INFO")
                    except Exception as status_e:
                        log_message(user_id, f"⚠️ 更新产业链状态失败: {status_e}", log_type="ERROR")
                    
                    
                    # 第六步：处理网页数据并生成报告
                    if record_id:
                        # 检查是否有文章内容，没有文章内容时跳过任务六
                        if not collected_articles or len(collected_articles) == 0 or skip_tasks_2_3:
                            log_message(user_id, f"没有文章内容，跳过任务六", log_type="WARNING")
                            await send_message(f"任务六：处理网页数据并生成{industry_name}产业链分析报告跳过（无文章内容）", "Error")
                        else:
                            await send_message(f"任务六：处理网页数据并生成{industry_name}产业链分析报告", "1")
                        
                        # 使用优化后的报告编排器
                        report_orchestrator = OptimizedReportOrchestrator()
                        
                        analysis_data = {
                            'industry_info': {'name': industry_name},
                            'nodes': structure_data.get('nodes', []),
                            'relations': structure_data.get('relations', []),
                            'complete_data': structure_data,
                            'collected_articles': collected_articles
                        }
                        
                        # 检查是否已取消
                        if cancel_flag and cancel_flag.is_set():
                            log_message(user_id, f"产业链分析已被取消: {industry_name}", log_type="INFO")
                            if record_id:
                                await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 取消了任务")
                                has_failure = True  # 标记失败
                            await send_message(f"产业链分析已被取消", "End")
                            return
                            
                        # 使用传入的历史报告配置
                        # historical_config 已经通过函数参数传入
                        
                        # 生成报告（支持历史报告分析）
                        result = await report_orchestrator.generate_reports(
                            analysis_data, user_id, cancel_flag, historical_config
                        )
                        
                        if result['status'] == 'success':
                            await send_message(f"任务六：处理网页数据并生成{industry_name}产业链分析报告完成", "2")

                            # 第一阶段只发一次钉钉通知（任务五，已移至前端触发），任务六不再发送
                            await send_message(f"精简版报告: {result['saved_paths'].get('simple', '')}", "Info")
                            await send_message(f"详细版报告: {result['saved_paths'].get('detailed', '')}", "Info")
                            
                            # 简单的任务完成消息
                            nodes_count = len(nodes) if 'nodes' in locals() else 0
                            articles_count = len(collected_articles) if 'collected_articles' in locals() else 0
                            stats_message = f"本次任务完成，共生成节点数量：{nodes_count}个，检索{articles_count}篇文章"
                            await send_message(stats_message, "TaskSummary")
                        else:
                            await send_message(f"报告生成失败: {result.get('error', '未知错误')}", "Error")
                    else:
                        log_message(user_id, "无有效记录ID，跳过报告生成", log_type="WARNING")
                        await send_message(f"任务五：生成{industry_name}产业链图谱完成", "2")
                        # 任务五完成后，更新产业���状态为"已完成"(2)
                        try:
                            import pymysql
                            meta_conn = pymysql.connect(
                                host=os.getenv('DB_HOST', '8.141.5.67'),
                                user=os.getenv('DB_USER', 'root'),
                                password=os.getenv('DB_PASSWORD'),
                                database=os.getenv('DB_NAME_CHAIN', 'industrial_chain'),
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
                            log_message(user_id, f"✅ 任务五完成，已将产业链 {industry_name} 状态设置为已完成(2)", log_type="INFO")
                        except Exception as status_e:
                            log_message(user_id, f"⚠️ 更新产业链状态失败: {status_e}", log_type="ERROR")
                        
                break  # 如果一切顺利，退出循环
                
            except Exception as e:
                attempts += 1
                log_message(user_id, f"解析失败，第 {attempts} 次尝试: {e}", log_type="ERROR")
                await send_message(f"解析失败，第 {attempts} 次尝试: {e}", "Error")
                
                # 详细记录错误信息
                import traceback
                error_trace = traceback.format_exc()
                log_message(user_id, f"错误详情: {error_trace}", log_type="ERROR")
                
                # 检查是否已取消
                if cancel_flag and cancel_flag.is_set():
                    log_message(user_id, f"产业链分析已被取消: {industry_name}", log_type="INFO")
                    if record_id:
                        await IndustryStorageService.mark_as_failed(record_id, f"用户 {user_id} 取消了任务")
                        has_failure = True  # 标记失败
                    await send_message(f"产业链分析已被取消", "End")
                    return
                
                if attempts >= max_attempts:
                    log_message(user_id, "任务四达到最大尝试次数，标记为失败", log_type="ERROR")
                    await send_message("任务四：构建产业链节点关系失败，达到最大尝试次数", "Error")
                    # 更新状态：失败 - 
                    if record_id:
                        try:
                            await IndustryStorageService.mark_as_failed(record_id, f"任务四解析失败，达到最大尝试次数: {str(e)[:200]}")
                            has_failure = True  # 标记失败
                            log_message(user_id, f"已将产业链记录 {record_id} 标记为失败（任务四失败）", log_type="INFO")
                        except Exception as mark_error:
                            log_message(user_id, f"标记失败状态时出错: {mark_error}", log_type="ERROR")
                    break

    except Exception as e:
        # 详细记录错误信息
        import traceback
        error_trace = traceback.format_exc()
        log_message(user_id, f"处理产业链过程中发生未预期错误: {e}", log_type="CRITICAL")
        log_message(user_id, f"错误详情: {error_trace}", log_type="ERROR")
        
        await send_message(f"处理产业链 {industry_name} 时发生系统错误: {str(e)[:100]}...", "Error")
        
        # 更新状态：失败
        if record_id:
            try:
                error_msg = f"系统异常: {str(e)[:200]}"
                await IndustryStorageService.mark_as_failed(record_id, error_msg)
                has_failure = True  # 标记失败
                log_message(user_id, f"已将产业链记录 {record_id} 标记为失败（系统异常）", log_type="INFO")
                
                # 同时更新相关数据表状态 
                try:
                    from database.industrial_chain.connection import get_connection
                    conn = await get_connection()
                    cursor = conn.cursor()
                    
                    # 将相关的产业链结构记录标记为无效
                    structure_update_query = """
                    UPDATE industrial_chain_structure 
                    SET status = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE chain_id = %s
                    """
                    cursor.execute(structure_update_query, (record_id,))
                    affected_structure = cursor.rowcount
                    
                    # 将相关的节点文章链接标记为无效
                    article_update_query = """
                    UPDATE node_article_links 
                    SET status = 0, created_at = CURRENT_TIMESTAMP
                    WHERE chain_name = %s
                    """
                    cursor.execute(article_update_query, (industry_name,))
                    affected_articles = cursor.rowcount
                    
                    conn.commit()
                    conn.close()
                    
                    log_message(user_id, f"已清理相关数据: 结构记录 {affected_structure} 条，文章链接 {affected_articles} 条", log_type="INFO")
                    
                except Exception as cleanup_error:
                    log_message(user_id, f"清理相关数据时出错: {cleanup_error}", log_type="WARNING")
                    
            except Exception as mark_error:
                log_message(user_id, f"标记失败状态时出错: {mark_error}", log_type="ERROR")
        return
    finally:
        # 确保在所有情况下都发送结束消息
        await send_message(f"产业链处理结束", "End")
        # 任务完成后���更新状态为"已完成"
        if record_id and not has_failure:
            try:
                await IndustryStorageService.update_status(record_id, "已完成")
                log_message(user_id, f"产业链 {record_id} 已标记为已完成", log_type="INFO")
            except Exception as e:
                log_message(user_id, f"更新记录状态时出错: {e}", log_type="ERROR")
            log_message(user_id, f"更新记录状态时出错: {e}", log_type="ERROR")
