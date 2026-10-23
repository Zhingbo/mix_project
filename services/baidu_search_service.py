"""
基于百度搜索的产业链搜��服务
接口设计与 JinaSearcher 兼容，可直接替换
"""
import asyncio
import hashlib
import re
import time
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse, unquote

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'baidu_spider', 'baidu_spider'))
import baidu_improved
import baidu_data_extractor

from utils.logger import get_logger
from services.crawler_service import log_message

logger = get_logger(__name__)


class BaiduSearcher:
    """
    百度搜索服务类
    接口与 JinaSearcher 兼容，用于产业链搜索
    """

    def __init__(self, url=None, headers=None, industry_name="", default_sites=None):
        self.industry_name = industry_name
        self.default_sites = default_sites or []
        self.search_cache = {}
        self.cache_ttl = 3600

        log_message(None, f"BaiduSearcher初始化完成，产业：{industry_name}", log_type="INFO")

    def _get_cache_key(self, data):
        """生成缓存键"""
        return hashlib.md5(str(data).encode()).hexdigest()

    def _is_cache_valid(self, timestamp):
        """检查缓存是否有效"""
        return time.time() - timestamp < self.cache_ttl

    def _extract_real_url(self, baidu_link: str) -> str:
        """从百度跳转链接中提取真实URL"""
        if not baidu_link:
            return ""

        # 如果不是百度跳转链接，直接返回
        if 'baidu.com/link' not in baidu_link:
            # 检查是否是有效的URL
            if baidu_link.startswith('http://') or baidu_link.startswith('https://'):
                return baidu_link
            return baidu_link

        try:
            import requests
            # 尝试通过HTTP请求获取真实URL
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })

            try:
                # 使用HEAD请求获取重定向URL
                response = session.head(
                    baidu_link,
                    allow_redirects=True,
                    timeout=5
                )
                if response.url and response.url != baidu_link and 'baidu.com/link' not in response.url:
                    return response.url
            except:
                pass

            # 如果HEAD失败，尝试GET（只获取头部）
            try:
                response = session.get(
                    baidu_link,
                    allow_redirects=True,
                    stream=True,
                    timeout=5
                )
                if response.url and response.url != baidu_link and 'baidu.com/link' not in response.url:
                    # 立即关闭连接
                    response.close()
                    return response.url
            except:
                pass

            # 如果无法通过HTTP获取，尝试从查询参数解析
            parsed = urlparse(baidu_link)
            params = parse_qs(parsed.query)

            if 'url' in params:
                real_url = params['url'][0]
                real_url = unquote(real_url)
                if real_url.startswith(('http://', 'https://')):
                    return real_url

            # 如果都失败，返回原链接（但记录日志）
            log_message(None, f"无法解析百度链接，使用原链接", log_type="DEBUG")
            return baidu_link

        except Exception as e:
            log_message(None, f"解析URL失败: {e}", log_type="DEBUG")
            return baidu_link

    def _is_valid_industry_result(self, result: Dict) -> bool:
        """验证结果是否与产业相关"""
        title = result.get('title', '')
        description = result.get('description', '')

        # 基本验证：标题不能为空或太短
        if not title or len(title) < 5:
            return False

        # 只排除明显无关的百度内部链接
        exclude_patterns = ['baidu.com/link?url=zhidao', 'baidu.com/link?url=ting']
        url = result.get('url', '')
        for pattern in exclude_patterns:
            if pattern in url:
                return False

        # 放宽过滤条件：只要有一定长度的描述就接受
        # 不再强制要求包含特定关键词
        return True

    def _parse_baidu_results(self, raw_results: List[Dict]) -> List[Dict]:
        """解析百度搜索结果为统一格式"""
        parsed_results = []

        for result in raw_results:
            try:
                # 提取真实URL
                real_url = self._extract_real_url(result.get('real_url', result.get('url', '')))

                parsed_result = {
                    'title': result.get('title', ''),
                    'url': real_url,
                    'content': result.get('description', ''),
                    'source': result.get('source_domain', ''),
                    'description': result.get('description', '')
                }

                # 过滤无效结果
                if self._is_valid_industry_result(parsed_result):
                    parsed_results.append(parsed_result)

            except Exception as e:
                log_message(None, f"解析结果失败: {e}", log_type="DEBUG")
                continue

        return parsed_results

    async def search(self, query: str, limit: int = 20) -> Optional[Dict]:
        """
        通用搜索方法
        与 JinaSearcher.search() 接口兼容

        Args:
            query: 搜索关键词
            limit: 返回结果数量限制

        Returns:
            {'results': [{'title': '', 'url': '', 'content': ''}, ...]}
        """
        try:
            log_message(None, f"🔍 百度搜索: {query} (limit={limit})", log_type="INFO")

            # 检查缓存
            cache_key = self._get_cache_key({'query': query, 'limit': limit})
            if cache_key in self.search_cache:
                cached_item = self.search_cache[cache_key]
                if self._is_cache_valid(cached_item['timestamp']):
                    log_message(None, f"使用缓存的搜索结果: {query}", log_type="INFO")
                    return cached_item['data']

            # 构建搜索关键词
            # 如果查询词不包含"产业链"，自动添加
            search_keyword = query
            if '产业链' not in query and '产业' not in query:
                search_keyword = f"{query} 产业链"

            # 执行百度搜索（2-3页）
            log_message(None, f"📡 开始百度多页搜索: {search_keyword}", log_type="DEBUG")

            raw_results = await asyncio.to_thread(
                baidu_improved.search_multiple_pages,
                search_keyword,
                max_pages=3
            )

            if not raw_results:
                log_message(None, f"⚠️ 百度搜索未获取到结果", log_type="WARNING")
                return None

            # 解析结果
            parsed_results = self._parse_baidu_results(raw_results)

            # 限制结果数量
            parsed_results = parsed_results[:limit]

            # 构造返回格式（与Jina兼容）
            response = {
                'results': parsed_results,
                'total': len(parsed_results)
            }

            # 缓存结果
            self.search_cache[cache_key] = {
                'data': response,
                'timestamp': time.time()
            }

            log_message(None, f"✅ 百度搜索成功，获取到 {len(parsed_results)} 条有效结果", log_type="INFO")

            return response

        except Exception as e:
            log_message(None, f"❌ 百度搜索失败: {e}", log_type="ERROR")
            return None

    async def search_with_site(self, query: str, site_constraint: str) -> Optional[Dict]:
        """
        站点限制搜索方法
        与 JinaSearcher.search_with_site() 接口兼容

        Args:
            query: 搜索关键词
            site_constraint: 站点约束，如 "site:qianzhan.com" 或 "qianzhan.com"

        Returns:
            {'results': [{'title': '', 'url': '', 'content': ''}, ...]}
        """
        try:
            # 从site_constraint中提取域名
            if "site:" in site_constraint:
                domain = site_constraint.replace("site:", "")
            else:
                domain = site_constraint

            log_message(None, f"🔍 百度站点搜索: {query} site:{domain}", log_type="INFO")

            # 构建搜索关键词
            search_keyword = f"{query} site:{domain}"

            # 执行搜索
            raw_results = await asyncio.to_thread(
                baidu_improved.search_multiple_pages,
                search_keyword,
                max_pages=2
            )

            if not raw_results:
                log_message(None, f"⚠️ 百度站点搜索未获取到结果", log_type="WARNING")
                return None

            # 解析结果
            parsed_results = self._parse_baidu_results(raw_results)

            # 构造返回格式
            response = {
                'results': parsed_results,
                'total': len(parsed_results)
            }

            log_message(None, f"✅ 百度站点搜索成功，获取到 {len(parsed_results)} 条结果", log_type="INFO")

            return response

        except Exception as e:
            log_message(None, f"❌ 百度站点搜索失败: {e}", log_type="ERROR")
            return None

    async def get_page_content(self, url: str, user_id: Optional[str] = None) -> Optional[str]:
        """
        获取页面完整内容
        使用 requests + BeautifulSoup 提取页面主要内容
        """
        try:
            import requests
            from bs4 import BeautifulSoup

            log_message(user_id, f"📄 获取页面内容: {url}", log_type="DEBUG")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }

            response = await asyncio.to_thread(
                requests.get,
                url,
                headers=headers,
                timeout=30
            )

            if response.status_code != 200:
                log_message(user_id, f"⚠️ 页面请求失败: HTTP {response.status_code}", log_type="WARNING")
                return None

            soup = BeautifulSoup(response.text, 'html.parser')

            # 移除不需要的标签
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
                tag.decompose()

            # 尝试找到主要内容区域
            content_selectors = [
                'article',
                'main',
                '[class*="content"]',
                '[class*="article"]',
                '[id*="content"]',
                '[id*="article"]',
                '.detail-content',
                '.article-content',
                '.news-content'
            ]

            content_element = None
            for selector in content_selectors:
                content_element = soup.select_one(selector)
                if content_element:
                    break

            if content_element:
                text = content_element.get_text(separator='\n', strip=True)
            else:
                # 如果没找到主要内容区域，使用整个body
                body = soup.find('body')
                text = body.get_text(separator='\n', strip=True) if body else soup.get_text(separator='\n', strip=True)

            # 清理文本
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            cleaned_text = '\n'.join(lines)

            # 限制内容长度
            if len(cleaned_text) > 10000:
                cleaned_text = cleaned_text[:10000]

            if len(cleaned_text) < 100:
                log_message(user_id, f"⚠️ 页面内容过短: {len(cleaned_text)} 字符", log_type="WARNING")
                return None

            log_message(user_id, f"✅ 成功获取页面内容: {len(cleaned_text)} 字符", log_type="DEBUG")
            return cleaned_text

        except Exception as e:
            log_message(user_id, f"❌ 获取页面内容失败: {e}", log_type="ERROR")
            return None


# 测试代码
async def main():
    """测试百度搜索服务"""
    searcher = BaiduSearcher(industry_name="锂电池")

    # 测试通用搜索
    print("\n=== 测试通用搜索 ===")
    results = await searcher.search("锂电池 产业链")
    if results and results.get('results'):
        print(f"获取到 {len(results['results'])} 条结果:")
        for i, r in enumerate(results['results'][:5], 1):
            print(f"\n{i}. {r['title']}")
            print(f"   URL: {r['url']}")
            print(f"   来源: {r.get('source', 'N/A')}")
            if r.get('content'):
                content = r['content'][:100] + '...' if len(r['content']) > 100 else r['content']
                print(f"   摘要: {content}")

    # 测试站点搜索
    print("\n\n=== 测试站点搜索 ===")
    results = await searcher.search_with_site("锂电池 产业链", "site:qianzhan.com")
    if results and results.get('results'):
        print(f"获取到 {len(results['results'])} 条结果:")
        for i, r in enumerate(results['results'][:3], 1):
            print(f"\n{i}. {r['title']}")
            print(f"   URL: {r['url']}")


if __name__ == "__main__":
    asyncio.run(main())
