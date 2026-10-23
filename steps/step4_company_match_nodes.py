"""
步骤4：公司匹配节点（SQL优化版 + 并行 + LLM反向排除）

优化点：
- 不再读全表到内存
- 对每个节点的 full_name 做 SQL LIKE 查询，直接在数据库里匹配
- 一级领域跨行业防护改用 industry_class_first 等值过滤（走 idx_ic_first 索引，大幅提速）
- 节点查询并行化（线程池）
- 匹配完成后用 LLM 生成"该产业链一定不会出现的名字特征词"，反向过滤掉误入企业（只作用于 step4 结果，不动白名单）
"""
import pandas as pd
from sqlalchemy import create_engine, text
import ast
import re

# 确定性基础排除词(企业名称含这些词, 一票否决, 任何产业链都不该有)
BASE_EXCLUDE_RE = re.compile(
    r"银行|证券|保险|典当|担保|小额贷款|融资租赁|信托|期货|基金管理|财富管理|支付"
    r"|房地产|地产|物业|置业|房产|售楼|中介"
    r"|餐饮|酒店|饭店|旅馆|民宿|住宿|酒楼|火锅|烧烤|咖啡|奶茶|烘焙|茶饮"
    r"|旅游|旅行社|景区|度假|游乐园|滑雪|漂流"
    r"|教育|培训|学校|幼儿园|托育|驾校|艺考|留学|辅导|家教"
    r"|游戏|直播|短视频|影视|电影院|传媒|出版|广告|动漫|网吧|剧本杀|KTV|酒吧|娱乐|演艺|经纪"
    r"|超市|便利店|百货|批发|零售|专卖|商贸|贸易|商场|购物中心|农贸"
    r"|电商|电子商务|网店|淘宝|天猫|网商"
    r"|物流|快递|货运|仓储|搬家|配送|供应链"
    r"|家政|保洁|月嫂|保姆|干洗|洗衣|搬家公司"
    r"|美容|美发|美甲|SPA|足浴|洗浴|推拿|按摩|养生|减肥|植发|纹身|洗脚"
    r"|殡葬|公墓|墓园|寿衣"
    r"|宠物|宠物医院|宠物食品|宠物美容|宠物用品"
    r"|婚纱|婚庆|写真|影楼"
    r"|花店|花卉|绿植|苗木|园艺"
    r"|二手车|4S店|汽修|洗车|汽车美容|汽车租赁"
    r"|彩票|棋牌|茶馆|会所|俱乐部|健身|瑜伽|舞蹈"
    r"|食品|饮料|白酒|啤酒|黄酒|红酒|葡萄酒|乳业|粮油|调味品|零食|屠宰|肉制品|水产|果蔬|糖果|蜜饯"
    r"|种植|养殖|农场|种子|化肥|农药|饲料|农机|畜牧|渔业|林业"
    r"|纺织|服装|面料|印染|皮革|家纺|服饰|箱包|制衣|针织|羽绒|毛纺|袜"
    r"|家具|厨具|瓷砖|地板|门窗|涂料|油漆|卫浴|洁具|橱柜|衣柜|木门|建材|装修|窗帘|灯具"
    r"|饰品|珠宝|黄金|白银|玉石|翡翠|钟表|眼镜|工艺品|文玩|木雕|陶瓷|玩具|文具"
    r"|化妆品|日化|牙膏|洗衣液|卫生巾|纸尿裤|香皂|洗发水|沐浴露|香水"
    r"|煤矿|铁矿|金矿|铜矿|矿山|冶金|钢铁|水泥|砂石|采石|焦化|炼钢|有色金属"
    r"|煤炭|石油|天然气|火电|炼油|加油站"
)
import os
import json
import pymysql
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from .cancel_token import is_cancelled, reset_token, remove_token

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("DASHSCOPE_API_KEY", os.getenv("DASHSCOPE_API_KEY"))
OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4.1-flash"


def _cleanup_deleted_nodes_from_mapping(industry_name: str, removed_nodes: list, tables: dict) -> int:
    """清理已删除节点的公司匹配数据"""
    if not removed_nodes:
        return 0
    conn = pymysql.connect(
        host='8.141.5.67', user='root', password=os.getenv('DB_PASSWORD'), database='business_data'
    )
    cursor = conn.cursor()
    deleted_count = 0
    for node in removed_nodes:
        try:
            cursor.execute(
                "DELETE FROM company_nodes_mapping WHERE industry_name = %s AND nodes = %s",
                (industry_name, node)
            )
            deleted_count += cursor.rowcount
        except Exception as e:
            logger.warning(f"清理 company_nodes_mapping 中节点 {node} 失败: {e}")
    conn.commit()
    cursor.close()
    conn.close()
    logger.info(f"清理已删除节点 {removed_nodes} 的公司匹配数据，共 {deleted_count} 条")
    return deleted_count


def _generate_exclusion_keywords(industry_name: str, node_names: list) -> list:
    """让 LLM 分析: 企业名称中含什么特征就几乎一定不属于该产业链, 返回排除关键词列表"""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        node_list = "、".join([str(n) for n in node_names[:80] if str(n) not in ('', 'nan')])
        user_msg = (
            f"产业链名称：{industry_name}\n"
            f"产业链节点（环节）：{node_list}\n\n"
            f"请判断：企业名称中包含哪些词（或特征），就几乎一定不属于「{industry_name}」这个产业链，应该被剔除。\n"
            f"要求：\n"
            f"1. 只给明确不属于该产业链的行业/产品特征词。例如产业链是「生命健康」，则“五金、模具、纺织、服装、汽车、光伏、储能、半导体、家具、食品、物流、房地产、传媒、游戏”这类无关行业的词就是排除特征。\n"
            f"2. 不要给“科技、实业、集团、贸易、销售、制造、信息、工程、服务”这类几乎所有行业都有的泛词。\n"
            f"3. 宁缺毋滥，只给高置信度、且会出现在企业名称里的词。\n"
            f"4. 排除词应为 2~8 个汉字的中文词。\n"
            f"请严格按 JSON 输出：{{\"exclude_keywords\": [\"词1\", \"词2\", ...]}}"
        )
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是产业链企业名单审核助手，负责给出“一定不属于某产业链”的企业名称排除特征词。"},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        kws = data.get("exclude_keywords", []) if isinstance(data, dict) else []
        kws = [str(k).strip() for k in kws if str(k).strip()]
        # 安全约束: 去掉单字/超长/含空白词, 去重
        kws = [k for k in dict.fromkeys(kws) if 2 <= len(k) <= 12 and ' ' not in k and '，' not in k and ',' not in k]
        return kws
    except Exception as e:
        print(f"LLM 反向排除词生成失败: {e}，跳过反向过滤")
        return []


# 节点名关键词覆盖字典(行业分类过粗时按公司名收窄, 用于 AI智能算力 等宏观节点链)
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
    # ==== 合成生物 ====
    "生物信息学分析平台": ["生物信息", "生信", "基因", "基因组", "组学", "测序",
                   "转录组", "蛋白组", "代谢组", "分子诊断", "分子生物", "生物芯片",
                   "生命科学", "高通量", "基因检测", "基因科技"],
}
# 产业链主题关键词(泛环节收窄用: 环节名含泛词时, 用主题词过滤企业名, 避免脱离主题过匹配)
CHAIN_THEME_KEYWORDS = {
    '大飞机': ['航空', '飞机', '机场', '航天', '民航', '机务', '飞行', '无人机', '直升机', '航空器', '航材', '客机'],
}

# 泛化环节词(含这些词的环节, 若未配置节点关键词, 则用产业链主题关键词收窄)
GENERIC_NODE_WORDS = ['维修', '检修', '修理', '维护']

def _load_chain_blacklist(industry_name: str) -> set:
    """加载产业链排除黑名单(人工清洗标记的无关企业), 返回企业名集合"""
    try:
        conn = pymysql.connect(host='8.141.5.67', user='root', password=os.getenv('DB_PASSWORD'),
                               database='business_data', charset='utf8mb4')
        cur = conn.cursor()
        cur.execute("SELECT company_name FROM chain_exclude_company WHERE industry_name=%s", (industry_name,))
        s = set(r[0] for r in cur.fetchall())
        cur.close(); conn.close()
        return s
    except Exception as e:
        print(f"加载产业链黑名单失败(忽略): {e}")
        return set()


def step4_company_match_nodes(industry_name, tables, whitelist_data=None, progress_callback=None, change_context=None):
    """
    将公司匹配到产业链节点（SQL优化版 + 并行 + LLM反向排除）
    """
    host = '8.141.5.67'
    user = 'root'
    password = os.getenv('DB_PASSWORD')
    database = 'business_data'
    port = 3306

    target_table = tables['company_nodes_mapping']
    source_table = tables['ent_industry_class_old']
    old_source_table = 'ent_industry_class_old'  # 老底表(26.9万, 匹配时优先)
    nodes_mapping_table = tables.get('nodes_industry_mapping', 'nodes_industry_mapping')

    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}")

    print(f"\n{'='*40}")
    print(f"步骤4：公司匹配节点（SQL优化版 + 并行 + LLM反向排除）")
    print(f"产业链名称: {industry_name}")
    print(f"目标表: {target_table}")

    reset_token(industry_name)

    if change_context:
        removed_nodes = change_context.get('removed_nodes', [])
        if removed_nodes:
            print(f"检测到已删除节点: {removed_nodes}，开始清理关联数据")
            _cleanup_deleted_nodes_from_mapping(industry_name, removed_nodes, tables)

    # 创建目标表
    def create_table_if_not_exists():
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {target_table} (
            company_name VARCHAR(255),
            credit_code VARCHAR(100),
            certainty VARCHAR(20),
            industry_name VARCHAR(255),
            nodes TEXT,
            name VARCHAR(255),
            level VARCHAR(50),
            full_name VARCHAR(255),
            reason TEXT
        )
        """
        try:
            with engine.connect() as conn:
                conn.execute(text(create_table_sql))
            print(f"表 {target_table} 检查完成")
        except Exception as e:
            print(f"创建表失败：{e}")

    create_table_if_not_exists()

    # 1. 查询节点行业映射数据
    industry_name_escaped = industry_name.replace("'", "''")
    query_b = f"""
    SELECT industry_name, nodes, name, level, full_name, reason
    FROM {nodes_mapping_table}
    WHERE industry_name = '{industry_name_escaped}'
    """
    df_b = pd.read_sql(query_b, engine)
    df_b['full_name'] = df_b['full_name'].astype(str)

    if df_b.empty:
        print(f"警告：未找到产业链 '{industry_name}' 的节点映射数据")
        return {"step": 4, "name": "公司匹配节点", "status": "skipped", "reason": "无节点映射数据"}

    # 过滤掉0级、1级节点
    excluded_patterns = [industry_name, '上游', '中游', '下游', '产业链上游', '产业链中游', '产业链下游']
    original_count = len(df_b)
    df_b = df_b[~df_b['nodes'].isin(excluded_patterns) &
                ~df_b['nodes'].str.contains('上游|中游|下游', na=False) &
                ~df_b['full_name'].str.contains('上游|中游|下游', na=False)]
    filtered_count = len(df_b)
    print(f"加载节点映射数据: {original_count} 条 -> 过滤后: {filtered_count} 条")

    # 提取一级领域集合
    chain_level1_domains = set()
    for _, row_b in df_b.iterrows():
        domain = str(row_b['full_name']).split('|')[0].strip()
        if domain:
            chain_level1_domains.add(domain)
    chain_level1_domains.discard('其他')
    print(f"产业链 '{industry_name}' 相关一级领域: {sorted(chain_level1_domains)}")

    if df_b.empty:
        print("过滤后无节点，跳过")
        return {"step": 4, "name": "公司匹配节点", "status": "skipped", "reason": "无有效节点"}

    # 2. 删除旧数据
    with engine.connect() as conn:
        delete_sql = text(f"DELETE FROM {target_table} WHERE industry_name = :industry_name")
        conn.execute(delete_sql, {"industry_name": industry_name})
        conn.commit()

    # 3. 构建一级领域防护 SQL 条件（等值过滤，走 idx_ic_first 索引）
    if chain_level1_domains:
        domain_list = sorted(chain_level1_domains)
        quoted = ",".join("'" + d.replace("'", "''") + "'" for d in domain_list)
        domain_filter = f"AND a.industry_class_first IN ({quoted})"
    else:
        domain_filter = ""

    nodes_rows = list(df_b.iterrows())

    blacklist_set = _load_chain_blacklist(industry_name)
    if blacklist_set:
        print(f"产业链 {industry_name} 黑名单 {len(blacklist_set)} 家, 匹配时将剔除")

    def _match_one_node(row_b):
        """单个节点的匹配，返回 matched 列表（供线程池并发）"""
        full_name = str(row_b['full_name'])
        if not full_name or full_name == 'nan':
            return []
        # 收紧: 用三级口径(全名)匹配, 避免二级大类导致过宽匹配
        match_name = full_name
        match_name_escaped = match_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("'", "''")
        # 节点关键词(区分细分类型): 优先覆盖字典(行业过粗时按公司名收窄), 否则通用词剥离
        node_name = str(row_b['nodes'])
        node_kws = NODE_KW_OVERRIDES.get(node_name)
        if node_kws is None:
            # 泛化环节(含维修/检修等泛词) -> 用产业链主题关键词收窄
            if any(w in node_name for w in GENERIC_NODE_WORDS):
                node_kws = CHAIN_THEME_KEYWORDS.get(industry_name, [])
            # 其余节点: 不再用节点名过滤公司名(节点名≠公司名, 避免欠匹配),
            # 完全信任 step3 的行业映射 + 手动覆盖字典
        def _query_node(table, use_domain=True):
            _df = domain_filter if use_domain else ""
            _sql = f"""
            SELECT COALESCE(a.company_name_full, a.company_name) AS company_name,
                   a.credit_code, a.certainty, a.industry_class_third
            FROM {table} a
            WHERE a.industry_class_third LIKE '%{match_name_escaped}%'
              AND a.industry_class_third LIKE '%强%'
              {_df}
            """
            _c = pymysql.connect(host=host, user=user, password=password, database=database, port=port)
            try:
                _cur = _c.cursor()
                try:
                    _cur.execute(_sql)
                    return _cur.fetchall()
                except Exception as e:
                    print(f"查询节点 {full_name} 失败: {e}")
                    return []
                finally:
                    _cur.close()
            finally:
                _c.close()

        results = []
        # 老底表优先: 先查老底表, 再查新底表(跳过老底表已命中的公司), 实现"老底表为主"
        _old_rows = _query_node(old_source_table, use_domain=False)
        _old_companies = set(r[0] for r in _old_rows)
        _new_rows = [r for r in _query_node(source_table) if r[0] not in _old_companies]
        rows = list(_old_rows) + _new_rows

        for row in rows:
            company_name, credit_code, certainty, industry_class_third = row
            try:
                industry_dict = ast.literal_eval(industry_class_third) if industry_class_third else {}
            except (ValueError, SyntaxError):
                continue
            if not industry_dict:
                continue

            # 精确验证: full_name 是某个 key 的子串, 且 value 是 '强'/'中'
            matched = False
            for key, strength in industry_dict.items():
                if match_name in key and strength == '强':
                    matched = True
                    break
            if not matched:
                continue

            # 一级领域防护(精确验证)
            if chain_level1_domains:
                company_has_relevant_domain = False
                for cls_key in industry_dict.keys():
                    company_domain = str(cls_key).split('|')[0].strip()
                    if company_domain in chain_level1_domains:
                        company_has_relevant_domain = True
                        break
                if not company_has_relevant_domain:
                    continue

            results.append({
                'company_name': company_name,
                'credit_code': credit_code,
                'certainty': (certainty if certainty else '1'),
                'industry_name': row_b['industry_name'],
                'nodes': row_b['nodes'],
                'name': row_b['name'],
                'level': row_b['level'],
                'full_name': row_b['full_name'],
                'reason': row_b['reason']
            })

        # 节点关键词二次过滤: 企业名命中任一关键词则收窄; 完全无命中则兜底不过滤(避免节点空)
        if node_kws:
            _kw_hit = [r for r in results
                       if any(k.lower() in (r.get('company_name') or '').lower() for k in node_kws)]
            if _kw_hit:
                results = _kw_hit
        # 产业链黑名单过滤(确保无关企业不再挂载)
        if blacklist_set:
            results = [r for r in results if (r.get('company_name') or '') not in blacklist_set]
        return results

    # 4. 并行匹配所有节点
    total_nodes = len(nodes_rows)
    all_matched = []
    nodes_processed = 0
    max_workers = 8
    print(f"开始并行匹配节点，线程数={max_workers}，节点数={total_nodes}")

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_match_one_node, row_b) for _, row_b in nodes_rows]
        for fut in as_completed(futures):
            if is_cancelled(industry_name):
                print("步骤4已被取消")
                remove_token(industry_name)
                return {"step": 4, "name": "公司匹配节点", "status": "cancelled", "message": "用户取消操作"}
            all_matched.extend(fut.result())
            nodes_processed += 1
            if nodes_processed % 10 == 0:
                print(f"  节点进度: {nodes_processed}/{total_nodes}, 累计匹配: {len(all_matched)}")
                if progress_callback:
                    progress_callback('batch_progress', {
                        'batch': nodes_processed,
                        'total_batches': total_nodes,
                        'count': len(all_matched),
                        'message': f'节点 {nodes_processed}/{total_nodes} 完成，累计 {len(all_matched)} 条'
                    })

    # 5. 去重: 同一企业+同一行业只保留一条
    seen_pairs = set()
    deduped = []
    for m in all_matched:
        dedup_key = (m['company_name'], m['nodes'])
        if dedup_key not in seen_pairs:
            seen_pairs.add(dedup_key)
            deduped.append(m)
    all_matched = deduped
    print(f"\n匹配完成，去重后共 {len(all_matched)} 条记录")

    # 6.0 生命健康专用: 药房/药铺企业强制挂到下游"线下药店"
    if industry_name == '生命健康' and all_matched:
        _xd = df_b[df_b['nodes'] == '线下药店']
        _xd_full = str(_xd.iloc[0]['full_name']) if not _xd.empty else '医疗流通|医药零售|线下药店'
        _xd_name = str(_xd.iloc[0]['name']) if not _xd.empty else '线下药店'
        _xd_cnt = 0
        for _m in all_matched:
            _cn = _m.get('company_name') or ''
            if ('药房' in _cn) or ('药铺' in _cn):
                _m['nodes'] = '线下药店'
                _m['name'] = _xd_name
                _m['level'] = '3'
                _m['full_name'] = _xd_full
                _m['reason'] = '生命健康下游:药房/药铺'
                _xd_cnt += 1
        print(f'药房/药铺强制挂下游: {_xd_cnt} 条')

    # 6. LLM 反向排除: 生成"该链一定不会出现的名字特征"，过滤误入企业
    if all_matched:
        node_names = list(dict.fromkeys([str(r['name']) for r in all_matched]))
        exclude_kws = _generate_exclusion_keywords(industry_name, node_names)
        if exclude_kws:
            print(f"LLM 生成的排除特征词({len(exclude_kws)}): {exclude_kws}")
            before = len(all_matched)
            filtered = [m for m in all_matched
                        if not any(kw in (m['company_name'] or '') for kw in exclude_kws)]
            removed = before - len(filtered)
            print(f"反向过滤: 移除 {removed} 家，剩余 {len(filtered)} 家")
            all_matched = filtered
        else:
            print("LLM 未生成有效排除词，跳过反向过滤")

    # 6.5 确定性基础排除(一票否决层), 合成生物/生命健康除外(其链内含食品/医药等)
    if all_matched and industry_name not in ("合成生物", "生命健康"):
        before2 = len(all_matched)
        all_matched = [m for m in all_matched
                       if not BASE_EXCLUDE_RE.search(m.get('company_name') or '')]
        print(f"确定性排除: 移除 {before2 - len(all_matched)} 家, 剩余 {len(all_matched)} 家")

    # 7. 插入结果到目标表
    if all_matched:
        result_df = pd.DataFrame(all_matched)
        batch_size = 5000
        for i in range(0, len(result_df), batch_size):
            batch = result_df.iloc[i:i+batch_size]
            try:
                batch.to_sql(target_table, engine, index=False, if_exists='append')
                print(f"  插入批次 {i//batch_size + 1}/{(len(result_df)+batch_size-1)//batch_size}: {len(batch)} 条")
            except Exception as e:
                print(f"  插入失败: {e}")

    remove_token(industry_name)
    print(f"步骤4完成，数据已插入到 {target_table}")
    return {"step": 4, "name": "公司匹配节点", "status": "completed"}


if __name__ == "__main__":
    from auto_industry_chain_pipeline import TABLES
    step4_company_match_nodes("氢能产业", TABLES)