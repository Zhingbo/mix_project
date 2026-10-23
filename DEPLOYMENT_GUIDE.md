# 产业链自动化处理 - 完整部署说明

## 修改摘要

已在 `ChatContainer.vue` 中的 mindmap 步骤下方添加"开始自动化处理"按钮。

**按钮位置**: 当用户点击侧边栏的产业链后，在显示的图谱下方会出现按钮。

## 文件修改列表

### 后端
1. **pipeline_routes.py** (新增)
   - API 路由: `/api/pipeline/process`
   - 使用 SSE 推送进度

2. **main.py**
   - 注册了 `pipeline_router`

3. **steps/** 目录 (9个步骤脚本)
   - step2_generate_definition.py
   - step3_match_industry.py
   - step4_company_match_nodes.py
   - step5_search_top_companies.py
   - step6_top_company_match.py
   - step7_split_results.py
   - step8_merge_and_clean.py
   - step9_export_finallist.py
   - step10_export_online_tables.py

### 前端
1. **ChatContainer.vue**
   - 第177-227行: 在 mindmap 模板中添加按钮和状态显示
   - 第2516-2663行: 添加 `startPipelineProcessing` 和 `togglePipelineMessages` 方法
   - 第2725-2780行: 添加 CSS 样式

## 部署步骤

### 1. 重启后端服务
```bash
cd /root/mix_project
./fastapi_manager.sh restart
```

### 2. 重新构建前端
```bash
cd /root/mix_project/liandong-intelligent-agent-master
npm run build
```

### 3. 测试流程
1. 打开前端页面
2. 在侧边栏点击一个产业链（如"氢能产业"）
3. 图谱显示后，点击"开始自动化处理（步骤2-10）"按钮
4. 观察进度条和处理日志

## API 端点

- `GET /api/pipeline/industries` - 获取产业链列表
- `GET /api/pipeline/industry/{name}/info` - 获取产业链信息
- `POST /api/pipeline/process` - 启动自动化处理（SSE流）

## 数据库表

确保以下表存在:
- `business_data.chain_needcomp` - 产业链节点表
- `business_data.whitelist_company` - 白名单表

## 添加新产业链

```sql
-- 1. 添加节点数据
INSERT INTO chain_needcomp (chain_name, nodes, parent_node, node_level)
VALUES ('新产业链', '节点名称', '父节点', 层级);

-- 2. 添加白名单（可选）
INSERT INTO whitelist_company (industry_name, position, company_name)
VALUES ('新产业链', '上游', '企业名称');
```

## 故障排查

1. **按钮不显示** - 检查浏览器控制台是否有JS错误
2. **API 调用失败** - 检查后端服务是否运行在端口8001
3. **产业链不存在** - 确保产业链名称存在于 `chain_needcomp` 表中
