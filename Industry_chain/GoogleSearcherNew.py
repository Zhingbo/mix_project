import aiohttp
import asyncio
import json

class GoogleSearcher:
    def __init__(self, url, headers, industry_name):
        self.url = url
        self.headers = headers
        self.industry_name = industry_name

    async def google_search(self, limit=5, isNode=False, node="", websocket=None, user_id=None):
        # 第一步：优先使用特定的三个网站进行搜索
        if isNode:
            specific_query = {"query": f"{self.industry_name}相关的{node}产业链信息 site:qianzhan.com OR site:zhihu.com OR site:askci.com",
                            "limit": limit, "related_keywords": "false"}
        else:
            specific_query = {"query": f"{self.industry_name}的产业链信息 site:qianzhan.com OR site:zhihu.com OR site:askci.com",
                            "limit": limit, "related_keywords": "false"}

        if websocket:
            await websocket.send_text(f"正在搜索：{specific_query['query']}")

        specific_response = await self._make_request(specific_query, websocket, user_id)
        if specific_response is not None:
            links = specific_response.get("links", [])
            if links:
                parsed_data = await self._parse_links(links, websocket, user_id)  # 使用 await 调用
                if parsed_data:
                    if websocket:
                        await websocket.send_text(f"特定网站搜索成功，解析到链接：{parsed_data}")
                    return parsed_data
                else:
                    if websocket:
                        await websocket.send_text("所有链接解析失败，尝试普通搜索")
            else:
                if websocket:
                    await websocket.send_text("未获取到有效链接，尝试普通搜索")

        # 第二步：如果特定网站搜索失败，尝试普通搜索
        if websocket:
            await websocket.send_text("特定网站未搜索到相关内容，尝试普通搜索")
        if isNode:
            general_query = {"query": f"{self.industry_name}相关的{node}产业链信息",
                            "limit": limit, "related_keywords": "false"}
        else:
            general_query = {"query": f"{self.industry_name}的产业链信息",
                            "limit": limit, "related_keywords": "false"}

        general_response = await self._make_request(general_query, websocket, user_id)
        return general_response

    async def _make_request(self, querystring, websocket=None, user_id=None, retries=3, delay=2):
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.url, headers=self.headers, params=querystring, timeout=10) as response:
                        response.raise_for_status()
                        data = await response.json()
                        if data.get("error"):
                            if websocket:
                                await websocket.send_text(f"Error in response: {data['error']}")
                            return None
                        return data
            except aiohttp.ClientError as e:
                if websocket:
                    await websocket.send_text(f"Attempt {attempt + 1}/{retries} failed: {e}")
                await asyncio.sleep(delay)
        if websocket:
            await websocket.send_text("All attempts failed.")
        return None

    async def _parse_links(self, links, websocket=None, user_id=None):
        parsed_data = []
        for link in links:
            try:
                # 模拟解析链接内容
                print(f"尝试解析链接：{link}")
                parsed_data.append(f"解析成功：{link}")
            except Exception as e:
                print(f"解析链接 {link} 时失败：{e}")
                if websocket:
                    await websocket.send_text(f"解析链接 {link} 时失败：{e}")
        if parsed_data:
            return parsed_data
        return None