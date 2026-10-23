import re
import requests
from urllib.parse import parse_qs, urlparse, unquote
from bs4 import BeautifulSoup
from typing import List, Dict


class BaiduDataExtractor:
    def __init__(self):
        self.soup = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    def load_html_content(self, html_content: str):
        self.soup = BeautifulSoup(html_content, 'html.parser')
    
    def extract_real_url(self, baidu_link: str) -> str:
        if not baidu_link:
            return ""

        # 如果不是百度跳转链接，直接返回
        if 'baidu.com/link' not in baidu_link:
            if baidu_link.startswith(('http://', 'https://')):
                return baidu_link
            return baidu_link

        try:
            # 首先尝试从查询参数解析
            parsed = urlparse(baidu_link)
            params = parse_qs(parsed.query)

            if 'url' in params:
                encoded_url = params['url'][0]
                # 尝试URL解码
                decoded = unquote(encoded_url)
                if decoded.startswith(('http://', 'https://')):
                    return decoded

            # 实际访问链接获取重定向后的真实URL
            try:
                response = self.session.head(
                    baidu_link,
                    allow_redirects=True,
                    timeout=5
                )
                if response.url and response.url != baidu_link:
                    # 成功获取重定向后的URL
                    return response.url
            except Exception as e:
                # HEAD请求失败，尝试GET
                try:
                    response = self.session.get(
                        baidu_link,
                        allow_redirects=True,
                        timeout=5
                    )
                    if response.url and response.url != baidu_link:
                        return response.url
                except:
                    pass

            # 如果都无法解析，返回原链接
            return baidu_link
        except Exception:
            return baidu_link
    
    def clean_text(self, text: str) -> str:
        if not text:
            return ""
        return re.sub(r'\s+', ' ', text.strip())
    
    def extract_search_results(self) -> List[Dict]:
        if not self.soup:
            return []

        results = []
        result_containers = self._find_result_containers()

        for i, container in enumerate(result_containers):
            try:
                result = self.extract_single_result(container, i + 1)
                if self._is_valid_search_result(result):
                    results.append(result)
            except Exception:
                continue

        return results

    def _find_result_containers(self) -> list:
        containers = []
        
        # 直接查找带 c-result 类的元素
        c_results = self.soup.select('.c-result')
        if c_results:
            containers.extend(c_results)
        
        # 备用选择器
        if len(containers) < 3:
            standard_selectors = [
                'div.result.c-container',
                'div.result',
                'div.c-container[tpl]',
            ]
            for selector in standard_selectors:
                found = self.soup.select(selector)
                if found:
                    containers.extend(found)

        if len(containers) < 3:
            broad_selectors = ['div[id*="result"]', 'div[class*="result"]', 'div.c-container']
            for selector in broad_selectors:
                found = self.soup.select(selector)
                for container in found:
                    if self._looks_like_search_result(container) and container not in containers:
                        containers.append(container)

        unique_containers = []
        seen = set()
        for container in containers:
            container_id = id(container)
            if container_id not in seen:
                seen.add(container_id)
                unique_containers.append(container)

        return unique_containers

    def _looks_like_search_result(self, container) -> bool:
        # 查找标题链接
        title_link = self.find_title_link(container)
        if not title_link:
            return False
            
        # 检查链接有效性
        href = title_link.get('href', '')
        if not href:
            return False
            
        text_content = container.get_text().strip()
        if len(text_content) < 20:
            return False
            
        return True

    def _is_valid_search_result(self, result: Dict) -> bool:
        if not result:
            return False
        title = result.get('title', '').strip()
        if not title or len(title) < 3:
            return False
        if self._is_navigation_link(title):
            return False
        url = result.get('url', '').strip()
        if not url:
            return False
        return True
    
    def extract_single_result(self, container, index: int) -> Dict:
        result = {
            'index': index,
            'title': '',
            'url': '',
            'real_url': '',
            'description': '',
            'source_domain': ''
        }
        
        title_link = self.find_title_link(container)
        if title_link:
            result['title'] = self.clean_text(title_link.get_text())
            result['url'] = title_link.get('href', '')
            result['real_url'] = self.extract_real_url(result['url'])
            
            if result['real_url']:
                try:
                    parsed_url = urlparse(result['real_url'])
                    result['source_domain'] = parsed_url.netloc
                except:
                    pass
        
        description = self.find_description(container)
        if description:
            result['description'] = self.clean_text(description)
        
        source_url = self.find_source_url(container)
        if source_url:
            result['displayed_source'] = self.clean_text(source_url)
        
        return result
    
    def find_title_link(self, container):
        """在容器中查找标题链接"""
        # 移动版百度优先（无h3，使用a标签）
        selectors = [
            'a.cosc-title-a[href]',
            'h3.cosc-title a',
            'a.c-title',
            'h3 a[href*="baidu.com/link"]',
            'h3 a[href*="www.baidu.com/link"]',
            'h3 a[href]',
            'h3 a[href*="m.baidu.com/from"]',
            'h3.t a',
            'h3.c-title a',
            'a.sc-link[href]',
            'a[data-module="title"]',
            'a[href*="baidu.com/link"]',
        ]

        for selector in selectors:
            elements = container.select(selector)
            for element in elements:
                text = element.get_text().strip()
                href = element.get('href', '')
                
                # 跳过无效链接
                if not href:
                    continue
                    
                # 跳过纯导航链接
                if not text or len(text) < 3:
                    continue
                    
                # 跳过百度内部跳转链接（移动版相关搜索）
                if 'm.baidu.com/from' in href and 's?word=' in href:
                    continue
                    
                if self._is_navigation_link(text):
                    continue
                    
                return element

        # 如果还没找到，尝试查找任何有意义的链接
        all_links = container.find_all('a', href=True)
        for link in all_links:
            text = link.get_text().strip()
            href = link.get('href', '')
            
            if text and len(text) > 5 and href:
                # 检查是否是外部链接（非百度内部）
                if not any(x in href for x in ['m.baidu.com/from', 'baidu.com/link?url=']):
                    return link

        return None

    def _is_navigation_link(self, text: str) -> bool:
        """判断是否为导航链接"""
        nav_patterns = [
            '百度', '搜索', '首页', '登录', '注册', '设置', '更多',
            '图片', '视频', '贴吧', '学术', '地图', '更多产品',
            '下一页', '上一页', '相关搜索'
        ]

        text_lower = text.lower().strip()

        if len(text_lower) <= 1:
            return True

        for pattern in nav_patterns:
            if pattern in text or text in pattern:
                return True

        return False
    
    def find_description(self, container) -> str:
        """在容器中查找描述文本"""
        selectors = [
            'div.c-abstract',
            'span.c-abstract',
            'div.c-span-last',
            'div.c-row .c-span-last',
            'p.op_sp_fanyi_line_two',
            'div.c-summary',
            'span.content-right_8Zs40',
            'div[class*="abstract"]',
            'div[class*="summary"]',
            'span[class*="abstract"]',
        ]

        for selector in selectors:
            elements = container.select(selector)
            for element in elements:
                text = element.get_text().strip()
                if self._is_valid_description(text):
                    return self.clean_text(text)

        return self._extract_description_from_container(container)

    def _is_valid_description(self, text: str) -> bool:
        """判断文本是否为有效的描述"""
        if not text or len(text.strip()) < 10:
            return False

        invalid_patterns = [
            '百度', '搜索', '首页', '登录', '注册',
            '更多', '下一页', '上一页', '相关搜索',
            '官方', '网站', '链接', '点击',
            '查看更多', '展开', '收起'
        ]

        if len(text.strip()) < 15:
            return False

        nav_count = sum(1 for pattern in invalid_patterns if pattern in text)
        if nav_count > 2:
            return False

        return True

    def _extract_description_from_container(self, container) -> str:
        """从容器中提取描述文本"""
        title_text = ""
        title_link = self.find_title_link(container)
        if title_link:
            title_text = title_link.get_text().strip()

        all_text = container.get_text()

        if title_text and title_text in all_text:
            remaining_text = all_text.replace(title_text, '', 1)
        else:
            remaining_text = all_text

        cleaned_text = self.clean_text(remaining_text)

        if len(cleaned_text) > 300:
            for i in range(200, min(300, len(cleaned_text))):
                if cleaned_text[i] in '。！？.!?':
                    return cleaned_text[:i+1]
            return cleaned_text[:200] + '...'

        return cleaned_text if len(cleaned_text) > 15 else ""
    
    def find_source_url(self, container) -> str:
        """在容器中查找显示的来源URL"""
        selectors = [
            'cite',
            'span.c-showurl',
            'a.c-showurl',
            'span.g',
        ]
        
        for selector in selectors:
            element = container.select_one(selector)
            if element:
                return element.get_text().strip()
        
        return ""
