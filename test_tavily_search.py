"""
产业链搜索引擎替换测试脚本
使用 Tavily 替换 Jina 搜索，完全复刻项目现有的搜索流程和输出格式
不修改项目现有代码，独立运行测试

用法:
    pip install tavily-python openai pyyaml
    python test_tavily_search.py
"""

import os
import sys
import yaml
import json
import asyncio
from datetime import datetime
from urllib.parse import unquote

# ===================== 配置区 =====================

# Tavily API Key
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "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")

# 阿里云百炼配置（项目实际用的 AI 调用，和 industry_service.py 一致）
ALI_API_KEY = os.environ.get("ALI_API_KEY", os.getenv("DASHSCOPE_API_KEY"))
ALI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
ALI_MODEL = "deepseek-r1"

# DeepSeek 官方配置（备用）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY"))
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"


# ===================== 加载项目提示词（和 industry_service.py 第233-244行一致）=====================

def load_prompts():
    """从项目 config/settings_show.yaml 加载提示词"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'settings_show.yaml')
    with open(config_path, "r", encoding="utf-8") as f:
        settings = yaml.load(f, Loader=yaml.FullLoader)
    return {
        'input_clean': settings['prompts']['input_clean']['content'],
        'get_entity': settings['prompts']['get_entity']['content'],
        'clean_info': settings['prompts']['clean_info']['content'],
        'clean_node_info': settings['prompts']['clean_node_info']['content'],
        'words_from_ocr': settings['prompts']['words_from_ocr']['content'],
        'get_triples': settings['prompts']['get_triples']['content'],
        'check_triples': settings['prompts']['check_triples']['content'],
        'modify_triples': settings['prompts']['modify_triples']['content'],
    }


# ===================== Tavily 搜索引擎（替代 JinaSearcher）=====================

class TavilyIndustrySearcher:
    """
    使用 Tavily 搜索，完全模拟项目现有 JinaSearcher 的行为：

    JinaSearcher 的两个核心方法:
    1. search(query) -> {'results': [{'title', 'url', 'content'}]}
    2. search_with_site(query, site_constraint) -> {'results': [{'title', 'url', 'content'}]}
    3. get_page_content(url) -> str (完整网页内容)

    Tavily 的 include_raw_content=True 等价于 Jina Reader，
    搜索结果直接带完整内容，不需要再单独调用 Reader API
    """

    def __init__(self, api_key=None):
        self.api_key = api_key or TAVILY_API_KEY

    def search(self, query, max_results=10):
        """
        通用搜索，模拟 JinaSearcher.search(query)
        返回格式和项目一致: {'results': [{'title', 'url', 'content', 'full_content'}]}
        """
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=self.api_key)
            tavily_results = client.search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                include_raw_content=True,
            )
            return self._normalize_results(tavily_results)
        except ImportError:
            print("请先安装: pip install tavily-python")
            return None
        except Exception as e:
            print(f"Tavily 搜索失败: {e}")
            return None

    def search_with_site(self, query, site_constraint):
        """
        站点限定搜索，模拟 JinaSearcher.search_with_site(query, site_constraint)
        site_constraint 格式: "site:askci.com"
        Tavily 不支持 site: 语法，改用 include_domains 参数
        """
        # 从 "site:xxx.com" 提取域名
        if "site:" in site_constraint:
            domain = site_constraint.replace("site:", "").strip()
        else:
            domain = site_constraint

        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=self.api_key)
            tavily_results = client.search(
                query=query,
                max_results=10,
                search_depth="advanced",
                include_raw_content=True,
                include_domains=[domain],
            )
            return self._normalize_results(tavily_results)
        except ImportError:
            print("请先安装: pip install tavily-python")
            return None
        except Exception as e:
            print(f"Tavily 站点搜索失败 ({domain}): {e}")
            return None

    def _normalize_results(self, tavily_results):
        """
        将 Tavily 结果转换为项目 JinaSearcher 统一格式:
        {'results': [{'title': ..., 'url': ..., 'content': ..., 'full_content': ...}]}
        """
        if not tavily_results or not tavily_results.get('results'):
            return None

        normalized = []
        for r in tavily_results['results']:
            normalized.append({
                'title': unquote(r.get('title', '未知标题')),
                'url': r.get('url', ''),
                'content': r.get('content', ''),          # 摘要
                'full_content': r.get('raw_content', ''),  # 完整内容（等价于 Jina Reader 结果）
            })

        return {'results': normalized}


# ===================== 搜索流程（完全复刻 tool_search）=====================

def tool_search_sync(industry_name, isNode=False, node="", sites=None):
    """
    同步版本的 tool_search，完全复刻 industry_service.py 第569-902行的逻辑

    流程:
    1. 构造搜索词（和项目一致）
    2. 优先按指定站点搜索（中商情报网、前瞻网等）
    3. 站点搜索失败 → 通用搜索
    4. 通用搜索失败 → 备用搜索词
    5. 备用失败 → 扩展搜索词
    6. 全部失败 → 全网合并搜索
    7. 获取搜索结果的完整网页内容（等价于 Jina Reader）
    8. 拼接 final_content 字符串（格式和项目一模一样）

    返回: (final_content, collected_articles)
        final_content: "来源: xxx\n内容: xxx\n\n来源: yyy\n内容: yyy\n"
        collected_articles: [{'title', 'url', 'content'}]
    """
    print(f"\n{'='*60}")
    print(f"开始搜索: industry_name={industry_name}, isNode={isNode}, node={node}")
    print(f"{'='*60}")

    searcher = TavilyIndustrySearcher()

    # ---- 第1步：构造搜索关键词（和 industry_service.py 第579-584行一致）----
    if isNode and node:
        search_keyword = f"{industry_name} {node}"
        print(f"[搜索模式] 节点搜索: '{search_keyword}'")
    else:
        search_keyword = industry_name
        print(f"[搜索模式] 整体产业链搜索: '{search_keyword}'")

    search_success = False
    raw_content = None

    # ---- 第2步：按站点搜索或默认搜索策略 ----
    if sites and len(sites) > 0:
        # 指定站点搜索（和 industry_service.py 第592-654行一致）
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

        for site in sites:
            print(f"\n[站点搜索] 使用 {site} 搜索: {search_keyword}")
            search_term = f"{search_keyword} 产业链"  # 和项目第603行一致

            try:
                if site in site_mapping:
                    raw_content = searcher.search_with_site(search_term, site_mapping[site])
                    if raw_content and raw_content.get('results'):
                        print(f"  -> {site} 找到 {len(raw_content['results'])} 个结果")
                        search_success = True
                        break
                    else:
                        print(f"  -> {site} 无结果")
                elif site == "通用搜索":
                    raw_content = searcher.search(search_term)
                    if raw_content and raw_content.get('results'):
                        search_success = True
                        break
                else:
                    print(f"  -> 未知站点 '{site}'，尝试通用搜索")
                    raw_content = searcher.search(search_term)
                    if raw_content and raw_content.get('results'):
                        search_success = True
                        break
            except Exception as e:
                print(f"  -> {site} 搜索异常: {e}")
    else:
        # 默认搜索策略（和 industry_service.py 第655-749行一致）
        print(f"\n[默认策略] Jina搜索: {search_keyword}")

        # 策略1：直接搜索
        try:
            raw_content = searcher.search(search_keyword)
            if raw_content and raw_content.get('results'):
                search_success = True
            else:
                print("  -> 直接搜索无结果，尝试备用搜索策略...")

                # 策略2：备用搜索词
                search_terms = [
                    f"{search_keyword}产业链",
                    f"{search_keyword}行业分析",
                    f"{search_keyword}市场研究",
                ]
                for term in search_terms:
                    print(f"  -> 尝试备用词: {term}")
                    raw_content = searcher.search(term)
                    if raw_content and raw_content.get('results'):
                        search_success = True
                        break
        except Exception as e:
            print(f"  -> 搜索异常: {e}")

        # 策略3：通用搜索
        if not search_success:
            try:
                print(f"  -> 尝试通用搜索: {search_keyword}")
                raw_content = searcher.search(f"{search_keyword} 产业链分析")
                if raw_content and raw_content.get('results'):
                    search_success = True
            except Exception as e:
                print(f"  -> 通用搜索异常: {e}")

        # 策略4：扩展搜索词
        if not search_success:
            print("  -> 尝试扩展搜索关键词...")
            extended_search_terms = [
                f"{search_keyword} 产业",
                f"{search_keyword} 行业",
                f"{search_keyword} 发展前景",
                f"{search_keyword} 市场规模",
            ]
            for term in extended_search_terms:
                print(f"  -> 尝试扩展词: {term}")
                try:
                    raw_content = searcher.search(term)
                    if raw_content and raw_content.get('results'):
                        search_success = True
                        print(f"  -> 扩展搜索成功: {term}")
                        break
                except Exception as e:
                    print(f"  -> 扩展词 '{term}' 失败: {e}")

        # 策略5：全网合并搜索
        if not search_success:
            print("  -> 尝试全网搜索...")
            try:
                raw_content = searcher.search(f"{search_keyword} 产业链 行业分析 发展前景 市场规模")
                if raw_content and raw_content.get('results'):
                    search_success = True
                    print("  -> 全网搜索成功")
            except Exception as e:
                print(f"  -> 全网搜索异常: {e}")

        # 全部失败
        if not search_success:
            print(f"\n[失败] 所有搜索策略都失败了，关键词: {search_keyword}")
            return '无内容', []

    # ---- 第3步：处理搜索结果（和 industry_service.py 第751-896行一致）----
    if not raw_content:
        print("[失败] 无搜索结果")
        return '无内容', []

    # 提取 URL 列表和标题映射
    urls = []
    titles = {}
    url_blacklist = ['.zip', '.rar', '.mp4', '.mp3', '.exe', '.dmg', '.pkg', '.bin', '.iso']

    def is_crawlable_url(url):
        url_lower = url.lower()
        for ext in url_blacklist:
            if url_lower.endswith(ext):
                return False
        return True

    if isinstance(raw_content, dict):
        urls = [r['url'] for r in raw_content.get('results', []) if 'url' in r and is_crawlable_url(r['url'])]
        titles = {r['url']: r.get('title') for r in raw_content.get('results', []) if 'url' in r and is_crawlable_url(r['url'])}
    elif isinstance(raw_content, list):
        urls = [r['url'] for r in raw_content if 'url' in r and is_crawlable_url(r['url'])]
        titles = {r['url']: r.get('title') for r in raw_content if 'url' in r and is_crawlable_url(r['url'])}

    print(f"\n[结果处理] 提取到 {len(urls)} 个有效 URL")

    if not urls:
        print("[失败] 没有可用的 URL")
        return '无内容', []

    # ---- 第4步：获取完整内容（等价于 Jina Reader）----
    # Tavily 的 raw_content 已经带了完整网页内容，不需要再单独请求
    # 但格式要和项目一致：content 截断到 8000 字符

    # URL 数量限制（和 industry_service.py 第840-846行一致）
    if isNode:
        if node:
            max_urls = 5
        else:
            max_urls = 3
    else:
        max_urls = 10

    results = []
    collected_articles = []

    # 内容验证函数（和 industry_service.py 第789-799行一致）
    def is_valid_content(text):
        if not text or len(text.strip()) < 100:
            return False
        meaningful_keywords = ['产业', '行业', '市场', '发展', '分析', '研究', '报告']
        return any(kw in text for kw in meaningful_keywords)

    # 构建完整内容的结果列表
    # Tavily 已经返回了 raw_content，不需要像 Jina 那样再调 Reader API
    # 但要模拟同样的截断和验证逻辑
    raw_results_map = {}
    if isinstance(raw_content, dict):
        for r in raw_content.get('results', []):
            raw_results_map[r['url']] = r

    for url in urls[:max_urls]:
        r = raw_results_map.get(url, {})
        title = unquote(titles.get(url, r.get('title', '未知标题')))

        # Tavily 的 raw_content 等价于 Jina Reader 返回的完整内容
        full_text = r.get('full_content', '') or r.get('content', '')

        if not full_text or len(full_text.strip()) < 100:
            print(f"  [跳过] 内容太短: {title[:30]}... ({len(full_text) if full_text else 0} 字符)")
            continue

        # 截断到 8000 字符（和 industry_service.py 第826行一致）
        content = full_text[:8000]

        results.append({
            'url': url,
            'title': title,
            'content': content,
            'status': 'success',
        })
        collected_articles.append({
            'title': title,
            'url': url,
            'content': content[:1000],
        })
        print(f"  [成功] {title[:40]}... ({len(content)} 字符)")

    if not results:
        print(f"[失败] 未能获取到有效内容: {industry_name}")
        return '无内容', []

    # ---- 第5步：合并内容（和 industry_service.py 第887-893行一致）----
    combined_content = []
    for result in results:
        content = result.get('content', '')
        if content:
            combined_content.append(f"来源: {result.get('title', '未知')}\n内容: {content}\n")

    final_content = '\n'.join(combined_content)

    print(f"\n[完成] 搜索完成，获取到 {len(results)} 个有效结果，总内容 {len(final_content)} 字符")
    return final_content, collected_articles


# ===================== AI 处理（完全复刻 industry_service.py 的 AI 调用）=====================

class IndustryAIProcessor:
    """
    复刻项目 industry_service.py 中的 AI 调用方式:
    - 使用阿里云百炼 + deepseek-r1
    - 消息格式和项目一致
    - 提示词从 config/settings_show.yaml 读取
    """

    def __init__(self):
        self.prompts = load_prompts()

    def _call_api(self, messages, temperature=0.6, json_format=False):
        """调用 AI API（和 industry_service.py 第415-425行一致）"""
        from openai import OpenAI

        client = OpenAI(
            api_key=ALI_API_KEY,
            base_url=ALI_BASE_URL,
        )
        kwargs = {
            'model': ALI_MODEL,
            'messages': messages,
            'temperature': temperature,
        }
        if json_format:
            kwargs['response_format'] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)

        # 尝试获取思维链内容（deepseek-r1 特有）
        reasoning = ""
        try:
            reasoning = response.choices[0].message.reasoning_content or ""
        except:
            pass

        content = response.choices[0].message.content
        return content, reasoning

    def extract_entities(self, industry_name, search_content):
        """
        从搜索结果提取产业链节点
        对应 industry_service.py 的 process_industry_data + get_entity_prompts
        (industry_service.py 第994-1000行)
        """
        system_prompt = self.prompts['get_entity'].replace("{industry}", industry_name)

        messages = [
            {"role": "system", "content": "你是一个产业链分析专家。请根据用户提供的信息，按照指定的格式进行分析。请以json格式返回结果。"},
            {"role": "user", "content": f"{system_prompt}\n\n{search_content}"}
        ]

        return self._call_api(messages)

    def clean_info(self, industry_name, search_content):
        """
        清洗整合搜索结果
        对应 industry_service.py 的 process_industry_data + clean_info_prompts
        (industry_service.py 第383-400行)
        """
        system_prompt = self.prompts['clean_info'].replace("{industry}", industry_name)

        messages = [
            {"role": "system", "content": "你是一个产业链分析专家。请根据用户提供的信息，按照指定的格式进行分析。请以json格式返回结果。"},
            {"role": "user", "content": f"{system_prompt}\n\n{search_content}"}
        ]

        return self._call_api(messages)

    def clean_node_info(self, industry_name, node_name, search_content):
        """
        清洗节点搜索结果
        对应 clean_node_info_prompts
        """
        system_prompt = (
            self.prompts['clean_node_info']
            .replace("{industry}", industry_name)
            .replace("{node}", node_name)
        )

        messages = [
            {"role": "system", "content": "你是一个产业链分析专家。请根据用户提供的信息，按照指定的格式进行分析。请以json格式返回结果。"},
            {"role": "user", "content": f"{system_prompt}\n\n{search_content}"}
        ]

        return self._call_api(messages)

    def get_triples(self, industry_name, all_content, white_list=""):
        """
        从所有资料中提取节点和三元组
        对应 get_triples_prompts
        """
        system_prompt = (
            self.prompts['get_triples']
            .replace("{industry}", industry_name)
            .replace("{white_list}", white_list)
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": all_content}
        ]

        return self._call_api(messages, json_format=True)


# ===================== 完整流程测试（复刻 tool_total_search）=====================

def _save_results(industry_name, step_name, data, output_dir):
    """保存结果到文件"""
    import os
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M%S")
    filepath = os.path.join(output_dir, f"{step_name}.txt")

    with open(filepath, "w", encoding="utf-8") as f:
        if isinstance(data, dict):
            json.dump(data, f, ensure_ascii=False, indent=2)
        elif isinstance(data, list):
            for item in data:
                f.write(str(item) + "\n")
        else:
            f.write(str(data))

    print(f"  [已保存] {filepath}")
    return filepath


def run_full_pipeline(industry_name, sites=None):
    """
    完整复刻 industry_service.py 的 tool_total_search 流程:

    任务一：搜索产业链信息（tool_search）
    任务二：AI 提取节点（get_entity_prompts）
    任务三：搜索每个节点的信息（tool_search for each node）
    每一步结果保存到 test_output/{industry_name}/ 目录
    """
    # 输出目录
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_output', industry_name)
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n结果保存目录: {output_dir}")

    print(f"\n{'#'*60}")
    print(f"# 完整产业链搜索流程测试: {industry_name}")
    print(f"{'#'*60}")

    processor = IndustryAIProcessor()

    # 记录完整运行日志
    full_log = []

    # ==================== 任务一：搜索产业链信息 ====================
    print(f"\n{'='*60}")
    print("任务一：搜索产业链信息")
    print(f"{'='*60}")

    center_node_info, center_articles = tool_search_sync(
        industry_name,
        sites=sites,
    )

    # 保存任务一结果
    task1_result = {
        "industry": industry_name,
        "content_length": len(center_node_info),
        "articles_count": len(center_articles),
        "articles": center_articles,
    }
    _save_results(industry_name, "任务1_搜索结果_summary", task1_result, output_dir)
    _save_results(industry_name, "任务1_搜索结果_完整内容", center_node_info, output_dir)

    full_log.append({
        "step": "任务一：搜索产业链信息",
        "status": "成功" if center_node_info != '无内容' else "失败",
        "content_length": len(center_node_info),
        "articles_count": len(center_articles),
    })

    if center_node_info == '无内容':
        print("\n[流程终止] 搜索失败，无法继续后续任务")
        _save_results(industry_name, "运行日志", full_log, output_dir)
        return

    print(f"\n[任务一完成] 获取内容 {len(center_node_info)} 字符, {len(center_articles)} 篇文章")

    # ==================== 任务二：AI 提取节点 ====================
    print(f"\n{'='*60}")
    print("任务二：AI 提取产业链节点")
    print(f"{'='*60}")

    ai_content, ai_reasoning = processor.extract_entities(industry_name, center_node_info)

    # 保存任务二结果
    task2_result = {
        "industry": industry_name,
        "prompt_used": "get_entity",
        "ai_raw_response": ai_content,
        "reasoning": ai_reasoning[:2000] if ai_reasoning else "",
    }
    _save_results(industry_name, "任务2_AI提取节点_原始返回", task2_result, output_dir)

    if ai_reasoning:
        print(f"\n[思维链]:\n{ai_reasoning[:500]}...")
    print(f"\n[AI 返回的节点]:\n{ai_content}")

    # 解析节点 JSON（和 industry_service.py 第1044-1076行一致）
    parsed_nodes = None
    try:
        cleaned = ai_content.replace("```", "").replace("json", "").strip()
        parsed_nodes = json.loads(cleaned)

        if isinstance(parsed_nodes, dict):
            if 'nodes' in parsed_nodes:
                parsed_nodes = parsed_nodes['nodes']
            elif 'node' in parsed_nodes:
                parsed_nodes = parsed_nodes['node']
            else:
                for v in parsed_nodes.values():
                    if isinstance(v, list):
                        parsed_nodes = v
                        break

        if not isinstance(parsed_nodes, list):
            parsed_nodes = []

        print(f"\n[解析成功] 节点数量: {len(parsed_nodes)}")
        print(f"[节点列表]: {parsed_nodes}")

        _save_results(industry_name, "任务2_解析后的节点列表", parsed_nodes, output_dir)
    except json.JSONDecodeError as e:
        print(f"\n[解析失败] JSON 解析错误: {e}")
        print("跳过任务三")
        full_log.append({
            "step": "任务二：AI 提取节点",
            "status": "解析失败",
            "error": str(e),
            "ai_raw_response": ai_content,
        })
        _save_results(industry_name, "运行日志", full_log, output_dir)
        return

    full_log.append({
        "step": "任务二：AI 提取节点",
        "status": "成功",
        "nodes_count": len(parsed_nodes),
        "nodes": parsed_nodes,
    })

    # ==================== 任务三：搜索每个节点信息 ====================
    print(f"\n{'='*60}")
    print(f"任务三：搜索 {len(parsed_nodes)} 个节点的详细信息")
    print(f"{'='*60}")

    all_node_info = [f"以下是{industry_name}产业链的中心节点信息:\n{center_node_info}\n"]
    node_search_results = []

    for i, node in enumerate(parsed_nodes):
        node_str = str(node)
        print(f"\n--- 节点 {i+1}/{len(parsed_nodes)}: {node_str} ---")

        # 搜索节点信息（和 industry_service.py 第1201行 tool_search 一致）
        node_content, node_articles = tool_search_sync(
            industry_name,
            isNode=True,
            node=node_str,
        )

        node_result = {
            "node": node_str,
            "status": "成功" if node_content != '无内容' else "无内容",
            "content_length": len(node_content) if node_content else 0,
            "articles": node_articles,
        }
        node_search_results.append(node_result)

        if node_content and node_content != '无内容':
            all_node_info.append(f"以下是{industry_name}产业链中{node_str}节点的信息:\n{node_content}\n")
            print(f"  [完成] 节点 '{node_str}' 获取到 {len(node_content)} 字符")
        else:
            print(f"  [跳过] 节点 '{node_str}' 无有效内容")

    # 保存任务三结果
    _save_results(industry_name, "任务3_节点搜索_各节点汇总", node_search_results, output_dir)

    # 保存全部节点资料（这个就是最终传给 get_triples 的内容）
    all_node_content = "\n".join(all_node_info)
    _save_results(industry_name, "任务3_全部节点资料_最终内容", all_node_content, output_dir)

    full_log.append({
        "step": "任务三：搜索节点信息",
        "status": "完成",
        "total_nodes": len(parsed_nodes),
        "successful_nodes": sum(1 for r in node_search_results if r['status'] == '成功'),
        "total_content_length": len(all_node_content),
    })

    # ==================== 保存运行日志 ====================
    print(f"\n{'='*60}")
    print(f"全部流程完成")
    print(f"  - 任务一：{len(center_node_info)} 字符中心内容, {len(center_articles)} 篇文章")
    print(f"  - 任务二：{len(parsed_nodes)} 个节点")
    print(f"  - 任务三：{len(all_node_info)} 份节点资料, 总计 {len(all_node_content)} 字符")
    print(f"  - 结果已保存到: {output_dir}")
    print(f"{'='*60}")

    _save_results(industry_name, "运行日志", full_log, output_dir)

    return all_node_info


# ===================== 测试入口 =====================

def test_search_only():
    """只测试搜索，不调用 AI"""
    industry = input("请输入产业链名称（直接回车用默认值）: ").strip() or "新能源汽车"
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_output', industry)
    os.makedirs(output_dir, exist_ok=True)

    print("\n--- 1. 整体产业链搜索 ---")
    content, articles = tool_search_sync(industry)
    print(f"\n返回格式: ({type(content).__name__}, {type(articles).__name__})")
    print(f"内容长度: {len(content)}")
    print(f"文章数: {len(articles)}")
    if articles:
        print(f"文章标题: {[a['title'][:30] for a in articles]}")

    _save_results(industry, "单独测试_整体搜索内容", content, output_dir)
    _save_results(industry, "单独测试_整体搜索文章", articles, output_dir)

    print("\n--- 2. 节点搜索 ---")
    content2, articles2 = tool_search_sync(industry, isNode=True, node="电池")
    print(f"\n内容长度: {len(content2)}")
    print(f"文章数: {len(articles2)}")

    _save_results(industry, "单独测试_节点搜索内容_电池", content2, output_dir)
    _save_results(industry, "单独测试_节点搜索文章_电池", articles2, output_dir)


def test_search_with_sites():
    """测试指定站点搜索"""
    industry = input("请输入产业链名称（直接回车用默认值）: ").strip() or "新能源汽车"
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_output', industry)
    os.makedirs(output_dir, exist_ok=True)

    print("\n--- 1. 中商情报网搜索 ---")
    content, articles = tool_search_sync(industry, sites=["中商情报网"])
    print(f"\n内容长度: {len(content)}")
    if articles:
        print(f"文章: {[a['title'][:40] for a in articles]}")

    _save_results(industry, "站点搜索_中商情报网_内容", content, output_dir)
    _save_results(industry, "站点搜索_中商情报网_文章", articles, output_dir)

    print("\n--- 2. 前瞻网搜索 ---")
    content2, articles2 = tool_search_sync(industry, sites=["前瞻网"])
    print(f"\n内容长度: {len(content2)}")
    if articles2:
        print(f"文章: {[a['title'][:40] for a in articles2]}")

    _save_results(industry, "站点搜索_前瞻网_内容", content2, output_dir)
    _save_results(industry, "站点搜索_前瞻网_文章", articles2, output_dir)


def test_ai_only():
    """只用 AI 处理已有内容（不搜索）"""
    industry = input("请输入产业链名称（直接回车用默认值）: ").strip() or "新能源汽车"
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_output', industry)
    os.makedirs(output_dir, exist_ok=True)

    # 先搜索
    content, _ = tool_search_sync(industry)
    if content == '无内容':
        print("搜索失败")
        return

    processor = IndustryAIProcessor()

    print("\n--- AI 提取节点 ---")
    result, reasoning = processor.extract_entities(industry, content)
    if reasoning:
        print(f"[思维链]: {reasoning[:300]}...")
    print(f"[结果]: {result}")

    _save_results(industry, "AI测试_搜索内容", content, output_dir)
    _save_results(industry, "AI测试_提取节点结果", {"result": result, "reasoning": reasoning or ""}, output_dir)


def test_full_pipeline():
    """完整流程测试"""
    industry = input("请输入产业链名称（直接回车用默认值）: ").strip() or "新能源汽车"
    run_full_pipeline(industry)


def test_compare_jina_vs_tavily():
    """对比 Jina 和 Tavily 的搜索结果（需要 Jina 密钥有效）"""
    industry = input("请输入产业链名称（直接回车用默认值）: ").strip() or "新能源汽车"

    print(f"\n{'='*60}")
    print("Tavily 搜索结果")
    print(f"{'='*60}")
    tavily_content, tavily_articles = tool_search_sync(industry)
    print(f"Tavily: {len(tavily_content)} 字符, {len(tavily_articles)} 篇文章")

    # 如果想对比 Jina，取消下面的注释
    # print(f"\n{'='*60}")
    # print("Jina 搜索结果")
    # print(f"{'='*60}")
    # from services.jina_search_service import JinaSearcher
    # searcher = JinaSearcher()
    # ... (需要异步调用)


def main():
    print("=" * 60)
    print("  产业链搜索引擎测试（Tavily 替代 Jina）")
    print("  搜索流程和输出格式与项目完全一致")
    print("=" * 60)
    print("\n请选择测试模式:")
    print("  1. 只测试搜索（整体 + 节点，不调 AI）")
    print("  2. 测试指定站点搜索（中商情报网/前瞻网）")
    print("  3. 只测试 AI 处理（搜索 + AI 提取节点）")
    print("  4. 完整流程（搜索 → 提取节点 → 节点��索）")
    print("  5. 对比 Jina vs Tavily")
    print("  0. 退出")

    choice = input("\n请输入选项 (0-5): ").strip()

    if choice == "1":
        test_search_only()
    elif choice == "2":
        test_search_with_sites()
    elif choice == "3":
        test_ai_only()
    elif choice == "4":
        test_full_pipeline()
    elif choice == "5":
        test_compare_jina_vs_tavily()
    elif choice == "0":
        print("退出")
    else:
        print("无效选项")


if __name__ == "__main__":
    main()
