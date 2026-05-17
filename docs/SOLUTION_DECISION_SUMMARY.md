# 企业微信外部群自动回复方案决策总结

## 目标

验证“刘红利作为企业微信成员小助手账号，加入多个外部客户群后，客户在任意群里 @刘红利，系统自动生成回复并回到对应群”的可行性。

当前目标是验证方案是否成立，不是直接交付生产级无人值守系统。

## 当前结论

如果允许使用会话内容存档，最适合本场景的最终路线是：

```text
会话内容存档 SDK 负责读消息
自建多群自动回复服务负责判断、去重、AI/FAQ 和路由
企业微信客户端自动化负责以刘红利账号发回对应群
```

如果明确不依赖会话内容存档，则当前路线调整为：

```text
专用企业微信客户端托管
WeCom Desktop Adapter 负责读取 UI、识别 @、定位群、写入/发送
自建 Reply Orchestrator 负责判断、去重、AI/FAQ 和路由
State & Observability 负责状态、截图、心跳、告警
```

这不是官方 API 级生产方案，而是工程化 RPA 生产尝试方案。它的核心风险是企业微信桌面 UI 稳定性和防错群。

在正式进入生产尝试前，当前替代验证路线是：

```text
GUI/Computer Use/OCR 获取企业微信会话列表快照
解析 [有人@我] 的多群会话预览
生成多群回复任务
生成对应群的桌面发送计划
人工确认或半自动发送
```

## 已验证事实

```text
[x] 企业微信成员刘红利在外部客户群中可以发送普通文本
[x] 企业微信成员刘红利可以真正 @ 微信客户 sky
[x] Computer Use 可以读取企业微信真实 UI，并识别 [有人@我]
[x] Computer Use 可以把回复写入正确群输入框
[x] 多群模拟消息可以生成对应群 reply jobs
[x] GUI 会话列表快照可以生成多群 reply jobs
[x] reply jobs 可以转换成桌面发送计划
[x] msgid/source_msgid 去重逻辑已具备
```

## 已发现限制

```text
[!] AppleScript 可以获得辅助功能权限，但读取企业微信窗口内容为空
[!] AppleScript 搜索定位群聊不稳定，不能作为可靠无人值守发送通道
[!] 不接会话内容存档时，监听依赖 GUI 快照，不适合大量群长期无人值守
[!] 企业微信公开 API 没有“服务端以成员身份即时发送外部客户群普通消息”的能力
```

## OpenClaw 的位置

OpenClaw 可以作为 Agent 编排和多群路由思想参考，但它不是企业微信外部客户群的现成消息源，也不能替代企业微信桌面读写适配层。

如果使用会话内容存档，更合理的位置是：

```text
会话内容存档 SDK
-> 自定义 wecom-msgaudit channel
-> OpenClaw 做群会话、mention gating、Agent 路由
-> 企业微信客户端自动化发送
```

如果不使用会话内容存档，更合理的位置是：

```text
WeCom Desktop Adapter
-> WeComEvent
-> OpenClaw/QClaw 或自建 Reply Orchestrator 做 Agent 编排
-> SendPlan
-> WeCom Desktop Adapter 执行发送
```

当前阶段不建议先引入 OpenClaw/QClaw。应先把企业微信桌面 I/O 适配层验证稳定，再评估是否把 Agent 编排层换成 OpenClaw/QClaw。

## 当前 POC 链路

### 会话内容存档模拟链路

```bash
.venv/bin/python scripts/multi_group_reply_planner_poc.py \
  --assistant-name "刘红利" \
  --ignore-state \
  --out /tmp/multi_group_reply_jobs.jsonl
```

验证点：

```text
多个 roomid
只处理启用群
只处理 @刘红利
跳过禁用群、未知群、非文本消息
生成对应 chat_name 的 reply job
```

### 无会话内容存档 GUI 快照链路

```bash
.venv/bin/python scripts/gui_snapshot_reply_planner_poc.py \
  --assistant-name "刘红利" \
  --ignore-state \
  --out /tmp/gui_snapshot_reply_jobs.jsonl
```

验证点：

```text
从企业微信会话列表快照解析 [有人@我]
按 group allowlist 过滤群
生成多群 reply job
```

### 发送计划 dry-run

```bash
.venv/bin/python scripts/multi_group_desktop_sender_poc.py \
  --reply-jobs-jsonl /tmp/gui_snapshot_reply_jobs.jsonl \
  --max-jobs 10 \
  --include-applescript \
  --out /tmp/gui_snapshot_desktop_send_plans.jsonl
```

验证点：

```text
每条 reply job 都能生成对应 chat_name 的发送计划
默认不操作企业微信
--run 才写入草稿
--send 才发送
```

## 分支策略

当前不需要创建新分支。

原因：

```text
当前分支 poc/member-assistant-rpa 本身就是成员型小助手 RPA 验证线
最新无存档 GUI 快照方案是这条验证线的自然补充
没有出现两个需要并行维护的互斥实现
```

建议继续在当前分支推进：

```text
poc/member-assistant-rpa
```

只有出现以下情况时再创建新分支：

```text
1. 接真实会话内容存档 SDK：
   poc/msgaudit-ingestion

2. 尝试 OpenClaw 自定义 channel：
   poc/openclaw-wecom-channel

3. 尝试替换发送自动化引擎：
   poc/desktop-automation-engine

4. 不依赖会话内容存档的桌面 Agent 生产尝试：
   poc/no-msgaudit-desktop-agent
```

## 下一步建议

先不要开新分支。下一步应该继续验证当前方案最关键的剩余问题：

```text
1. 多群 GUI 快照能否从真实企业微信界面稳定采集
2. 目标群打开后，是否能用 Computer Use 校验顶部群名
3. 草稿写入前后是否能校验输入框内容
4. 是否可以形成“默认草稿、人工确认发送”的半自动闭环
```

完成这些后，再决定是否进入真实会话内容存档 SDK 分支。

无会话内容存档阶段的具体操作步骤见：

```text
docs/NO_MSGAUDIT_GUI_RPA_RUNBOOK.md
```

不依赖会话内容存档的桌面 Agent 生产尝试设计见：

```text
docs/NO_MSGAUDIT_DESKTOP_AGENT_DESIGN.md
```
