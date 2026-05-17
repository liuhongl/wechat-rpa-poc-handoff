# 不依赖会话内容存档的企业微信桌面 Agent 方案设计

## 背景

目标场景：

```text
一个企业微信群里有微信客户，也有企业微信成员“小助手”。
客户在群里 @小助手 并提出问题。
系统自动理解问题，生成回复，并以小助手企业微信成员账号发回原群。
```

当前明确约束：

```text
[x] 后期目标是生产级无人值守
[x] 尽量不依赖会话内容存档
[x] 小助手本质上是一个企业微信成员账号
[x] 需要支持多个外部客户群
[x] 需要支持客户 @触发、去重、防错群
```

关键事实：

```text
[x] 企业微信公开 API 不提供“服务端以成员身份即时发送外部客户群普通消息”的稳定能力
[x] 已验证企业微信成员账号可以在外部客户群发送消息
[x] 已验证企业微信成员账号可以真正 @ 微信客户
[x] 已验证 Computer Use 可以读取部分企业微信 UI 并写入草稿
[!] AppleScript 读取企业微信窗口内容为空
[!] AppleScript 搜索定位群聊不稳定
```

因此，不依赖会话内容存档时，方案本质不是官方 API 方案，而是：

```text
专用企业微信客户端托管 + 桌面 Agent/RPA + 自建回复中控
```

## 目标

本设计要解决的问题：

```text
在不接会话内容存档的前提下，尽可能工程化地验证和逼近生产级无人值守自动回复。
```

更具体地说：

```text
1. 能从企业微信桌面客户端发现多个群里的 @小助手 消息
2. 能打开目标群并读取足够的最近上下文
3. 能判断是否应该回复，避免普通聊天误触发
4. 能生成可控回复
5. 能校验当前群和输入框，避免发错群
6. 能自动发送或按策略降级为草稿/人工确认
7. 能记录状态、告警、恢复，支撑长时间运行
```

## 非目标

本方案不承诺：

```text
[ ] 像会话内容存档 SDK 一样完整、稳定、实时地获取所有消息
[ ] 绕过企业微信客户端限制
[ ] 使用非官方协议或破解协议
[ ] 让 OpenClaw/QClaw 直接解决企业微信外部客户群读写问题
[ ] 一开始就支持大规模群和高并发
```

如果后续要求强 SLA、大量群、完整消息审计，仍应重新评估会话内容存档。

## 总体架构

```text
Dedicated WeCom Desktop
        |
        v
WeCom Desktop Adapter
  - 读取会话列表
  - 识别 [有人@我]
  - 打开目标群
  - 读取最近上下文
  - 写入/发送消息
  - 校验当前群和输入框
        |
        v
Reply Orchestrator
  - 群白名单
  - @触发规则
  - 去重
  - FAQ/AI 回复
  - 风险拦截
  - 发送策略
        |
        v
State & Observability
  - SQLite/JSONL 状态
  - 事件日志
  - 截图证据
  - 心跳
  - 告警
        |
        v
Operator Console
  - 待处理任务
  - 异常任务
  - 人工接管
  - 配置群白名单
```

## 核心模块

### WeCom Desktop Adapter

职责：

```text
1. 获取企业微信当前 UI 状态
2. 扫描会话列表中的 [有人@我]
3. 将会话预览转成标准事件
4. 打开指定群聊
5. 读取目标群最近消息上下文
6. 在发送前校验当前会话身份
7. 写入草稿或发送消息
```

标准输入：

```text
目标群名
客户昵称
回复内容
是否允许发送
```

标准输出：

```text
WeComEvent
WeComSendResult
WeComDesktopSnapshot
```

第一阶段不要把 OpenClaw/QClaw 放在这一层。原因是这一层是本项目最硬的风险点，需要先用可控、可测试、可记录的本地适配器验证。

### Reply Orchestrator

职责：

```text
1. 判断客户消息是否 @小助手
2. 合并同一客户近期上下文
3. 跳过小助手自己发出的消息
4. 按群白名单过滤
5. 调用 FAQ 或 AI 生成回复
6. 对高风险回复转人工
7. 生成发送任务
```

现有 POC 里的 `plan_multi_group_reply_jobs`、触发规则、去重逻辑可以继续复用。

### State & Observability

无人值守的关键不是“能跑一次”，而是“出问题能停、能报警、能恢复”。

至少需要记录：

```text
1. 原始 UI 快照
2. 解析出的 WeComEvent
3. 生成的回复任务
4. 发送前截图或 UI 状态
5. 发送结果
6. 已处理事件指纹
7. 异常原因
8. Agent 心跳
```

推荐最小实现：

```text
data/no_msgaudit_desktop_agent/events.jsonl
data/no_msgaudit_desktop_agent/actions.jsonl
data/no_msgaudit_desktop_agent/state.sqlite
data/no_msgaudit_desktop_agent/screenshots/
```

`data/` 继续不提交到仓库。

## 标准数据结构

### WeComEvent

```json
{
  "event_id": "ui:汽车贷款小助手:sky:需要经营证明吗@刘红利:2026-05-17T10:00",
  "source": "desktop_ui",
  "chat_name": "汽车贷款小助手",
  "sender_name": "sky",
  "content": "需要经营证明吗 @刘红利",
  "assistant_name": "刘红利",
  "detected_at": "2026-05-17T10:00:00+08:00",
  "confidence": 0.91,
  "raw_snapshot_ref": "data/no_msgaudit_desktop_agent/snapshots/..."
}
```

### ReplyJob

```json
{
  "job_id": "reply:ui:...",
  "event_id": "ui:...",
  "chat_name": "汽车贷款小助手",
  "sender_name": "sky",
  "question_content": "需要经营证明吗",
  "reply_content": "是否需要经营证明取决于具体产品和客户身份...",
  "handoff": false,
  "created_at": "2026-05-17T10:00:03+08:00"
}
```

### SendPlan

```json
{
  "job_id": "reply:ui:...",
  "chat_name": "汽车贷款小助手",
  "reply_content": "是否需要经营证明取决于具体产品和客户身份...",
  "mode": "draft",
  "requires_operator_confirm": true
}
```

### SendResult

```json
{
  "job_id": "reply:ui:...",
  "chat_name": "汽车贷款小助手",
  "status": "draft_written",
  "verified_chat_name": "汽车贷款小助手",
  "sent_at": null,
  "error": null
}
```

## 消息发现策略

不接会话内容存档时，消息发现只能来自企业微信客户端。

优先级：

```text
1. macOS/Windows 辅助功能树
2. 截图 + OCR
3. 企业微信通知
4. 会话列表轮询
```

当前已知：

```text
[x] Computer Use 可以读到部分企业微信 UI
[!] AppleScript 读取 accessible contents 为空
```

因此下一步应验证：

```text
1. 会话列表在真实运行时是否能被稳定读取
2. [有人@我] 是否总能出现在会话预览中
3. 群名和客户昵称被截断时如何处理
4. 打开群后能否读取最近 N 条消息
5. 企业微信窗口不在前台、锁屏、网络波动时会发生什么
```

## 触发规则

默认只回复：

```text
客户 @小助手 + 问题
```

支持：

```text
[x] “问题 + @小助手”
[x] “先发问题，下一条只 @小助手”
[x] 同一客户连续多条上下文合并
```

必须跳过：

```text
[x] 没有 @小助手 的普通群聊
[x] 小助手自己发出的消息
[x] 未配置群
[x] disabled 群
[x] 低置信度 OCR/GUI 解析结果
```

## 发送安全策略

发送前必须满足：

```text
1. 当前顶部群名等于 SendPlan.chat_name
2. 左侧选中会话等于 SendPlan.chat_name
3. 输入框为空，或当前草稿可被覆盖
4. 回复内容与 SendPlan.reply_content 一致
5. 当前任务未处理过
6. 发送模式允许 send，不只是 draft
```

生产尝试阶段建议分三档：

```text
draft_only：只写草稿，不发送
confirm_send：写草稿后等待人工确认
auto_send：校验全部通过后自动发送
```

默认从 `draft_only` 开始，连续验证稳定后再进入 `confirm_send`，最后才考虑 `auto_send`。

## 防错群机制

发错群是这个方案的最高风险。

必须使用多重校验：

```text
1. 群白名单校验
2. UI 顶部群名校验
3. 左侧选中会话校验
4. 发送前截图留证
5. 发送后状态记录
6. 异常时停止自动发送
```

如果任一校验失败：

```text
不发送
标记任务为 blocked
记录截图和原因
通知人工处理
```

## OpenClaw/QClaw 的位置

OpenClaw/QClaw 有帮助，但不应该放在第一阶段核心链路里。

适合的位置：

```text
Reply Orchestrator / Agent Runtime
```

可以带来的价值：

```text
1. 多 Agent 编排
2. 长期记忆
3. 工具调用
4. 定时任务
5. Dashboard
6. 审批和权限策略
7. 多渠道扩展
```

不能直接解决：

```text
1. 稳定读取企业微信外部客户群消息
2. 稳定定位企业微信群聊
3. 稳定以企业微信成员身份发消息
4. 防止发错群
```

推荐接入顺序：

```text
1. 先自建 WeCom Desktop Adapter
2. 定义 WeComEvent / ReplyJob / SendPlan / SendResult
3. 确认桌面 I/O 稳定性
4. 再做 OpenClaw/QClaw adapter spike
5. 用同一批 WeComEvent 对比自建 Orchestrator 与 OpenClaw/QClaw
```

## 生产化运行形态

建议使用专用设备：

```text
1. 专用 Mac mini、Windows 主机或云桌面
2. 只登录小助手企业微信账号
3. 固定屏幕分辨率和缩放比例
4. 禁止人工日常使用这台机器
5. 关闭无关通知和自动更新
6. 设置企业微信开机自启
7. Agent 以守护进程方式运行
```

需要监控：

```text
1. 企业微信是否在线
2. 企业微信窗口是否可见
3. Agent 是否心跳正常
4. 最近一次扫描时间
5. 最近一次成功发送时间
6. blocked/error 任务数量
7. OCR/GUI 置信度异常
```

## 阶段路线

### P0：文档和接口收敛

```text
[x] 明确不依赖会话存档的方案边界
[x] 定义 WeComEvent / SendPlan 等核心结构
[x] 把现有 GUI snapshot POC 对齐到这些结构
```

当前 P0 dry-run 命令：

```bash
.venv/bin/python scripts/no_msgaudit_desktop_agent_poc.py \
  --assistant-name "刘红利" \
  --ignore-state
```

这条命令只读取样例 GUI 快照并输出标准链路：

```text
wecom_event
reply_job
send_plan
```

默认 send plan 是 `draft` 模式，`send=false`，不会打开企业微信，也不会发送真实消息。

### P1：真实桌面 I/O 验证

```text
[x] 定义发送前校验模型
[x] 用快照文件模拟连续扫描并输出 heartbeat/preflight 日志
[ ] 从真实企业微信连续扫描会话列表，发现多个群的 [有人@我]
[ ] 打开目标群后读取最近上下文
[x] 从真实企业微信初步采集顶部群名、左侧选中会话、输入框内容
[x] 用桌面快照校验顶部群名和左侧选中会话
[ ] 只写草稿，不发送
```

当前 P1 校验模型仍是 dry-run。可以用手工构造的桌面快照 JSON 验证防错群判断：

```json
{
  "current_chat_name": "汽车贷款小助手",
  "selected_chat_name": "汽车贷款小助手",
  "input_text": "",
  "app_online": true,
  "window_visible": true,
  "captured_at": "2026-05-17T10:00:00+08:00"
}
```

运行：

```bash
.venv/bin/python scripts/no_msgaudit_desktop_agent_poc.py \
  --assistant-name "刘红利" \
  --ignore-state \
  --desktop-snapshot-json /tmp/wecom_desktop_snapshot.json
```

输出会额外包含：

```text
send_preflight
```

其中：

```text
ok=true 表示当前桌面快照满足写草稿/发送前校验
status=ready_to_draft 表示只能安全写草稿
status=ready_to_send 表示 auto_send 模式下校验通过
status=blocked 表示必须停止，不能写入或发送
```

注意：这一步还没有从真实企业微信自动采集桌面快照，只是把“是否允许写草稿/发送”的判断模型先固定下来。

2026-05-17 使用 Computer Use 对真实企业微信窗口做了一次只读验证，accessibility tree 中可以看到：

```text
顶部当前群名：汽车金融VIP群
左侧选中会话：汽车金融VIP群
输入框元素：文本输入区 (settable, string)，当前为空
```

这说明真实 UI 树里存在构造 `WeComDesktopSnapshot` 所需字段。当前已支持从 Computer Use 风格的 accessibility tree 文本生成快照：

```bash
.venv/bin/python scripts/no_msgaudit_desktop_agent_poc.py \
  --assistant-name "刘红利" \
  --ignore-state \
  --desktop-accessibility-tree-text-file /tmp/wecom_accessibility_tree.txt
```

注意：这仍然只是“单次 UI 树可解析”，不是“连续监听稳定”。后续还必须验证窗口切换、滚动、锁屏、网络波动、企业微信 UI 更新后的稳定性。

当前已新增连续扫描 dry-run 脚本：

```bash
.venv/bin/python scripts/no_msgaudit_desktop_scan_poc.py \
  --assistant-name "刘红利" \
  --ignore-state \
  --desktop-accessibility-tree-text-file /tmp/wecom_accessibility_tree_1.txt \
  --desktop-accessibility-tree-text-file /tmp/wecom_accessibility_tree_2.txt \
  --iterations 2 \
  --interval-seconds 0 \
  --out /tmp/no_msgaudit_desktop_scan_log.jsonl
```

输出包含：

```text
scan_heartbeat
desktop_snapshot
send_preflight
```

这一步验证的是“多轮快照 -> 多轮安全判断 -> JSONL 日志”的运行框架。它还没有自动从企业微信实时抓取 UI 树，后续需要把 Computer Use/OCR/其它桌面采集器接入为真实 snapshot source。

### P2：半自动闭环

```text
[ ] 生成回复
[ ] 写入草稿
[ ] 人工确认发送
[ ] 记录结果和去重状态
```

### P3：受控自动发送

```text
[ ] 连续运行 24 小时
[ ] 错群次数为 0
[ ] 重复回复次数为 0
[ ] 卡死后能自动恢复或报警
[ ] 低置信度任务自动转人工
```

### P4：OpenClaw/QClaw 接入评估

```text
[ ] 把 WeComEvent 接入 OpenClaw/QClaw adapter
[ ] 比较任务编排、记忆、日志、审批能力
[ ] 判断是否替换自建 Orchestrator
```

## 成功标准

进入生产试运行前，至少满足：

```text
[ ] 专用设备连续运行 24 小时
[ ] 能处理至少 3 个外部客户群
[ ] 能稳定识别 @小助手
[ ] 能读取足够上下文
[ ] 能写入正确群草稿
[ ] 自动发送前全部校验可记录
[ ] 没有发错群
[ ] 没有重复回复
[ ] 异常时会停机或报警，而不是继续误发
```

## 当前建议

下一步不要先接 OpenClaw/QClaw。

先做：

```text
WeCom Desktop Adapter POC
```

具体目标：

```text
1. 加入发送前校验模型
2. 跑一个只写草稿的 1 小时守护进程验证
3. 验证真实企业微信 UI 快照能否持续抽象成 WeComEvent
4. 验证异常时能停止并记录证据
```

如果 1 小时守护进程能稳定，再扩展到 24 小时；如果 24 小时仍稳定，再评估 OpenClaw/QClaw 是否值得引入。
