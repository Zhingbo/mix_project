# -*- coding: utf-8 -*-
# 给 step6 的"自搜企业"加非健康过滤, 防止混入保险/汽车/能源等
p = "step6_top_company_match.py"
s = open(p, encoding="utf-8").read()

HELPER = '''
NON_HEALTH_RE = ("保险|证券|银行|融资租赁|典当|担保|小额贷款|汽车|整车|汽配|轮胎|光伏|太阳能|储能|"
                 "风电|氢能|燃料电池|半导体|集成电路|物流|快递|电商|电子商务|游戏|传媒|影视|直播|"
                 "出版|矿业|矿山|钢铁|煤炭|石油|天然气|冶金|食品|饮料|白酒|啤酒|粮油|饲料|屠宰|"
                 "养殖|种养殖|纺织|服装|面料|印染|皮革|鞋业|五金|模具|机床|铸造|轴承|减速机|液压|"
                 "阀门|建材|水泥|照明|家电|家具|厨具|服饰|饰品|商贸|旅游|餐饮|酒店")
HEALTH_RE = ("医药|医疗|医|药|生物|健康|康复|诊断|医院|诊所|基因|细胞|中药材|保健|卫生|口腔|"
             "眼科|疫苗|器械|制药|药业")


def _is_non_health_name(name):
    """企业名含非健康行业词且不含健康词 -> 判为不该进该链"""
    n = str(name or "")
    return bool(re.search(NON_HEALTH_RE, n)) and not bool(re.search(HEALTH_RE, n))
'''

# 插入 helper(在 MATCH_BATCH_SIZE 之后)
anchor = "MATCH_BATCH_SIZE = 5\n"
if anchor in s and "def _is_non_health_name" not in s:
    s = s.replace(anchor, anchor + HELPER, 1)
    print("helper 已插入")
else:
    print("helper 已存在或锚点未找到")

# 过滤自搜企业
old = "        raw_companies = raw_position_results.get(position, [])\n"
new = ("        raw_companies = raw_position_results.get(position, [])\n"
       "        raw_companies = [c for c in raw_companies if not _is_non_health_name(c)]\n")
if s.count(old) == 1:
    s = s.replace(old, new, 1)
    print("自搜企业过滤已插入")
else:
    print(f"自搜锚点命中 {s.count(old)} 处, 跳过")

open(p, "w", encoding="utf-8").write(s)
print("完成")