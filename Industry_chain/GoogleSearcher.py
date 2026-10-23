import requests
import time

class GoogleSearcher:
    def __init__(self, url, headers, industry_name):
        self.url = url
        self.headers = headers
        self.industry_name = industry_name

    def google_search(self, limit=5, isNode=False, node=""):
        # 第一步：优先使用特定的三个网站进行搜索
        if isNode:
            specific_query = {"query": f"{self.industry_name}相关的{node}产业链信息 site:qianzhan.com OR site:zhihu.com OR site:askci.com",
                              "limit": limit, "related_keywords": "false"}
        else:
            specific_query = {"query": f"{self.industry_name}的产业链信息 site:qianzhan.com OR site:zhihu.com OR site:askci.com",
                              "limit": limit, "related_keywords": "false"}

        print(f"正在搜索：{specific_query}")
        specific_response = self._make_request(specific_query)
        if specific_response is not None:
            # 如果特定网站搜索成功，尝试解析返回的链接
            links = specific_response.get("links", [])
            if links:
                parsed_data = self._parse_links(links)
                if parsed_data:
                    return parsed_data
                else:
                    print("所有链接解析失败，尝试普通搜索")
            else:
                print("未获取到有效链接，尝试普通搜索")

        # 第二步：如果特定网站搜索失败，尝试普通搜索
        print("特定网站未搜索到相关内容，尝试普通搜索")
        if isNode:
            general_query = {"query": f"{self.industry_name}相关的{node}产业链信息",
                             "limit": limit, "related_keywords": "false"}
        else:
            general_query = {"query": f"{self.industry_name}的产业链信息",
                             "limit": limit, "related_keywords": "false"}

        general_response = self._make_request(general_query)
        return general_response

    def _make_request(self, querystring, retries=3, delay=2):
        for attempt in range(retries):
            try:
                response = requests.get(self.url, headers=self.headers, params=querystring, timeout=10)
                response.raise_for_status()
                data = response.json()
                if data.get("error"):
                    print(f"Error in response: {data['error']}")
                    return None
                return data
            except requests.exceptions.RequestException as e:
                print(f"Attempt {attempt + 1}/{retries} failed: {e}")
                time.sleep(delay)
        print("All attempts failed.")
        return None

    def _parse_links(self, links):
        parsed_data = []
        for link in links:
            try:
                # 模拟解析链接内容
                print(f"尝试解析链接：{link}")
                # 这里可以添加具体的解析逻辑，例如使用requests获取网页内容
                # 示例：response = requests.get(link)
                # 示例：parsed_data.append(response.text)
                parsed_data.append(f"解析成功：{link}")
            except Exception as e:
                print(f"解析链接 {link} 时失败：{e}")
        if parsed_data:
            return parsed_data
        return None