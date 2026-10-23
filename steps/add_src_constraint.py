# -*- coding: utf-8 -*-
p = "step6_top_company_match.py"
s = open(p, encoding="utf-8").read()
anchor = "- 返回30-50家企业（尽可能多地返回）\n"
constraint = ('- 【严格限定行业】只返回真正属于"{industry_name}"产业链的企业，绝不返回保险、金融、证券、银行、'
              '房地产、汽车、光伏、太阳能、半导体、游戏、传媒、物流、电商、食品、纺织等明显不相干行业的企业\n'
              '- 返回30-50家企业（尽可能多地返回）\n')
if anchor in s and "严格限定行业" not in s:
    s = s.replace(anchor, constraint, 1)
    open(p, "w", encoding="utf-8").write(s)
    print("搜索时行业限定已加")
else:
    print("已存在或锚点未找到")
