# 前端集成说明

## 修改内容

在 `ChatContainer.vue` 中添加了"开始自动化处理"按钮和相关功能。

## 修改位置

**文件**: `/root/mix_project/liandong-intelligent-agent-master/src/components/ChatContainer.vue`

### 1. 模板修改 (约第226-280行)

在产业链图谱显示区域下方添加了：
- "开始自动化处理（步骤2-10）"按钮
- 处理状态显示（进度条、当前步骤）
- 可展开的处理消息日志

### 2. 方法修改 (约第2500-2630行)

添加了两个新方法：
- `startPipelineProcessing(industryName, task)` - 启动自动化处理
- `togglePipelineMessages(task)` - 切换消息显示

### 3. 样式修改 (约第2680-2760行)

添加了以下样式：
- `.pipeline-action-container` - 按钮容器样式
- `.pipeline-status` - 状态显示样式
- `.pipeline-messages` - 消息列表样式

## 使用流程

1. 用户在前端输入产业链名称（如"氢能产业"）
2. 系统生成产业链图谱
3. 图谱生成完成后，在图谱下方显示"开始自动化处理（步骤2-10）"按钮
4. 点击按钮后：
   - 按钮变为加载状态
   - 显示当前处理步骤和进度条
   - 显示详细的消息日志
5. 处理完成后显示"自动化处理已完成"

## API 端点

后端使用 `/api/pipeline/process` 端点（SSE 流）

## 测试方法

```bash
# 1. 重启前端服务（如果需要）
cd /root/mix_project/liandong-intelligent-agent-master
npm run serve

# 2. 在浏览器中访问
# 输入产业链名称，等待图谱生成完成
# 点击"开始自动化处理"按钮
```

## 注意事项

1. 确保后端服务正在运行（端口8001）
2. 确保用户已登录（需要 access_token）
3. 产业链名称必须存在于 `chain_needcomp` 表中
