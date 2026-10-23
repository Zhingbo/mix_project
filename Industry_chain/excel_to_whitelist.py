#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将Excel中的产业链企业名单转换为白名单txt格式

用法:
    python excel_to_whitelist.py <excel_file_path> <industry_name>

示例:
    python excel_to_whitelist.py 工业元宇宙头部企业名单.xlsx 工业元宇宙
"""

import pandas as pd
import sys
import os

def excel_to_whitelist(excel_path, industry_name):
    """
    将Excel文件转换为白名单txt格式

    Args:
        excel_path: Excel文件路径
        industry_name: 产业链名称
    """
    try:
        # 读取Excel文件
        df = pd.read_excel(excel_path, sheet_name=0)
        print(f"读取Excel文件成功: {excel_path}")
        print(f"数据行数: {len(df)}")
        print(f"列名: {list(df.columns)}\n")

        # 定义环节映射（根据Excel中的分类标题）
        category_mapping = {
            "1、数字孪生/工业软件巨头": "上游",
            "2、工业XR/交互技术商": "上游",
            "3、工业云平台/物联网": "中游",
            "4、图形引擎/仿真工具": "中游",
            "5、垂直行业解决方案商": "中游",
            "6、核心硬件/芯片": "下游",
            "7、新兴技术融合企业": "下游",
        }

        # 按环节分类存储企业
        companies_by_position = {
            "上游": [],
            "中游": [],
            "下游": []
        }

        # 检查列名是否包含第一个分类
        first_col_name = str(df.columns[0]).strip()
        if "1、数字孪生/工业软件巨头" in first_col_name:
            print(f"发现分类（从列名）: 1、数字孪生/工业软件巨头 -> 上游")
            # 提取第一类的企业（从列名所在行到第一个NaN之前）
            for idx in range(len(df)):
                company_name = str(df.iloc[idx, 0]).strip()
                # 遇到NaN或下一个分类标题时停止
                if company_name == 'nan' or '2、' in company_name:
                    break
                # 跳过分类标题本身
                if '1、' in company_name or '数字孪生' in company_name:
                    continue
                # 添加到上游
                if company_name and company_name not in companies_by_position["上游"]:
                    companies_by_position["上游"].append(company_name)
                    print(f"  添加企业 [上游]: {company_name}")

        # 当前的分类
        current_category = None

        # 遍历每一行
        for idx, row in df.iterrows():
            # 检查第一列是否是分类标题
            first_col_value = str(row.iloc[0]).strip()

            # 判断是否是分类标题
            for category in category_mapping.keys():
                if category in first_col_value:
                    current_category = category
                    print(f"发现分类: {category} -> {category_mapping[category]}")
                    break

            # 如果当前有分类，且第一列是企业名称（不是NaN且不是分类标题）
            if current_category and pd.notna(row.iloc[0]):
                company_name = str(row.iloc[0]).strip()

                # 跳过NaN值、分类标题本身、以及说明文字
                if (company_name == 'nan' or
                    any(cat_key in company_name for cat_key in category_mapping.keys()) or
                    '（' in company_name and '排除' in company_name or  # 说明性文字
                    company_name.startswith('（') or  # 以括号开头的说明
                    '已排除' in company_name or  # 包含"已排除"的说明
                    '企业）' in company_name):  # 以"企业）"结尾的说明
                    continue

                # 添加到对应环节
                position = category_mapping[current_category]
                if company_name and company_name not in companies_by_position[position]:
                    companies_by_position[position].append(company_name)
                    print(f"  添加企业 [{position}]: {company_name}")

        # 保存到白名单文件
        print("\n" + "="*50)
        print("开始保存白名单文件...")
        print("="*50 + "\n")

        for position, companies in companies_by_position.items():
            if companies:
                # 生成文件名：white_list_top_{产业链名}_{环节}.txt
                filename = f"white_list_top_{industry_name}_{position}.txt"
                filepath = os.path.join(os.path.dirname(excel_path), filename)

                # 写入文件
                with open(filepath, 'w', encoding='utf-8') as f:
                    for company in companies:
                        f.write(f"{company}\n")

                print(f"✓ 已保存 {filename} ({len(companies)} 家企业)")
                print(f"  路径: {filepath}\n")

                # 显示前5个企业
                print(f"  前5个企业: {', '.join(companies[:5])}")
                if len(companies) > 5:
                    print(f"  ...\n")
            else:
                print(f"✗ {position} 没有企业数据\n")

        print("="*50)
        print("转换完成！")
        print("="*50)

        # 显示统计信息
        total = sum(len(companies) for companies in companies_by_position.values())
        print(f"\n总计: {total} 家企业")
        for position, companies in companies_by_position.items():
            print(f"  {position}: {len(companies)} 家")

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("用法: python excel_to_whitelist.py <excel_file_path> [industry_name]")
        print("\n示例:")
        print("  python excel_to_whitelist.py 工业元宇宙头部企业名单.xlsx 工业元宇宙")
        sys.exit(1)

    excel_path = sys.argv[1]

    # 如果没有提供产业链名称，从文件名中提取
    if len(sys.argv) >= 3:
        industry_name = sys.argv[2]
    else:
        # 从文件名提取产业链名称（移除"头部企业名单.xlsx"等后缀）
        filename = os.path.basename(excel_path)
        industry_name = filename.replace("头部企业名单.xlsx", "").replace(".xlsx", "")
        print(f"从文件名提取产业链名称: {industry_name}\n")

    excel_to_whitelist(excel_path, industry_name)


if __name__ == "__main__":
    main()
