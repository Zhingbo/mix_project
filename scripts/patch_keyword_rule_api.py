# -*- coding: utf-8 -*-
# 给 pipeline_routes.py 追加"产业链关键词增删规则"相关 API 端点
import io
import datetime

FN = '/root/mix_project/pipeline_routes.py'
src = io.open(FN, 'r', encoding='utf-8').read()

bkp = FN + '.bak_kwrule_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
io.open(bkp, 'w', encoding='utf-8').write(src)
print('backup ->', bkp)

addition = '''

# ==================== 产业链关键词增删规则 ====================
from steps.chain_keyword_rule import apply_rule, list_rules as list_kw_rules, remove_rule, replay, ensure_rule_table


@pipeline_router.post("/keyword_rule")
async def apply_keyword_rule(request: Request, current_user: dict = Depends(get_current_user)):
    """
    按企业名称关键词补充/删除名单企业 (增量, 不重跑整条链)

    请求体:
    {
        "industry_name": "产业链名称",
        "keyword": "企业名称关键词",
        "action": "add" 或 "delete"
    }
    - add: 从两张底表查含关键词的企业, 自动匹配节点后补充进名单(并持久化规则)
    - delete: 从最终名单 + 过程表删除含关键词的企业(并持久化规则)
    """
    data = await request.json()
    industry_name = (data.get("industry_name") or "").strip()
    keyword = (data.get("keyword") or "").strip()
    action = (data.get("action") or "").strip()
    if not industry_name or not keyword or action not in ("add", "delete"):
        raise HTTPException(status_code=400, detail="industry_name/keyword 必填, action 必须为 add 或 delete")
    try:
        return apply_rule(industry_name, keyword, action)
    except Exception as e:
        logger.error(f"关键词规则执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"执行失败: {e}")


@pipeline_router.get("/keyword_rule/{industry_name}")
async def get_keyword_rules(industry_name: str, current_user: dict = Depends(get_current_user)):
    """查询某条链已保存的关键词增删规则"""
    try:
        return list_kw_rules(industry_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


@pipeline_router.delete("/keyword_rule")
async def remove_keyword_rule(request: Request, current_user: dict = Depends(get_current_user)):
    """删除某条链的某条关键词规则(撤销); action 可选"""
    data = await request.json()
    industry_name = (data.get("industry_name") or "").strip()
    keyword = (data.get("keyword") or "").strip()
    action = (data.get("action") or "").strip() or None
    if not industry_name or not keyword:
        raise HTTPException(status_code=400, detail="industry_name/keyword 必填")
    try:
        n = remove_rule(industry_name, keyword, action)
        return {"status": "ok", "removed": n}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除规则失败: {e}")


@pipeline_router.post("/keyword_rule/replay/{industry_name}")
async def replay_keyword_rules(industry_name: str, current_user: dict = Depends(get_current_user)):
    """重放某条链的所有关键词规则(重跑后自动/手动调用, 先删后补)"""
    try:
        return replay(industry_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重放失败: {e}")
'''

if '# ==================== 产业链关键词增删规则 ====================' in src:
    print('已存在, 跳过')
else:
    src = src.rstrip() + '\n' + addition
    io.open(FN, 'w', encoding='utf-8').write(src)
    print('已追加 API 端点')

# 语法检查
import ast
try:
    ast.parse(src)
    print('pipeline_routes.py 语法OK')
except SyntaxError as e:
    print('语法错误(需还原备份):', e)