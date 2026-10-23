# -*- coding: utf-8 -*-
"""
产业链关键词增/删规则
- 依据企业名称关键词, 从底表把缺失企业"补充"进名单, 或把名单里多余企业"删除"
- 增量操作, 不重跑整条链
- 规则持久化到 chain_keyword_rule 表, 每条链独立, 重跑后可重放(replay)
"""
import os
import ast
import pymysql

DB = dict(host='8.141.5.67', port=3306, user='root', password=os.getenv('DB_PASSWORD'),
          database='business_data', charset='utf8mb4', connect_timeout=20)

RULE_TABLE = 'chain_keyword_rule'
NEW_BASE = 'ent_industry_class_chain_scope_20260928_converted'
OLD_BASE = 'ent_industry_class_old'

STEPS = [
    ('company_nodes_mapping', 'company_name'),
    ('company_nodes_info_result', 'company_name'),
    ('company_nodes_final', 'company_name'),
    ('company_nodes_finallist', 'company_name'),
    ('company_list_output', '供应商'),
]


def _conn():
    return pymysql.connect(**DB)


def ensure_rule_table():
    c = _conn()
    cur = c.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {RULE_TABLE} (
            id INT AUTO_INCREMENT PRIMARY KEY,
            industry_name VARCHAR(100) NOT NULL,
            keyword VARCHAR(255) NOT NULL,
            action VARCHAR(10) NOT NULL COMMENT 'add/delete',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_chain_kw_action (industry_name, keyword, action)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产业链关键词增删规则(每条链独立)'
    """)
    c.commit()
    cur.close()
    c.close()


def save_rule(industry_name, keyword, action):
    ensure_rule_table()
    c = _conn()
    cur = c.cursor()
    cur.execute(f"""
        INSERT INTO {RULE_TABLE} (industry_name, keyword, action)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE created_at = NOW()
    """, (industry_name, keyword, action))
    c.commit()
    cur.close()
    c.close()


def list_rules(industry_name):
    ensure_rule_table()
    c = _conn()
    cur = c.cursor()
    cur.execute(f"SELECT id, industry_name, keyword, action, created_at "
                f"FROM {RULE_TABLE} WHERE industry_name=%s ORDER BY id", (industry_name,))
    rows = [{'id': r[0], 'industry_name': r[1], 'keyword': r[2],
             'action': r[3], 'created_at': str(r[4])} for r in cur.fetchall()]
    cur.close()
    c.close()
    return rows


def remove_rule(industry_name, keyword, action=None):
    ensure_rule_table()
    c = _conn()
    cur = c.cursor()
    if action:
        cur.execute(f"DELETE FROM {RULE_TABLE} WHERE industry_name=%s AND keyword=%s AND action=%s",
                    (industry_name, keyword, action))
    else:
        cur.execute(f"DELETE FROM {RULE_TABLE} WHERE industry_name=%s AND keyword=%s",
                    (industry_name, keyword))
    n = cur.rowcount
    c.commit()
    cur.close()
    c.close()
    return n


def get_chain_nodes(industry_name):
    """读 nodes_industry_mapping(step3 输出): (nodes, name, level, full_name)"""
    c = _conn()
    cur = c.cursor()
    cur.execute("SELECT nodes, name, level, full_name FROM nodes_industry_mapping "
                "WHERE industry_name=%s", (industry_name,))
    rows = cur.fetchall()
    cur.close()
    c.close()
    excluded = {industry_name, '上游', '中游', '下游', '产业链上游', '产业链中游', '产业链下游'}
    result = []
    for nodes, name, level, full_name in rows:
        if nodes in excluded or ('上游' in str(nodes) or '中游' in str(nodes) or '下游' in str(nodes)):
            continue
        result.append((str(nodes), str(name) if name else '', str(level) if level else '', str(full_name) if full_name else ''))
    return result


def get_chain_domains(nodes_rows):
    domains = set()
    for _, _, _, full_name in nodes_rows:
        d = str(full_name).split('|')[0].strip()
        if d:
            domains.add(d)
    domains.discard('其他')
    return domains


def get_structure(industry_name):
    """读 industrial_chain_structure -> {node: (parent_node, node_level)} 及 max_level"""
    c = _conn()
    cur = c.cursor()
    cur.execute("SELECT nodes, parent_node, node_level FROM industrial_chain.industrial_chain_structure "
                "WHERE chain_name=%s", (industry_name,))
    rows = cur.fetchall()
    cur.close()
    c.close()
    node_map = {}
    max_level = 1
    for nodes, parent, lv in rows:
        lv = int(lv) if lv is not None else 0
        node_map[str(nodes)] = (str(parent) if parent else '', lv)
        max_level = max(max_level, lv)
    return node_map, max_level


def _auto_match(industry_class_third, nodes_rows, domains):
    """复刻 step4 匹配: 返回匹配到的节点列表 [(nodes, name, level, full_name)]"""
    if not industry_class_third:
        return []
    try:
        d = ast.literal_eval(industry_class_third)
    except (ValueError, SyntaxError):
        try:
            import json
            d = json.loads(industry_class_third)
        except Exception:
            return []
    if not isinstance(d, dict) or not d:
        return []
    matched = []
    for nodes, name, level, full_name in nodes_rows:
        if not full_name:
            continue
        ok = False
        for key, strength in d.items():
            if full_name in str(key) and strength in ('强', '中'):
                # 一级领域防护
                kd = str(key).split('|')[0].strip()
                if domains and kd not in domains:
                    continue
                ok = True
                break
        if ok:
            matched.append((nodes, name, level, full_name))
    return matched


def _find_base_companies(keyword):
    """按关键词从两张底表查企业, 去重(优先老底表)"""
    like = f"%{keyword}%"
    c = _conn()
    cur = c.cursor()
    result = {}
    # 老底表优先
    cur.execute(f"SELECT company_name, company_name_full, credit_code, certainty, industry_class_third "
                f"FROM {OLD_BASE} WHERE company_name LIKE %s", (like,))
    for name, name_full, cc, cert, ict in cur.fetchall():
        cn = (name_full or name).strip()
        if cn:
            result.setdefault(cn, (cn, cc, cert, ict))
    cur.execute(f"SELECT company_name, company_name_full, credit_code, certainty, industry_class_third "
                f"FROM {NEW_BASE} WHERE company_name LIKE %s", (like,))
    for name, name_full, cc, cert, ict in cur.fetchall():
        cn = (name_full or name).strip()
        if cn and cn not in result:
            result[cn] = (cn, cc, cert, ict)
    cur.close()
    c.close()
    return list(result.values())


def _ancestor_path(node, node_map):
    """返回 node 到 root 的祖先链(从 root 到 node)"""
    path = []
    seen = set()
    cur = node
    while cur and cur not in seen:
        seen.add(cur)
        path.append(cur)
        p = node_map.get(cur)
        cur = p[0] if p else None
    path.reverse()
    return path


def apply_add(industry_name, keyword):
    """补齐: 底表命中关键词且不在名单的企业, 自动匹配节点后入库"""
    nodes_rows = get_chain_nodes(industry_name)
    if not nodes_rows:
        return {'status': 'error', 'message': f'产业链 {industry_name} 无节点映射数据'}
    domains = get_chain_domains(nodes_rows)
    node_map, max_level = get_structure(industry_name)

    # 现有名单企业
    c = _conn()
    cur = c.cursor()
    cur.execute("SELECT company_name FROM company_nodes_finallist WHERE industry_name=%s", (industry_name,))
    existing = {r[0] for r in cur.fetchall()}

    # 查底表 + 过滤 + 匹配
    candidates = _find_base_companies(keyword)
    to_add = []
    for cn, cc, cert, ict in candidates:
        if cn in existing:
            continue
        matched = _auto_match(ict, nodes_rows, domains)
        for nodes, name, level, full_name in matched:
            # 取结构里的 parent + node_level
            p, nl = node_map.get(nodes, ('', level))
            to_add.append((cn, nodes, int(nl) if str(nl).isdigit() else int(level) if str(level).isdigit() else 3,
                           p, cert or '1'))

    if not to_add:
        cur.close(); c.close()
        return {'status': 'ok', 'added': 0, 'message': f'关键词"{keyword}"下没有可补充的企业(可能已在名单或未匹配到节点)'}

    # 写 finallist
    for cn, nodes, nl, parent, score in to_add:
        cur.execute("INSERT IGNORE INTO company_nodes_finallist "
                    "(company_name, industry_name, nodes, node_level, parent_node, score) "
                    "VALUES (%s,%s,%s,%s,%s,%s)", (cn, industry_name, nodes, nl, parent, score))
    # 写 list_output(层级右对齐)
    for cn, nodes, nl, parent, score in to_add:
        path = _ancestor_path(nodes, node_map)
        levels = path[-max_level:] if len(path) >= max_level else path
        while len(levels) < max_level:
            levels = [industry_name] + levels
        cols = ['层级%d' % (i + 1) for i in range(max_level)]
        vals = levels[:max_level]
        cur.execute(f"INSERT IGNORE INTO company_list_output (供应商, industry_name, {', '.join(cols)}) "
                    f"VALUES (%s, %s, {', '.join(['%s'] * max_level)})",
                    tuple([cn, industry_name] + vals))
    # 写中间表 mapping + final(为一致性)
    for cn, nodes, nl, parent, score in to_add:
        nm = None
        for n2, name2, lv2, fn2 in nodes_rows:
            if n2 == nodes:
                nm = (name2, lv2, fn2)
                break
        name2, lv2, fn2 = nm if nm else ('', '', '')
        for tbl, col in [('company_nodes_mapping', 'company_name'), ('company_nodes_final', 'company_name')]:
            cur.execute(f"INSERT IGNORE INTO {tbl} (company_name, credit_code, certainty, industry_name, "
                        f"nodes, name, level, full_name, reason) "
                        f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (cn, cc, cert, industry_name, nodes, name2, lv2, fn2, '手动关键词补充'))
    c.commit()
    added = len(to_add)
    cur.close()
    c.close()
    return {'status': 'ok', 'added': added, 'message': f'补充 {added} 家企业(关键词"{keyword}")'}


def apply_delete(industry_name, keyword):
    """删除: 从最终表 + 中间表删掉关键词命中的企业"""
    like = f"%{keyword}%"
    c = _conn()
    cur = c.cursor()
    total = 0
    # 最终名单 + 输出表
    cur.execute("DELETE FROM company_nodes_finallist WHERE industry_name=%s AND company_name LIKE %s",
                (industry_name, like))
    total += cur.rowcount
    cur.execute("DELETE FROM company_list_output WHERE industry_name=%s AND 供应商 LIKE %s",
                (industry_name, like))
    total += cur.rowcount
    # 中间表
    cur.execute("DELETE FROM company_nodes_mapping WHERE industry_name=%s AND company_name LIKE %s",
                (industry_name, like))
    cur.execute("DELETE FROM company_nodes_final WHERE industry_name=%s AND company_name LIKE %s",
                (industry_name, like))
    cur.execute("DELETE FROM company_nodes_info_result WHERE industry_name=%s AND company_name LIKE %s",
                (industry_name, like))
    c.commit()
    cur.close()
    c.close()
    return {'status': 'ok', 'deleted': total, 'message': f'删除 {total} 条记录(关键词"{keyword}")'}


def apply_rule(industry_name, keyword, action):
    ensure_rule_table()
    if action == 'add':
        r = apply_add(industry_name, keyword)
    elif action == 'delete':
        r = apply_delete(industry_name, keyword)
    else:
        return {'status': 'error', 'message': f'未知操作 {action}'}
    if r.get('status') == 'ok' and action in ('add', 'delete'):
        save_rule(industry_name, keyword, action)
    return r


def replay(industry_name):
    """重放该链所有已存的规则(重跑后调用, 先删后补, 保证规则长期生效)"""
    rules = list_rules(industry_name)
    result = {'add': [], 'delete': []}
    # 先执行 delete 规则, 再 add 规则(避免补充的企业又被删)
    for r in rules:
        if r['action'] == 'delete':
            result['delete'].append(apply_delete(industry_name, r['keyword']))
    for r in rules:
        if r['action'] == 'add':
            result['add'].append(apply_add(industry_name, r['keyword']))
    return result