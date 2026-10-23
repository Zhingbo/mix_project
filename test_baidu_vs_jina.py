#!/usr/bin/env python3
"""
百度搜索 vs Jina 搜索效果对比测试脚本
使用相同的产业链名称对比两种搜索方式的效果

使用方法:
    python test_baidu_vs_jina.py

运行后会提示输入产业链名称
"""
import asyncio
import json
import sys
import os
from datetime import datetime
from typing import Dict, List, Any
from urllib.parse import urlparse

# 添加项目路径到 sys.path
sys.path.insert(0, '/root/mix_project')
sys.path.insert(0, '/root/mix_project/baidu_spider/baidu_spider')

# 导入百度搜索模块
import baidu_improved
import baidu_data_extractor

# 导入Jina搜索服务
from services.jina_search_service import JinaSearcher


class SearchComparison:
    """搜索效果对比类"""

    def __init__(self, industry_name: str):
        self.industry_name = industry_name
        self.results = {
            'industry_name': industry_name,
            'timestamp': datetime.now().isoformat(),
            'baidu': {
                'results': [],
                'count': 0,
                'unique_sources': set(),
                'avg_title_length': 0,
                'total_content_length': 0,
                'errors': []
            },
            'jina': {
                'results': [],
                'count': 0,
                'unique_sources': set(),
                'avg_title_length': 0,
                'total_content_length': 0,
                'errors': []
            }
        }

    def _extract_domain(self, url: str) -> str:
        """从URL中提取域名"""
        try:
            parsed = urlparse(url)
            return parsed.netloc
        except:
            return "unknown"

    def test_baidu_search(self, max_pages: int = 2):
        """测试百度搜索"""
        print(f"\n{'='*60}")
        print(f"🔍 开始测试百度搜索: {self.industry_name}")
        print(f"{'='*60}")

        try:
            # 使用百度搜索
            keyword = f"{self.industry_name} 产业链"
            results = baidu_improved.search_multiple_pages(keyword, max_pages=max_pages)

            if results:
                # 处理结果
                processed_results = []
                for r in results:
                    processed = {
                        'title': r.get('title', ''),
                        'url': r.get('url', ''),
                        'real_url': r.get('real_url', ''),
                        'description': r.get('description', ''),
                        'source_domain': r.get('source_domain', ''),
                        'page': r.get('page', 1),
                        'index': r.get('index', 0)
                    }

                    # 计算统计数据
                    self.results['baidu']['unique_sources'].add(processed['source_domain'])

                    processed_results.append(processed)

                self.results['baidu']['results'] = processed_results
                self.results['baidu']['count'] = len(processed_results)
                self.results['baidu']['unique_sources'] = list(self.results['baidu']['unique_sources'])

                # 计算平均标题长度
                total_title_len = sum(len(r['title']) for r in processed_results)
                self.results['baidu']['avg_title_length'] = total_title_len / len(processed_results) if processed_results else 0

                # 计算总内容长度
                self.results['baidu']['total_content_length'] = sum(len(r['description']) for r in processed_results)

                print(f"✅ 百度搜索完成，获取到 {len(processed_results)} 条结果")
                print(f"   独立来源数量: {len(self.results['baidu']['unique_sources'])}")
                print(f"   平均标题长度: {self.results['baidu']['avg_title_length']:.1f} 字符")

            else:
                print(f"⚠️ 百度搜索未获取到结果")
                self.results['baidu']['errors'].append("未获取到搜索结果")

        except Exception as e:
            error_msg = f"百度搜索出错: {str(e)}"
            print(f"❌ {error_msg}")
            self.results['baidu']['errors'].append(error_msg)

    async def test_jina_search(self, limit: int = 20):
        """测试Jina搜索"""
        print(f"\n{'='*60}")
        print(f"🔍 开始测试Jina搜索: {self.industry_name}")
        print(f"{'='*60}")

        try:
            # 创建Jina搜索器
            searcher = JinaSearcher(industry_name=self.industry_name)

            # 执行搜索
            results = await searcher.jina_search(
                limit=limit,
                isNode=False,
                user_id=None,
                send_message=None,
                sites=None,
                get_full_content=False,  # 不获取完整内容，只获取搜索结果
                suppress_search_message=True
            )

            if results:
                # 处理结果
                processed_results = []
                for r in results:
                    domain = self._extract_domain(r.get('url', ''))

                    processed = {
                        'title': r.get('title', ''),
                        'url': r.get('url', ''),
                        'description': r.get('content', ''),
                        'source_domain': domain,
                        'content_length': r.get('content_length', len(r.get('content', '')))
                    }

                    # 计算统计数据
                    self.results['jina']['unique_sources'].add(domain)

                    processed_results.append(processed)

                self.results['jina']['results'] = processed_results
                self.results['jina']['count'] = len(processed_results)
                self.results['jina']['unique_sources'] = list(self.results['jina']['unique_sources'])

                # 计算平均标题长度
                total_title_len = sum(len(r['title']) for r in processed_results)
                self.results['jina']['avg_title_length'] = total_title_len / len(processed_results) if processed_results else 0

                # 计算总内容长度
                self.results['jina']['total_content_length'] = sum(r['content_length'] for r in processed_results)

                print(f"✅ Jina搜索完成，获取到 {len(processed_results)} 条结果")
                print(f"   独立来源数量: {len(self.results['jina']['unique_sources'])}")
                print(f"   平均标题长度: {self.results['jina']['avg_title_length']:.1f} 字符")

            else:
                print(f"⚠️ Jina搜索未获取到结果")
                self.results['jina']['errors'].append("未获取到搜索结果")

        except Exception as e:
            error_msg = f"Jina搜索出错: {str(e)}"
            print(f"❌ {error_msg}")
            self.results['jina']['errors'].append(error_msg)

    def print_comparison(self):
        """打印对比结果"""
        print(f"\n{'='*80}")
        print(f"📊 搜索效果对比报告: {self.industry_name}")
        print(f"{'='*80}")

        baidu = self.results['baidu']
        jina = self.results['jina']

        # 基本指标对比
        print(f"\n【基本指标对比】")
        print(f"{'指标':<20} {'百度搜索':<15} {'Jina搜索':<15} {'差异':<15}")
        print(f"{'-'*70}")
        print(f"{'结果数量':<20} {baidu['count']:<15} {jina['count']:<15} {jina['count'] - baidu['count']:<15}")
        print(f"{'独立来源数量':<20} {len(baidu['unique_sources']):<15} {len(jina['unique_sources']):<15} {len(jina['unique_sources']) - len(baidu['unique_sources']):<15}")
        print(f"{'平均标题长度':<20} {baidu['avg_title_length']:<15.1f} {jina['avg_title_length']:<15.1f} {jina['avg_title_length'] - baidu['avg_title_length']:<15.1f}")
        print(f"{'总内容长度':<20} {baidu['total_content_length']:<15} {jina['total_content_length']:<15} {jina['total_content_length'] - baidu['total_content_length']:<15}")

        # 来源域名对比
        print(f"\n【百度搜索来源域名】")
        if baidu['unique_sources']:
            for i, domain in enumerate(baidu['unique_sources'][:10], 1):
                print(f"  {i}. {domain}")
        else:
            print("  无")

        print(f"\n【Jina搜索来源域名】")
        if jina['unique_sources']:
            for i, domain in enumerate(jina['unique_sources'][:10], 1):
                print(f"  {i}. {domain}")
        else:
            print("  无")

        # 共同来源
        baidu_domains = set(baidu['unique_sources'])
        jina_domains = set(jina['unique_sources'])
        common_domains = baidu_domains & jina_domains

        print(f"\n【共同来源】")
        if common_domains:
            for i, domain in enumerate(common_domains, 1):
                print(f"  {i}. {domain}")
        else:
            print("  无共同来源")

        # 错误信息
        if baidu['errors'] or jina['errors']:
            print(f"\n【错误信息】")
            if baidu['errors']:
                print(f"  百度搜索错误:")
                for err in baidu['errors']:
                    print(f"    - {err}")
            if jina['errors']:
                print(f"  Jina搜索错误:")
                for err in jina['errors']:
                    print(f"    - {err}")

    def save_results(self, filename: str = None):
        """保存对比结果到JSON文件"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"search_comparison_{self.industry_name}_{timestamp}.json"

        # 转换set为list以便JSON序列化
        export_data = self.results.copy()
        export_data['baidu'] = self.results['baidu'].copy()
        export_data['jina'] = self.results['jina'].copy()
        export_data['baidu']['unique_sources'] = list(self.results['baidu']['unique_sources'])
        export_data['jina']['unique_sources'] = list(self.results['jina']['unique_sources'])

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        print(f"\n💾 对比结果已保存到: {filename}")

    def print_top_results(self, n: int = 5):
        """打印双方的前N条结果"""
        print(f"\n{'='*80}")
        print(f"📋 搜索结果详情对比 (前{n}条)")
        print(f"{'='*80}")

        # 百度前N条
        print(f"\n【百度搜索 - 前{n}条结果】")
        baidu_results = self.results['baidu']['results'][:n]
        if baidu_results:
            for i, r in enumerate(baidu_results, 1):
                print(f"\n  {i}. {r['title']}")
                print(f"     来源: {r['source_domain']}")
                print(f"     URL: {r['url'][:80]}...")
                if r.get('description'):
                    desc = r['description'][:100] + '...' if len(r['description']) > 100 else r['description']
                    print(f"     描述: {desc}")
        else:
            print("  无结果")

        # Jina前N条
        print(f"\n【Jina搜索 - 前{n}条结果】")
        jina_results = self.results['jina']['results'][:n]
        if jina_results:
            for i, r in enumerate(jina_results, 1):
                print(f"\n  {i}. {r['title']}")
                print(f"     来源: {r['source_domain']}")
                print(f"     URL: {r['url'][:80]}...")
                if r.get('description'):
                    desc = r['description'][:100] + '...' if len(r['description']) > 100 else r['description']
                    print(f"     描述: {desc}")
        else:
            print("  无结果")


async def main():
    """主函数"""
    print("="*80)
    print("百度搜索 vs Jina 搜索效果对比测试")
    print("="*80)

    # 获取用户输入
    industry_input = input("\n请输入要测试的产业链名称: ").strip()
    if not industry_input:
        print("❌ 未输入产业链名称，使用默认值: '锂电池'")
        industry_input = "锂电池"

    test_industries = [industry_input]

    print(f"\n测试产业链: {', '.join(test_industries)}")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_results = []

    for industry in test_industries:
        print(f"\n\n{'#'*80}")
        print(f"# 测试产业链: {industry}")
        print(f"{'#'*80}")

        comparison = SearchComparison(industry)

        # 测试百度搜索
        comparison.test_baidu_search(max_pages=2)

        # 测试Jina搜索
        await comparison.test_jina_search(limit=20)

        # 打印对比结果
        comparison.print_comparison()
        comparison.print_top_results(n=3)

        # 保存单个产业链的对比结果
        comparison.save_results()

        all_results.append(comparison.results)

        # 避免请求过快
        await asyncio.sleep(2)

    # 保存所有结果的汇总
    summary_file = f"search_comparison_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'total_tests': len(test_industries),
            'industries': test_industries,
            'results': all_results
        }, f, ensure_ascii=False, indent=2)

    print(f"\n\n{'='*80}")
    print(f"✅ 所有测试完成！汇总结果已保存到: {summary_file}")
    print(f"{'='*80}")


if __name__ == "__main__":
    asyncio.run(main())
