import asyncio
import aiohttp
from utils.logger import get_logger
from services.crawler_service import log_message

logger = get_logger(__name__)

class GoogleSearcher:
    def __init__(self, url, headers, industry_name, default_sites=None):
        self.url = url
        self.headers = headers
        self.industry_name = industry_name
        # 设置默认搜索网站，如果未指定则使用默认值
        self.default_sites = default_sites or ["qianzhan.com", "askci.com"]

    async def google_search(self, limit=20, isNode=False, node="", user_id=None, send_message=None, sites=None, is_retry=False):
        # 使用传入的网站列表，如果未指定则使用实例的默认值
        search_sites = sites or self.default_sites
        query = (
            f"{self.industry_name}相关的{node}产业链信息 site:{' OR site:'.join(search_sites)}"
            if isNode
            else f"{self.industry_name}的产业链信息 site:{' OR site:'.join(search_sites)}"
        )
        # 构造正在搜索的消息，只有在非重试情况下才发送
        if send_message and not is_retry:
            if isNode:
                search_message = f'正在搜索："{self.industry_name}"产业链相关的"{node}"节点信息，搜索来源：'
            else:
                search_message = f'正在搜索："{self.industry_name}"的产业链信息，搜索来源：'
            await send_message(search_message, "2")
        response = await self._make_request({"query": query, "limit": limit, "related_keywords": "false"}, user_id, send_message)
        if response is not None:
            # 直接从响应中提取 URL、标题和摘要
            results = response.get("results", [])
            if results:
                for result in results:
                    # 只在非重试情况下发送搜索结果
                    if send_message and not is_retry:
                        # 发送标题和来源网站
                        await send_message(f"{result['title']} url:{result['url']}", "5")  # 获取标题和来源网站
                        await send_message(f"{result['description']}", "5")  # 获取摘要
                return results

        # 如果指定网站未搜索到相关内容，尝试普通搜索
        if (send_message and not is_retry) or not sites:
            await send_message("特定网站未搜索到相关内容，尝试普通搜索", "2")
            general_query = (
                f"{self.industry_name}相关的{node}产业链信息"
                if isNode
                else f"{self.industry_name}的产业链信息"
            )
            general_response = await self._make_request({"query": general_query, "limit": limit, "related_keywords": "false"}, user_id, send_message)
            if general_response is not None:
                results = general_response.get("results", [])
                if results:
                    for result in results:
                        # 只在非重试情况下发送搜索结果
                        if send_message and not is_retry:
                            # 发送标题和来源网站
                            await send_message(f"{result['title']} (url:{result['url']})", "5")  # 获取标题和来源网站
                            await send_message(f"{result['description']}", "5")  # 获取摘要
                    return results
            return None

    async def _make_request(self, querystring, user_id, send_message=None, retries=3, delay=2):
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.url, headers=self.headers, params=querystring, timeout=10) as response:
                        response.raise_for_status()
                        data = await response.json()
                        if data.get("error"):
                            log_message(user_id, f"Error in response: {data['error']}", log_type="ERROR")
                            return None
                        # 确保返回的数据包含 URL、标题和摘要
                        if "results" in data:
                            return data
                        else:
                            log_message(user_id, "Response does not contain 'results' field", log_type="ERROR")
                            return None
            except aiohttp.ClientResponseError as e:
                if e.status == 403:
                    error_message = (
                        f"尝试访问 {self.url} 时遇到 403 Forbidden 错误。这可能是由于以下原因之一：\n"
                        "1. API 密钥无效或权限不足。\n"
                        "2. 链接格式问题，某些自定义 URL 可能包含特殊字符。\n"
                        "3. 网络问题，导致请求无法正常到达服务器。"
                    )
                    log_message(user_id, error_message, log_type="ERROR")
                elif e.status == 429:
                    error_message = (
                        f"尝试访问 {self.url} 时遇到 429 Too Many Requests 错误。这表示您达到了 API 提供商设定的请求频率限制。\n"
                        "请适当减少请求频率，稍后再试。"
                    )
                    log_message(user_id, error_message, log_type="ERROR")
                    await asyncio.sleep(10)  # 增加延迟，等待10秒后再试
                else:
                    error_message2 = (
                        f"Attempt {attempt + 1}/{retries} failed with status {e.status}: {e}"
                    )
                    log_message(user_id, error_message2, log_type="ERROR")
            except aiohttp.ClientError as e:
                error_message3 = (
                    f"Attempt {attempt + 1}/{retries} failed: {e}"
                )
                log_message(user_id, error_message3, log_type="ERROR")
            await asyncio.sleep(delay)
        return None