#!/usr/bin/env python3
"""
企业简称匹配全名脚本 + DeepSeek智能筛选 + 天眼查补充
输出CSV: 原名称 | 候选列表 | 大模型选定
"""
import pymysql
import csv
import sys
import os
import requests
from typing import List, Dict, Optional
from openai import OpenAI

# 数据库配置
DB_CONFIG = {
    'host': 'rm-2zej668f34v6xr91wdo.mysql.rds.aliyuncs.com',
    'port': 3306,
    'user': 'root',
    'password': os.getenv('DB_PASSWORD_ZS'),
    'database': 'investment_agent',
    'charset': 'utf8mb4'
}

# DeepSeek配置
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', os.getenv('DEEPSEEK_API_KEY'))
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 天眼查配置
TIANYANCHA_TOKEN = os.getenv('TIANYANCHA_TOKEN', os.getenv('TIANYANCHA_TOKEN'))  # 请设置环境变量
TIANYANCHA_API_URL = "https://open.api.tianyancha.com/services/open/search/2.0"


def get_candidates(cursor, company: str, max_matches: int = 20) -> List[str]:
    """从数据库获取候选企业名称"""
    # 前缀匹配
    cursor.execute(
        "SELECT entity_name FROM entity_name_data WHERE entity_name LIKE %s LIMIT %s",
        (f"{company}%", max_matches)
    )
    matches = [row[0] for row in cursor.fetchall()]

    # 补充包含匹配
    if len(matches) < max_matches:
        cursor.execute(
            "SELECT entity_name FROM entity_name_data WHERE entity_name LIKE %s LIMIT %s",
            (f"%{company}%", max_matches)
        )
        for row in cursor.fetchall():
            if row[0] not in matches:
                matches.append(row[0])

    return matches


def search_tianyancha(company: str) -> Optional[str]:
    """
    使用天眼查API搜索企业
    返回第一个匹配的企业名称
    """
    if not TIANYANCHA_TOKEN:
        print(f"    ⚠️ 未配置天眼查Token，跳过API查询")
        return None

    try:
        params = {
            "word": company,
            "pageSize": 1  # 只取第一个
        }
        headers = {
            "Authorization": TIANYANCHA_TOKEN
        }

        print(f"    → 调用天眼查API...", end=" ")
        sys.stdout.flush()

        response = requests.get(TIANYANCHA_API_URL, params=params, headers=headers, timeout=10)
        data = response.json()

        if data.get("error_code") == 0 and data.get("result", {}).get("items"):
            first_item = data["result"]["items"][0]
            company_name = first_item.get("name")
            print(f"找到: {company_name}")
            return company_name
        else:
            print(f"未找到")
            return None

    except Exception as e:
        print(f"API调用失败: {e}")
        return None


def select_with_llm(company: str, candidates: List[str]) -> Optional[str]:
    """用DeepSeek从候选列表中选择最合适的总公司"""
    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL
    )

    # 构建提示词
    candidate_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(candidates)])

    prompt = f"""你是一个企业名称匹配专家。给定一个企业简称和若干候选全名，请选出最合适的总公司名称。

**企业简称**: {company}

**候选全名**:
{candidate_list}

**选择规则**:
1. 优先选择"集团有限公司"、"股份有限公司"等带有集团/股份标识的
2. 避免选择分公司（带有"分公司"、"办事处"等）
3. 避免选择地域子公司（如"北京XX"、"上海XX"等，除非是总部）
4. 选择名称最简洁、最核心的主体公司

请直接输出选中的企业全名，不要输出其他内容。如果所有候选都不合适，输出"无合适选项"。

选中的名称:"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个企业名称匹配专家，擅长从多个候选中选出总公司。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=100
        )

        result = response.choices[0].message.content.strip()

        if result == "无合适选项" or result not in candidates:
            # 如果大模型选的不在候选里，返回第一个
            return candidates[0]

        return result

    except Exception as e:
        print(f"    ⚠️ LLM调用失败: {e}，使用默认选择")
        # 降级策略：优先选择带"集团"、"股份"的
        for name in candidates:
            if "集团" in name or "股份" in name:
                return name
        return candidates[0]


def match_companies(company_list: List[str], use_llm: bool = True, use_tianyancha: bool = True) -> List[Dict]:
    """
    匹配企业简称到全名

    Args:
        company_list: 企业简称列表
        use_llm: 是否使用大模型筛选
        use_tianyancha: 是否使用天眼查补充

    Returns:
        [{"original": 原名称, "candidates": [候选列表], "selected": 选定名称, "source": 数据来源}]
    """
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    results = []
    total = len(company_list)
    tianyancha_count = 0

    for idx, company in enumerate(company_list, 1):
        company = company.strip()
        if not company:
            continue

        # 进度日志
        print(f"[{idx}/{total}] 正在匹配: {company}...", end=" ")
        sys.stdout.flush()

        # 1. 先从数据库获取候选
        candidates = get_candidates(cursor, company, max_matches=20)

        source = "数据库"
        tianyancha_result = None

        # 2. 如果数据库没有，尝试天眼查
        if not candidates and use_tianyancha:
            tianyancha_result = search_tianyancha(company)
            if tianyancha_result:
                candidates = [tianyancha_result]
                source = "天眼查"
                tianyancha_count += 1

        print(f"找到 {len(candidates)} 条候选 ({source})", end="")

        # 3. 用LLM筛选
        selected = None
        if use_llm and candidates:
            # 天眼查只有一个结果，不需要LLM
            if len(candidates) == 1 and source == "天眼查":
                selected = candidates[0]
                print(f" → 直接采用: {selected[:30]}..." if len(selected) > 30 else f" → 直接采用: {selected}")
            else:
                print(" → LLM筛选中...", end=" ")
                sys.stdout.flush()
                selected = select_with_llm(company, candidates)
                print(f"选定: {selected[:30]}..." if selected and len(selected) > 30 else f"选定: {selected}")

        results.append({
            "original": company,
            "candidates": candidates,
            "selected": selected or (candidates[0] if candidates else None),
            "source": source
        })

    cursor.close()
    conn.close()

    print(f"\n统计: 天眼查补充 {tianyancha_count} 条")
    return results


def save_to_csv(results: List[Dict], output_file: str):
    """保存结果到CSV"""
    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['原企业名称', '候选列表', '大模型选定', '数据来源'])

        for item in results:
            # 候选列表用分号分隔
            candidates_str = '; '.join(item['candidates']) if item['candidates'] else ''
            writer.writerow([
                item['original'],
                candidates_str,
                item['selected'] or '',
                item['source']
            ])

    print(f"✓ 结果已保存到: {output_file}")


def main():
    # 测试数据
    test_companies = [
        "药明康德", "康龙化成", "凯莱英", "义翘神州", "恒瑞医药",
        "迈瑞医疗", "百济神州", "信达生物", "君实生物", "万泰生物",
        "荣昌生物", "中国生物制药", "罗氏", "礼来", "默沙东",
        "阿斯利康", "诺和诺德", "国药控股", "华润医药", "上海医药"
    ]

    print("=" * 100)
    print("企业简称匹配 + DeepSeek智能筛选 + 天眼查补充")
    print("=" * 100)

    # 检查配置
    use_llm = True
    use_tianyancha = bool(TIANYANCHA_TOKEN)

    if DEEPSEEK_API_KEY == 'your-api-key-here':
        print("\n⚠️ DeepSeek API Key未配置，将不使用LLM筛选")
        use_llm = False
    else:
        print(f"✓ DeepSeek API已配置")

    if use_tianyancha:
        print(f"✓ 天眼查API已配置")
    else:
        print(f"⚠️ 天眼查Token未设置（如需使用请设置: export TIANYANCHA_TOKEN=your-token）")

    print()

    # 匹配
    results = match_companies(test_companies, use_llm=use_llm, use_tianyancha=use_tianyancha)

    # 输出汇总
    print("\n" + "=" * 100)
    print(f"{'原名称':<15} {'候选数':<8} {'数据来源':<10} {'大模型选定'}")
    print("=" * 100)

    for item in results:
        selected = item['selected'] or '[未匹配]'
        if len(selected) > 40:
            selected = selected[:40] + "..."
        print(f"{item['original']:<15} {len(item['candidates']):<8} {item['source']:<10} {selected}")

    print("=" * 100)

    # 保存CSV
    output_file = "/root/mix_project/scripts/company_match_results.csv"
    save_to_csv(results, output_file)

    # 打印详细结果
    print("\n详细结果：")
    print("-" * 100)
    for item in results:
        print(f"\n【{item['original']}】[{item['source']}]")
        if item['candidates']:
            print(f"  候选 ({len(item['candidates'])}条):")
            for i, c in enumerate(item['candidates'][:5], 1):
                marker = " ← 选中" if c == item['selected'] else ""
                print(f"    {i}. {c}{marker}")
            if len(item['candidates']) > 5:
                print(f"    ... 还有 {len(item['candidates']) - 5} 条")
        else:
            print("  [无候选]")


if __name__ == "__main__":
    main()
