"""
第六步：也可以和第五步一起运行
工作流程：                                                                                                                                                                                       
                                                                                                                                                                                                   
  1. 加载白名单企业（xlsx/txt） → 直接入库，优先级最高                                                                                                                                             
                      ↓                                                                                                                                                                            
  2. 按环节搜索（上游/中游/下游）                                                                                                                                                                  
     - Jina API 搜索相关文章                                                                                                                                                                       
     - 通义千问分析文章提取企业名称                                                                                                                                                                
                      ↓                                                                                                                                                                            
  3. 智能去重                                                                                                                                                                                      
     - 识别同一公司的不同叫法（如"华为"和"华为技术有限公司"）                                                                                                                                      
     - 保留完整名称                                                                                                                                                                                
     - 白名单企业不会被替换                                                                                                                                                                        
                      ↓                                                                                                                                                                            
  4. 保存到数据库 industry_chain_topcompanies0421
"""

import requests
import json
from typing import List, Dict
import time
import logging
from datetime import datetime
from openai import OpenAI
import pymysql
from pymysql.cursors import DictCursor
from bs4 import BeautifulSoup
import os
import pandas as pd

# 目标表名配置
TARGET_TABLE = "industry_chain_topcompanies0421"

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/industry_chain_search_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)

class IndustryChainSearcher:
    def __init__(self):
        # 火山引擎 DeepSeek V3 API配置
        # self.deepseek_api_key = os.getenv("VOLCENGINE_ARK_API_KEY")
        # self.deepseek_base_url = "https://ark.cn-beijing.volces.com/api/v3"
        
        # Jina API配置
        self.jina_api_key = os.getenv("JINA_API_KEY_B")
        self.jina_base_url = "https://r.jina.ai"
        
        self.headers = {
            'Authorization': f'Bearer {self.jina_api_key}',
            'Content-Type': 'application/json'
        }
        
        # MySQL数据库配置
        self.db_config = {
            'host': '8.141.5.67',
            'port': 3306,
            'user': 'root',
            'password': os.getenv('DB_PASSWORD'),
            'database': 'business_data'
        }

    def _extract_core_name(self, company_name: str) -> str:
        """提取公司核心名称，用于相似度比较"""
        import re
        # 去除常见后缀
        suffixes = ['股份有限公司', '有限责任公司', '有限公司', '集团有限公司', '集团股份有限公司', 
                    '集团', '公司', '（中国）', '(中国)', '（上海）', '(上海)', '（北京）', '(北京)',
                    '（深圳）', '(深圳)', '（广州）', '(广州)']
        core_name = company_name
        for suffix in suffixes:
            core_name = core_name.replace(suffix, '')
        # 去除括号及其内容
        core_name = re.sub(r'[（(][^）)]*[）)]', '', core_name)
        return core_name.strip()

    def _is_similar_company(self, name1: str, name2: str) -> bool:
        """判断两个公司名称是否指向同一家公司"""
        core1 = self._extract_core_name(name1)
        core2 = self._extract_core_name(name2)
        # 核心名称相同
        if core1 == core2:
            return True
        # 一个包含另一个（处理简称情况，如"中际旭创"和"中际旭创股份有限公司"）
        if core1 in core2 or core2 in core1:
            # 确保较短的名称至少有2个字符，避免误匹配
            min_len = min(len(core1), len(core2))
            if min_len >= 2:
                return True
        return False

    def _load_whitelist_from_xlsx(self, industry_chain: str) -> Dict[str, List[str]]:
        """
        从 xlsx 文件读取白名单企业

        Args:
            industry_chain: 产业链名称

        Returns:
            dict: {"上游": [企业列表], "中游": [企业列表], "下游": [企业列表]}
        """
        whitelist = {"上游": [], "中游": [], "下游": []}

        # 尝试多个可能的文件名
        possible_filenames = [
            f"{industry_chain}-上中下游企业名录.xlsx",
            f"Industry_chain/{industry_chain}-上中下游企业名录.xlsx",
            f"{industry_chain}_上中下游企业名录.xlsx",
        ]

        for filename in possible_filenames:
            if os.path.exists(filename):
                try:
                    df = pd.read_excel(filename)
                    # 筛选当前产业链的数据
                    df_chain = df[df.iloc[:, 0].astype(str) == industry_chain]

                    if not df_chain.empty:
                        # 按上中下游分组
                        for position in ["上游", "中游", "下游"]:
                            df_position = df_chain[df_chain.iloc[:, 1].astype(str) == position]
                            companies = df_position.iloc[:, 2].dropna().astype(str).str.strip().tolist()
                            whitelist[position] = [c for c in companies if c and c != 'nan']

                        total = sum(len(v) for v in whitelist.values())
                        logging.info(f"从 xlsx 文件 {filename} 加载了 {total} 家白名单企业")
                        for pos, companies in whitelist.items():
                            if companies:
                                logging.info(f"  {pos}: {len(companies)} 家")
                        return whitelist

                except Exception as e:
                    logging.error(f"读取 xlsx 文件 {filename} 失败: {str(e)}")

        logging.warning(f"未找到 {industry_chain} 的 xlsx 白名单文件")
        return whitelist

    def _deduplicate_companies(self, companies: list, seen_companies: set, whitelist_set: set = None) -> tuple:
        """
        对公司列表进行智能去重，优先保留名称更完整的全称。
        白名单企业具有最高优先级，永远不会被AI搜索结果替换。

        Args:
            companies: 待去重的公司列表
            seen_companies: 已存在的公司集合（会被修改，用全称替换简称）
            whitelist_set: 白名单企业集合，其中的企业名称不可被替换

        Returns:
            tuple: (去重后的新公司列表, 需要从seen_companies中移除的简称列表)
        """
        if whitelist_set is None:
            whitelist_set = set()

        unique_companies = []
        to_remove_from_seen = []  # 需要从seen_companies中移除的简称
        to_add_to_seen = []  # 需要添加到seen_companies的全称

        for company in companies:
            is_duplicate = False

            # 检查是否与已有公司(seen_companies)重复
            for seen in list(seen_companies):
                if self._is_similar_company(company, seen):
                    is_duplicate = True
                    # 【白名单优先】如果已有公司是白名单企业，绝对不替换
                    if seen in whitelist_set:
                        logging.info(f"白名单保护: 保留白名单 '{seen}'，丢弃AI搜索的 '{company}'")
                    # 如果新公司名称更长（更完整），且已有公司不是白名单，则替换
                    elif len(company) > len(seen):
                        to_remove_from_seen.append(seen)
                        to_add_to_seen.append(company)
                        unique_companies.append(company)
                        logging.info(f"去重: 用全称 '{company}' 替换已有简称 '{seen}'")
                    else:
                        logging.info(f"去重: '{company}' 与已有 '{seen}' 重复，保留已有全称")
                    break

            # 检查是否与当前批次中的公司重复
            if not is_duplicate:
                for i, existing in enumerate(unique_companies):
                    if self._is_similar_company(company, existing):
                        is_duplicate = True
                        # 保留更长的名称（更完整的全称）
                        if len(company) > len(existing):
                            unique_companies[i] = company  # 直接替换
                            logging.info(f"去重: 用全称 '{company}' 替换简称 '{existing}'")
                        else:
                            logging.info(f"去重: '{company}' 与 '{existing}' 重复，保留全称 '{existing}'")
                        break

            if not is_duplicate:
                unique_companies.append(company)

        # 更新seen_companies：移除简称，添加全称
        for name in to_remove_from_seen:
            seen_companies.discard(name)
        for name in to_add_to_seen:
            seen_companies.add(name)

        return unique_companies

    def fetch_article_content(self, article_url: str) -> str:
        """获取文章内容"""
        try:
            # 直接使用完整的URL
            headers = {
                'Authorization': f'Bearer {self.jina_api_key}',
                'Accept': 'application/json; charset=utf-8',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(article_url, headers=headers, timeout=30,
                                   proxies={"https": "socks5://127.0.0.1:7891", "http": "socks5://127.0.0.1:7891"})
            response.encoding = 'utf-8'  # 确保响应内容使用UTF-8编码
            
            if response.status_code == 200:
                # 使用BeautifulSoup解析HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 移除script和style标签
                for script in soup(["script", "style"]):
                    script.decompose()
                
                # 获取文本内容
                text = soup.get_text(separator='\n', strip=True)
                
                # 清理文本
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = '\n'.join(chunk for chunk in chunks if chunk)
                
                # 移除空行
                text = '\n'.join(line for line in text.splitlines() if line.strip())
                
                return text
            return ""
        except Exception as e:
            logging.error(f"获取文章内容失败: {str(e)}")
            return ""

    def search_with_jina(self, query: str) -> List[Dict]:
        """使用Jina API搜索相关文章"""
        try:
            # 搜索文章
            search_url = "https://s.jina.ai/"
            headers = {
                'Authorization': f'Bearer {self.jina_api_key}',
                'X-Respond-With': 'no-content',
                'Accept': 'application/json; charset=utf-8'
            }
            params = {
                'q': query
            }
            
            print(f"\n发送请求到URL: {search_url}")
            print(f"查询参数: {params}")
            
            response = requests.get(
                search_url,
                headers=headers,
                params=params,
                proxies={"https": "socks5://127.0.0.1:7891", "http": "socks5://127.0.0.1:7891"},
                timeout=30
            )
            
            if response.status_code == 200:
                # 确保响应内容使用UTF-8编码
                response.encoding = 'utf-8'
                print("\n原始响应内容：")
                print(response.text)
                
                # 解析文本格式的搜索结果
                search_results = []
                current_result = {}
                
                for line in response.text.split('\n'):
                    line = line.strip()
                    if not line:
                        if current_result:
                            search_results.append(current_result)
                            current_result = {}
                        continue
                        
                    if 'URL Source:' in line:
                        current_result['URL Source'] = line.split('URL Source:')[1].strip()
                    elif 'Description:' in line:
                        current_result['Description'] = line.split('Description:')[1].strip()
                    elif 'Date:' in line:
                        current_result['Date'] = line.split('Date:')[1].strip()
                    elif 'Title:' in line:
                        current_result['Title'] = line.split('Title:')[1].strip()
                
                if current_result:
                    search_results.append(current_result)
                
                print("\n解析后的搜索结果：")
                print(json.dumps(search_results, ensure_ascii=False, indent=2))
                
                # 获取每篇文章的内容
                for result in search_results:
                    if 'URL Source' in result:
                        content = self.fetch_article_content(result['URL Source'])
                        result['content'] = content
                return search_results
            else:
                logging.error(f"Jina API调用失败: {response.status_code} - {response.text}")
                return []
                
        except requests.exceptions.RequestException as e:
            logging.error(f"Jina搜索请求错误: {str(e)}")
            return []
        except Exception as e:
            logging.error(f"Jina搜索出错: {str(e)}")
            return []

    def search_with_deepseek(self, industry_chain: str, articles: List[Dict]) -> Dict:
        """使用DeepSeek V3分析文章内容"""
        try:
            # 构建文章内容
            articles_content = []
            for article in articles:
                content = f"文章标题：{article.get('Title', '')}\n"
                content += f"文章摘要：{article.get('Description', '')}\n"
                if 'content' in article:
                    # 使用更长的内容长度，并确保内容有意义
                    article_content = article['content']
                    if len(article_content) > 2000:
                        # 尝试找到合适的分割点
                        sentences = article_content.split('。')
                        content_length = 0
                        selected_sentences = []
                        for sentence in sentences:
                            if content_length + len(sentence) > 2000:
                                break
                            selected_sentences.append(sentence)
                            content_length += len(sentence)
                        article_content = '。'.join(selected_sentences) + '。'
                    content += f"文章内容：{article_content}\n"
                articles_content.append(content)
            
            # 从搜索结果中提取企业名称
            extracted_companies = set()
            for article in articles:
                if 'Description' in article:
                    # 尝试从描述中提取企业名称
                    desc = article['Description']
                    # 常见的分隔符
                    separators = ['、', '，', ',', '；', ';', '|', ' ', '：', ':', '（', '）', '(', ')', '【', '】', '[', ']']
                    for sep in separators:
                        if sep in desc:
                            companies = [c.strip() for c in desc.split(sep) if c.strip()]
                            extracted_companies.update(companies)
            
            # 将提取的企业名称添加到提示中
            companies_context = ""
            if extracted_companies:
                companies_context = "\n\n从搜索结果中提取到的企业名称：\n" + "\n".join(f"- {company}" for company in extracted_companies)
            
            system_prompt = f"""你是一个专业的产业链分析专家。请仔细分析文章内容，并结合你的专业知识，准确识别产业链"{industry_chain}"的头部企业。即使搜索结果有限，也要基于你的知识给出完整的分析并输出头部企业名字全称。

请严格按照以下JSON格式返回，确保所有引号和括号都完整：
{{
  "industry_chain": "{industry_chain}",
  "position": "上游",
  "top_companies": [
    "企业全称1",
    "企业全称2",
    "企业全称3"
  ]
}}

【最重要的规则 - 必须返回完整公司全称】：
- 必须返回公司的完整工商注册名称，包含"有限公司"、"股份有限公司"、"集团"等后缀
- 绝对禁止返回简称，例如：
  - 错误："中际旭创" → 正确："中际旭创股份有限公司"
  - 错误："宁德时代" → 正确："宁德时代新能源科技股份有限公司"
  - 错误："比亚迪" → 正确："比亚迪股份有限公司"
  - 错误："华为" → 正确："华为技术有限公司"
  - 错误："阿里巴巴" → 正确："阿里巴巴集团控股有限公司"
  - 错误："腾讯" → 正确："腾讯科技（深圳）有限公司"
  - 错误："地平线" → 正确："地平线（上海）人工智能技术有限公司"
  - 错误："商汤科技" → 正确："商汤科技开发有限公司"
- 如果不确定公司全称，请查询后再返回，宁可不返回也不要返回简称

注意：
1. 请只返回JSON格式的结果，不要包含其他文字说明
2. 请确保返回的企业名称是真实的完整的企业全称不是简写，每个企业名称都要用双引号包围
3. 请结合搜索结果和你已有的知识，列出产业链上游，中游及下游的头部企业至少各50家
4. 请按照企业在产业链中的重要性排序
5. 请明确指出这些企业属于产业链的哪个环节（上游/中游/下游）
6. 不要包含```json或```等标记，直接返回JSON对象
7. "top_companies"结果中的内容是个列表，不要缺少反中括号("]")
8. 返回的企业名称必须都是不一样的，不要有重复的，例如：
    - 错误示例：["华为技术有限公司", "华为公司", "华为"]  # 这是同一家公司的不同叫法
    - 正确示例：["华为技术有限公司"]  # 只保留最规范的名称
9. 返回的企业一定是真实存在的，不要虚构，不要自己瞎编，比如"深圳市飞虎无人机科技有限公司"就是不存在的公司，不要返回
10. 对于不确定是否真实存在的公司，宁可不要返回，也不要返回可能不存在的公司
11. 优先返回上市公司、知名企业、行业龙头企业等有公开信息可查的企业
12. 如果搜索结果中提到某公司，但你不确定该公司是否真实存在，请先验证后再决定是否返回
13. 对于外国公司，请使用其在中国注册的中文公司名称，例如：
    - "Apple Inc." 应返回为 "苹果电脑贸易（上海）有限公司"
    - "Tesla, Inc." 应返回为 "特斯拉（上海）有限公司"
    - "Siemens AG" 应返回为 "西门子（中国）有限公司"
14. 如果搜索结果中提到某公司，但该公司的名称看起来不完整或不规范，请查找其完整规范的公司名称
15. 如果无法确认某公司的真实存在性，请直接跳过，不要返回
16. 优先返回中国企业，特别是上市公司和行业龙头企业
17. 对于外国企业，请确保使用其在中国注册的官方中文名称，不要使用音译或意译
18. 如果外国企业在中国有多个子公司，请使用其最主要的中国子公司名称
19. 如果搜索结果中同时出现中英文名称，优先使用中文名称
20. 如果搜索结果中只有英文名称，请查找该公司的官方中文名称后再返回
21. 在返回结果前，请仔细检查是否有重复的企业名称，包括：
    - 同一公司的不同简称（如"华为"和"华为技术有限公司"）
    - 同一公司的不同写法（如"阿里巴巴"和"阿里巴巴集团"）
    - 同一公司的不同翻译（如"Microsoft"和"微软公司"）
22. 如果发现重复的企业名称，只保留最规范、最完整的那个名称
23. 请特别注意搜索结果中提到的企业，这些企业很可能是该产业链的重要企业
24. 对于特定领域的企业（如机器人领域的宇树科技等），即使搜索结果中没有明确提到，也要基于你的专业知识将其包含在结果中
25. 请确保返回的企业名称是最新的、准确的，包括：
    - 最新的公司名称（如公司更名后的名称）
    - 完整的公司名称（包含"有限公司"、"股份有限公司"等后缀）
    - 正确的公司名称（不要使用简称或别名）
26. 再次强调：绝对不能返回简称！每个公司名称必须是完整的工商注册名称！
"""

            user_content = f"""请分析以下关于{industry_chain}的文章，并结合你已有的知识，找出该产业链中的头部企业。

文章内容：
{chr(10).join(articles_content)}{companies_context}"""

            client = OpenAI(
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )

            response = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_content}],
                temperature=0.6,
                response_format={
                    "type": "json_object"
                }
            )
            
            try:
                content = response.choices[0].message.content
                print("API返回的原始内容：", content)
                # 清理内容中的markdown标记
                cleaned_content = content.replace("```json", "").replace("```", "").strip()
                result = json.loads(cleaned_content)
                return result
            except json.JSONDecodeError as e:
                logging.error(f"JSON解析错误: {str(e)}")
                logging.error(f"原始内容: {content}")
                return None
                
        except Exception as e:
            logging.error(f"DeepSeek搜索出错: {str(e)}")
            return None

    def save_to_database(self, industry_chain: str, companies: List[str], position: str) -> bool:
        """保存结果到数据库"""
        try:
            conn = pymysql.connect(**self.db_config, cursorclass=DictCursor)
            cursor = conn.cursor()
            
            # 删除旧表
            # drop_table_sql = "DROP TABLE IF EXISTS industry_chain_topcompanies0608;"
            # cursor.execute(drop_table_sql)
            
            # 创建表（如果不存在）
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {TARGET_TABLE} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                industry_chain VARCHAR(100) NOT NULL,
                company_name VARCHAR(200) NOT NULL,
                company_rank INT NOT NULL,
                position VARCHAR(50) NOT NULL COMMENT '企业所属环节：上游/中游/下游',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_company_position (industry_chain, company_name, position),
                INDEX idx_industry_chain (industry_chain)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            cursor.execute(create_table_sql)

            # 插入数据，使用 INSERT IGNORE 避免重复插入
            insert_sql = f"""
            INSERT IGNORE INTO {TARGET_TABLE} (industry_chain, company_name, company_rank, position)
            VALUES (%s, %s, %s, %s)
            """
            
            for rank, company in enumerate(companies, 1):
                cursor.execute(insert_sql, (industry_chain, company, rank, position))
            
            conn.commit()
            cursor.close()
            conn.close()
            return True
            
        except Exception as e:
            logging.error(f"保存到数据库失败: {str(e)}")
            return False

    def analyze_industry_chain(self, industry_chain: str) -> Dict:
        """分析产业链信息"""
        positions = ["上游", "中游", "下游"]
        all_companies = []
        seen_companies = set()  # 用于记录已经出现过的公司名称
        whitelist_set = set()   # 白名单企业集合，具有最高优先级，不可被AI替换

        # 优先从 xlsx 文件读取白名单
        whitelist_from_xlsx = self._load_whitelist_from_xlsx(industry_chain)
        xlsx_loaded = any(len(companies) > 0 for companies in whitelist_from_xlsx.values())

        if xlsx_loaded:
            # 使用 xlsx 白名单
            for position in positions:
                companies = whitelist_from_xlsx[position]
                if companies:
                    for company in companies:
                        whitelist_set.add(company)
                        if company not in seen_companies:
                            seen_companies.add(company)
                            all_companies.append(company)
                        self.save_to_database(industry_chain, [company], position)
                        print(f"已添加 xlsx 白名单企业[{position}]: {company}")
        else:
            # 如果没有 xlsx，回退到 txt 文件读取（按环节分类的文件）
            white_list_loaded = False
            for position in positions:
                white_list_file = f"white_list_top_{industry_chain}_{position}.txt"
                try:
                    if os.path.exists(white_list_file):
                        white_list_loaded = True
                        with open(white_list_file, 'r', encoding='utf-8') as f:
                            white_list_companies = [line.strip() for line in f if line.strip()]
                        print(f"\n从 txt 白名单文件加载了{position}环节 {len(white_list_companies)}家企业")

                        for company in white_list_companies:
                            whitelist_set.add(company)
                            if company not in seen_companies:
                                seen_companies.add(company)
                                all_companies.append(company)
                            self.save_to_database(industry_chain, [company], position)
                            print(f"已添加白名单企业[{position}]: {company}")
                except Exception as e:
                    logging.error(f"读取白名单文件 {white_list_file} 失败: {str(e)}")

            # 如果没有找到分类文件，尝试读取旧版本的单文件格式
            if not white_list_loaded:
                white_list_file = f"white_list_top_{industry_chain}.txt"
                try:
                    if os.path.exists(white_list_file):
                        with open(white_list_file, 'r', encoding='utf-8') as f:
                            white_list_companies = [line.strip() for line in f if line.strip()]
                        print(f"\n从 txt 白名单文件加载了{len(white_list_companies)}家企业（旧格式，默认为中游）")

                        for company in white_list_companies:
                            whitelist_set.add(company)
                            if company not in seen_companies:
                                seen_companies.add(company)
                                all_companies.append(company)
                            self.save_to_database(industry_chain, [company], "中游")
                            print(f"已添加白名单企业[中游]: {company}")
                except Exception as e:
                    logging.error(f"读取白名单文件失败: {str(e)}")

        for position in positions:
            # 定义搜索关键词组合（放到循环内部）
            search_keywords = [
                # f"{industry_chain} {position}环节 头部企业 龙头企业 上市公司 市场份额 行业排名 2024年",
                # f"{industry_chain} {position}环节 重点企业 知名企业 领军企业 2024年",
                # f"{industry_chain} {position}环节 企业排名 企业名单 企业名录 2024年",
                # f"{industry_chain} {position}环节 主要企业 核心企业 重点企业 2024年",
                # f"{industry_chain} 知名企业",
                f"{industry_chain} {position}环节 上市公司",
                f"{industry_chain} {position}环节 龙头企业",
                f"{industry_chain} {position}环节 知名企业"
            ]
            # 使用多个搜索关键词组合
            for search_query in search_keywords:
                print(f"\n正在搜索: {search_query}")
                articles = self.search_with_jina(search_query)
                
                if not articles:
                    logging.error(f"Jina搜索未返回{position}相关结果")
                    continue
                    
                # 使用DeepSeek分析文章内容
                deepseek_result = self.search_with_deepseek(industry_chain, articles)
                
                if not deepseek_result or "top_companies" not in deepseek_result:
                    logging.error(f"DeepSeek分析{position}企业失败")
                    continue
                
                # 智能去重处理（识别相似公司名称，白名单企业不可被替换）
                unique_companies = self._deduplicate_companies(deepseek_result["top_companies"], seen_companies, whitelist_set)
                # 将去重后的公司添加到已见集合
                for company in unique_companies:
                    seen_companies.add(company)
                
                # 保存结果到数据库
                if unique_companies:
                    if self.save_to_database(industry_chain, unique_companies, position):
                        print(f"\n{position}企业结果已保存到数据库")
                        all_companies.extend(unique_companies)
                    else:
                        print(f"\n{position}企业保存到数据库失败")
                
                time.sleep(2)  # 避免API调用过于频繁
            
        if not all_companies:
            return {"error": "未找到任何企业信息"}
            
        return {
            "industry_chain": industry_chain,
            "top_companies": all_companies
        }

def main():
    searcher = IndustryChainSearcher()
    
    # 示例产业链列表
    industry_chains = [
        "氢能产业"
    ]
    
    print("\n=== 开始分析产业链头部企业 ===\n")
    
    for chain in industry_chains:
        print(f"\n正在分析{chain}...")
        
        result = searcher.analyze_industry_chain(chain)
        
        if result and "top_companies" in result:
            print(f"✓ {chain}分析完成并保存到数据库")
        else:
            print(f"✗ {chain}分析失败")
            
        time.sleep(2)  # 避免API调用过于频繁
        
    print("\n分析完成！")

if __name__ == "__main__":
    main() 