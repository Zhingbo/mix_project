# -*- coding: utf-8 -*-
"""给 step4 打补丁: 三级口径 + 强置信度 + 节点名关键词二次过滤(覆盖字典)"""
import io, sys

P = "/root/mix_project/steps/step4_company_match_nodes.py"
s = open(P, encoding="utf-8").read()
orig = s

NODE_KW_OVERRIDES = """\n# 节点名关键词覆盖字典(行业分类过粗时按公司名收窄, 用于 AI智能算力 等宏观节点链)
NODE_KW_OVERRIDES = {
    "算力中心基础设施": ["数据中心", "机房", "IDC", "算力"],
    "数据中心建设方案": ["数据中心", "机房", "IDC"],
    "TPU芯片（张量处理器）": ["TPU", "芯片", "处理器", "张量"],
    "ASIC芯片（专用集成电路）": ["ASIC", "集成电路", "芯片"],
    "GPU芯片（图形处理器）": ["GPU", "芯片", "显卡", "图形"],
    "智能算力": ["算力", "智能计算", "智算"],
    "通用大模型": ["大模型", "模型"],
    "算力优化软件": ["算力"],
    "垂直大模型": ["大模型", "模型"],
    "大模型服务": ["大模型", "模型"],
    "AI生成内容(AIGC)工具": ["AIGC", "生成"],
    "IDC数据中心": ["IDC", "数据中心", "机房"],
    "算力中心建设与运营": ["数据中心", "算力", "机房"],
    "基础软件与操作系统": ["操作系统", "基础软件", "OS"],
    "中间件": ["中间件"],
    "数据库管理软件": ["数据库", "数据管理", "DB"],
    "编程语言与工具": ["编程", "编译", "开发语言"],
    "智能计算(AIDC)": ["AIDC", "智能计算", "智算"],
    "云服务": ["云计算", "云服务", "云"],
    "边缘计算中心": ["边缘计算"],
    "超算中心": ["超算", "超级计算", "HPC"],
    "AIDC（智算中心）": ["AIDC", "智算", "数据中心"],
    "边缘计算服务": ["边缘计算"],
    "算力服务提供商": ["算力"],
    "高性能计算(HPC)": ["HPC", "超算", "高性能计算"],
    "算力平台运维": ["算力"],
    "算力平台与软件开发": ["算力"],
    "算力资源调度系统": ["算力", "调度"],
    "数据服务": ["数据服务", "数据"],
    "服务器": ["服务器"],
    "IT硬件设备/服务": ["硬件", "IT"],
    "网络通信": ["通信", "网络"],
    "存储": ["存储"],
    "CPU芯片（中央处理器）": ["CPU", "芯片", "中央处理器", "处理器"],
    "芯片封装测试": ["封装", "封测", "芯片"],
    "芯片制造": ["芯片", "晶圆", "半导体", "集成电路"],
    "芯片设计与制造": ["芯片", "集成电路", "半导体"],
    "芯片设计": ["芯片", "集成电路", "半导体"],
    "电力系统": ["电力", "配电", "供电"],
    "冷却系统": ["冷却", "制冷", "温控"],
    "具身智能": ["机器人", "具身智能"],
}
"""

def rep(old, new, expect=1):
    global s
    c = s.count(old)
    if c != expect:
        print(f"[FAIL] 期望 {expect} 处, 实际 {c} 处: {old[:60]!r}")
        sys.exit(1)
    s = s.replace(old, new)
    print(f"[ok] {new[:40]!r}")

# 1. 三级口径
rep("""        # 放宽: 用二级口径(前两段)匹配, 避免三级过细导致漏配
        match_name = '|'.join(full_name.split('|')[:2])""",
"""        # 收紧: 用三级口径(全名)匹配, 避免二级大类导致过宽匹配
        match_name = full_name""")

# 2. SQL 强-only
rep("""              AND (a.industry_class_third LIKE '%强%' OR a.industry_class_third LIKE '%中%')""",
"""              AND a.industry_class_third LIKE '%强%'""")

# 3. 精确验证 强-only
rep("""                if match_name in key and strength in ['强', '中']:""",
"""                if match_name in key and strength == '强':""")

# 4. 节点关键词来源(覆盖字典优先)
rep("""        # 节点关键词(区分细分类型): 去掉通用词后剩下的部分
        _nkw = str(row_b['nodes'])
        for _w in ['汽车', '整车', '车辆', '制造', '系统', '技术', '零部件', '服务', '车', '产业', '核心']:
            _nkw = _nkw.replace(_w, '')
        node_kw = _nkw.strip('，,、- ') if len(_nkw.strip('，,、- ')) >= 2 else '' """,
"""        # 节点关键词(区分细分类型): 优先覆盖字典(行业过粗时按公司名收窄), 否则通用词剥离
        node_name = str(row_b['nodes'])
        node_kws = NODE_KW_OVERRIDES.get(node_name)
        if node_kws is None:
            _nkw = str(row_b['nodes'])
            for _w in ['汽车', '整车', '车辆', '制造', '系统', '技术', '零部件', '服务', '车', '产业', '核心']:
                _nkw = _nkw.replace(_w, '')
            node_kws = [_nkw.strip('，,、- ')] if len(_nkw.strip('，,、- ')) >= 2 else []""")

# 5. 关键词过滤(命中任一即收窄; 完全无命中兜底)
rep("""        # 节点关键词二次过滤: 企业名含关键词则保留; 命中太少(<10)则兜底不过滤
        if node_kw:
            _kw_hit = [r for r in results if node_kw in (r.get('company_name') or '')]
            if len(_kw_hit) >= 10:
                results = _kw_hit
        return results""",
"""        # 节点关键词二次过滤: 企业名命中任一关键词则收窄; 完全无命中则兜底不过滤(避免节点空)
        if node_kws:
            _kw_hit = [r for r in results
                       if any(k.lower() in (r.get('company_name') or '').lower() for k in node_kws)]
            if _kw_hit:
                results = _kw_hit
        return results""")

# 6. 插入覆盖字典(模块级, 放在 step4 函数之前)
anchor = "\ndef step4_company_match_nodes"
if anchor not in s:
    print("[FAIL] 未找到 step4 函数锚点")
    sys.exit(1)
s = s.replace(anchor, NODE_KW_OVERRIDES + anchor, 1)

open(P, "w", encoding="utf-8").write(s)
print(f"[done] 写入完成, 原 {len(orig)} 字节 -> 新 {len(s)} 字节")