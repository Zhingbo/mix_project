#!/usr/bin/env python3
"""
天眼查API使用示例
"""
import os
import requests


# 配置
TIANYANCHA_TOKEN = os.getenv("TIANYANCHA_TOKEN")
TIANYANCHA_API_URL = "https://open.api.tianyancha.com/services/open/search/2.0"


def search_company(keyword: str, page_size: int = 1) -> dict:
    """
    搜索企业信息

    Args:
        keyword: 搜索关键词（公司名/法人等）
        page_size: 返回结果数量，默认1

    Returns:
        API返回的JSON数据
    """
    params = {
        "word": keyword,
        "pageSize": page_size
    }
    headers = {
        "Authorization": TIANYANCHA_TOKEN
    }

    response = requests.get(TIANYANCHA_API_URL, params=params, headers=headers, timeout=10)
    return response.json()


def format_company_info(item: dict) -> str:
    """格式化企业信息"""
    return f"""
    企业名称: {item.get('name')}
    法人代表: {item.get('legalPersonName')}
    成立日期: {item.get('estiblishTime')}
    注册资本: {item.get('regCapital')}
    经营状态: {item.get('regStatus')}
    统一社会信用代码: {item.get('creditCode')}
    """


if __name__ == "__main__":
    # 搜索示例
    companies = ["腾讯", "阿里巴巴", "华为"]

    for company in companies:
        print(f"\n=== 搜索: {company} ===")
        result = search_company(company)

        if result.get("error_code") == 0:
            items = result.get("result", {}).get("items", [])
            print(f"找到 {result['result']['total']} 条相关结果")
            for item in items:
                print(format_company_info(item))
        else:
            print(f"查询失败: {result.get('reason')}")
