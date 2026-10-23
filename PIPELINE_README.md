# 产业链自动化处理流程 - 使用说明

## 概述

本系统实现了产业链的自动化处理流程（步骤2-10），包括：
- 步骤2: 生成节点定义
- 步骤3: 节点匹配行业
- 步骤4: 公司匹配节点
- 步骤5: 搜索头部企业（从白名单）
- 步骤6: 头部企业匹配节点（AI匹配）
- 步骤7: 拆分结果
- 步骤8: 合并去重清理
- 步骤9: 输出最终名单
- 步骤10: 输出上线表

## 文件结构

```
/root/mix_project/
├── main.py                        # FastAPI 主应用
├── fastapi_manager.sh             # 服务管理脚本
├── pipeline_routes.py             # 产业链自动化处理路由
├── test_pipeline.py               # 测试脚本
├── auto_industry_chain_pipeline.py # 自动化流程主逻辑
├── steps/                         # 步骤脚本目录
│   ├── step2_generate_definition.py
│   ├── step3_match_industry.py
│   ├── step4_company_match_nodes.py
│   ├── step5_search_top_companies.py
│   ├── step6_top_company_match.py
│   ├── step7_split_results.py
│   ├── step8_merge_and_clean.py
│   ├── step9_export_finallist.py
│   └── step10_export_online_tables.py
└─��� api/                           # (已废弃，使用 main.py 代替)
    └── app.py
```

## 启动服务

```bash
cd /root/mix_project
./fastapi_manager.sh start
# 或
./fastapi_manager.sh restart
```

服务启动在端口 8001

## API 端点

### 1. 获取产业链列表

```
GET /api/pipeline/industries
Authorization: Bearer <token>
```

### 2. 获取产业链信息

```
GET /api/pipeline/industry/{industry_name}/info
Authorization: Bearer <token>
```

返回信息包括：
- 节点数量
- 白名单数量
- 处理步骤数

### 3. 启动处理流程

```
POST /api/pipeline/process
Authorization: Bearer <token>
Content-Type: application/json

{
    "industry_name": "氢能产业"
}
```

返回 SSE 流，实时推送处理进度。

## 测试方法

### 方法1: 使用测试脚本

```bash
cd /root/mix_project
python test_pipeline.py 氢能产业
```

### 方法2: 使用 curl

```bash
# 1. 登录
TOKEN=$(curl -s -X POST http://localhost:8001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | jq -r '.data.access_token')

# 2. 获取产业链列表
curl -s http://localhost:8001/api/pipeline/industries \
  -H "Authorization: Bearer $TOKEN" | jq

# 3. 启动处理
curl -s -X POST http://localhost:8001/api/pipeline/process \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"industry_name":"氢能产业"}'
```

## 数据库表

### 统一表（无日期后缀）

- `business_data.chain_needcomp` - 产业链节点信息表
- `business_data.whitelist_company` - 白名单企业表
- `business_data.nodes_industry_mapping` - 节点行业映射表
- `business_data.company_nodes_mapping` - 公司节点映射表
- `business_data.company_nodes_top` - 头部企业待处理表
- `business_data.company_nodes_info_result` - AI匹配结果表
- `business_data.company_nodes_info_split` - 拆分结果表
- `business_data.company_nodes_final` - 最终去重表
- `business_data.company_nodes_finallist` - 最终名单表
- `business_data.industry_structure_output` - 输出结构表
- `business_data.company_list_output` - 输出企业表

## 添加新产业链

### 1. 添加节点数据

将节点数据插入 `chain_needcomp` 表：

```sql
INSERT INTO chain_needcomp (chain_name, nodes, parent_node, node_level)
VALUES ('新产业链', '节点名称', '父节点', 层级);
```

### 2. 添加白名单（可选）

```sql
INSERT INTO whitelist_company (industry_name, position, company_name)
VALUES ('新产业链', '上游', '企业名称');
```

### 3. 调用 API 处理

```bash
python test_pipeline.py 新产业链
```

## 输出结果

处理完成后，结果会输出到：

1. **数据库表** - `company_nodes_finallist`
2. **Excel 文件** - `filled_reports/standard_{产业链名称}_{时间戳}.xlsx`
3. **上线表** - `industry_structure_output` 和 `company_list_output`

## 前端集成

前端可以调用 `/api/pipeline/process` 端点，通过 SSE 接收实时进度。

示例 JavaScript 代码：

```javascript
const eventSource = new EventSource(
    '/api/pipeline/process',
    {
        method: 'POST',
        headers: {
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ industry_name: '氢能产业' })
    }
);

eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(data);

    if (data.type === 'progress') {
        // 更新进度条
        updateProgress(data.content);
    } else if (data.type === 'completed') {
        // 处理完成
        eventSource.close();
    }
};
```
