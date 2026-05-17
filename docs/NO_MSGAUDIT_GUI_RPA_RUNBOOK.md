# 无会话内容存档 GUI/RPA 验证 Runbook

## 结论边界

当前 Runbook 只验证一个问题：

```text
不接会话内容存档时，能否通过企业微信客户端 GUI 快照发现 [有人@我]，
再生成回复任务，并把回复草稿写到正确外部客户群。
```

它不验证生产级无人值守监听。原因很直接：GUI 只能看到当前客户端界面暴露的信息，不能像会话内容存档一样稳定拿到完整消息流。

因此当前阶段的目标是：

```text
[x] 验证多群任务规划是否成立
[x] 验证发送计划是否能映射到正确群
[x] 验证 Computer Use 人机协同是否能把草稿写进正确群
[ ] 不承诺大量群长期无人值守
[ ] 不使用 AppleScript 作为可靠自动定位发送通道
```

## 分支策略

继续使用当前分支：

```text
poc/no-msgaudit-desktop-agent
```

暂时不需要创建新分支。当前改动仍属于“无会话内容存档桌面 Agent POC”验证线。

只有进入以下独立方向时再开新分支：

```text
接真实会话内容存档 SDK：poc/msgaudit-ingestion
接 OpenClaw 自定义 channel：poc/openclaw-wecom-channel
替换发送自动化引擎：poc/desktop-automation-engine
```

## 验证链路

```text
企业微信左侧会话列表 GUI 快照
-> 解析 [有人@我] 会话预览
-> 按群 allowlist 过滤
-> 生成 reply jobs
-> 生成 desktop send plans
-> 人工校验目标群
-> Computer Use 写入草稿
-> 人工确认后才发送
```

## 目标群配置

目标群白名单在：

```text
tests/fixtures/multi_group_targets.json
```

验证前必须确认：

```text
[ ] 只包含允许自动回复的群
[ ] chat_name 与企业微信群名完全一致
[ ] enabled=true 的群才会生成任务
[ ] 暂停群必须设置 enabled=false
```

当前样例会处理：

```text
汽车贷款小助手
汽车金融VIP群
```

## 第 1 步：生成 GUI 快照回复任务

使用固定样例快照 dry-run：

```bash
.venv/bin/python scripts/gui_snapshot_reply_planner_poc.py \
  --assistant-name "刘红利" \
  --ignore-state \
  --out /tmp/gui_snapshot_reply_jobs.jsonl
```

预期输出：

```text
汽车贷款小助手 / sky / 需要经营证明吗
汽车金融VIP群 / kay / 贷款利率是多少
```

必须跳过：

```text
[x] 暂停自动回复群
[x] 未配置群
[x] 没有 [有人@我] 的普通会话
```

审核 `/tmp/gui_snapshot_reply_jobs.jsonl` 时重点看：

```text
[ ] chat_name 是否是目标群
[ ] sender_name 是否是客户
[ ] question_content 是否是客户真实问题
[ ] reply_content 是否可以直接展示给客户
[ ] source_msgid 是否能用于去重
```

## 第 2 步：生成桌面发送计划

只生成计划，不操作企业微信：

```bash
.venv/bin/python scripts/multi_group_desktop_sender_poc.py \
  --reply-jobs-jsonl /tmp/gui_snapshot_reply_jobs.jsonl \
  --max-jobs 10 \
  --include-applescript \
  --out /tmp/gui_snapshot_desktop_send_plans.jsonl
```

必须确认：

```text
[ ] will_run=false
[ ] send=false
[ ] 每条 plan 的 chat_name 正确
[ ] reply_content 与 reply job 一致
[ ] 没有多余群被生成发送计划
```

这一步不应该打开企业微信，也不应该修改任何聊天输入框。

## 第 3 步：真实桌面草稿验证

真实桌面动作只验证 1 条任务，先不要批量跑。

安全规则：

```text
[ ] 默认只写草稿，不发送
[ ] 发送前必须由人明确确认
[ ] 不使用 AppleScript 批量定位群聊
[ ] 不在输入框已有内容时继续写入
[ ] 群名无法校验时立即停止
```

人工或 Computer Use 打开目标群后，必须逐项校验：

```text
[ ] 企业微信顶部当前群名等于 plan.chat_name
[ ] 左侧选中会话等于 plan.chat_name
[ ] 输入框为空，或当前草稿确实可被覆盖
[ ] 本次要写入的 reply_content 与计划一致
[ ] 当前动作只针对一条 source_msgid
```

校验通过后，只把回复写入输入框，不发送。

通过标准：

```text
[x] 草稿出现在正确群的输入框
[x] 草稿内容与 plan.reply_content 一致
[x] 未误切到其他群
[x] 未自动发送
```

失败标准：

```text
[!] 找不到目标群
[!] 当前顶部群名与 plan.chat_name 不一致
[!] 输入框已有不可覆盖内容
[!] 自动化定位到错误页面或错误群
[!] 无法确认当前会话身份
```

失败时不要发送，清空草稿并记录原因。

## 第 4 步：去重验证

如果本次任务已经确认处理，可以写入本地去重状态：

```bash
.venv/bin/python scripts/gui_snapshot_reply_planner_poc.py \
  --assistant-name "刘红利" \
  --mark-planned
```

再次运行规划命令，预期不再生成同一批任务：

```bash
.venv/bin/python scripts/gui_snapshot_reply_planner_poc.py \
  --assistant-name "刘红利"
```

通过标准：

```text
[x] 已处理 source_msgid 不重复生成
[x] 新的 [有人@我] 快照仍可生成新任务
```

## 第 5 步：真实快照采集验证

当需要从真实企业微信界面验证时，先让目标客户在目标群里发：

```text
需要经营证明吗 @刘红利
```

然后通过 Computer Use 或 OCR 读取企业微信左侧会话列表，确认能看到类似：

```text
汽车贷款小助手 [有人@我] sky: 需要经营证明吗 @刘红利
```

这一步只证明 GUI 层能捕捉到当前可见快照，不证明能监听全部历史消息。

如果使用 Swift AX 快照目录验证当前可见消息区事件提取：

```bash
.venv/bin/python scripts/no_msgaudit_desktop_scan_poc.py \
  --assistant-name "刘红利" \
  --ignore-state \
  --desktop-accessibility-tree-dir data/no_msgaudit_desktop_agent/accessibility_snapshots \
  --follow-snapshot-dir \
  --events-from-accessibility-tree \
  --snapshot-cursor-file data/no_msgaudit_desktop_agent/snapshot_cursor.json \
  --iterations 10 \
  --interval-seconds 2 \
  --out data/no_msgaudit_desktop_agent/desktop_scan_log.jsonl
```

通过标准：

```text
[x] 有客户 @刘红利 且消息在当前可见消息区时，输出 wecom_event/reply_job/send_plan
[x] 当前可见消息区没有客户 @刘红利 时，send_plan_count=0
[x] 不把群名、成员列表、系统消息误判成客户问题
[x] 同一条可见消息连续出现多轮时，本次扫描进程内只生成一次计划
[x] follow 模式必须显式配合 --events-from-accessibility-tree，避免默认样例事件混入真实验证
[x] follow 模式只消费新快照，目录暂无新快照时输出 idle heartbeat
[x] 设置 --snapshot-cursor-file 后，扫描器重启不会重复消费同一份旧快照
[x] 扫描器进程仍在运行时，`--out` JSONL 已经能看到最新输出
```

注意：

```text
[!] 这是进程内去重，防止同一条可见消息在多轮扫描里重复规划
[!] 这不是最终发送状态持久化；真实持久去重应在写草稿或发送成功后记录
[!] follow 模式解决的是 snapshot spool 消费，不等于完整消息流监听
[!] `--out` 是运行证据日志，不是“消息已成功回复”的业务状态
[!] snapshot cursor 只表示“快照已消费”，不表示“客户消息已回复”
```

扫描日志健康检查：

```bash
.venv/bin/python scripts/no_msgaudit_scan_health_poc.py \
  --log-jsonl data/no_msgaudit_desktop_agent/desktop_scan_log.jsonl \
  --max-heartbeat-age-seconds 60
```

通过标准：

```text
[x] ok=true
[x] last_heartbeat_age_seconds 未超过阈值
[x] failures=[]
```

通过标准：

```text
[x] 左侧会话列表能看到 [有人@我]
[x] 能提取群名、客户昵称、问题文本
[x] 能进入第 1 步生成 reply job
```

失败时需要判断是：

```text
[ ] 企业微信 UI 不展示 [有人@我]
[ ] 会话列表当前不可见
[ ] OCR/GUI 读取失败
[ ] 群名或客户昵称被截断
[ ] 客户消息不是 @刘红利 触发
```

## 发送权限规则

涉及真实企业微信发消息时，默认规则是：

```text
生成计划：可以自动执行
写入草稿：只在明确验证时执行
真正发送：必须由人明确说“发送”
批量发送：当前 POC 禁止
```

这条规则的目的不是保守，而是因为当前已实测：

```text
[!] AppleScript 读取企业微信 UI 内容为空
[!] AppleScript 搜索定位群聊不稳定
[x] Computer Use 可以人机协同定位并写入草稿
```

所以现阶段最可靠的验证方式是：

```text
程序负责生成任务和内容
人或 Computer Use 负责校验当前群
只写草稿
人工确认后发送
```

## 验证记录模板

每次真实验证后记录：

```text
日期：
企业微信账号：
目标群：
客户昵称：
客户原始消息：
是否出现 [有人@我]：
是否生成 reply job：
reply_content：
是否生成 send plan：
是否写入草稿：
是否发送：
是否发错群：
异常现象：
截图或备注：
```

## 最终判断标准

可以继续推进的信号：

```text
[x] 多群 GUI 快照可以稳定生成 reply jobs
[x] Computer Use 可以稳定校验目标群并写草稿
[x] 去重逻辑可以避免重复回复
[x] 人工确认发送流程能闭环
```

必须暂停并切换方案的信号：

```text
[!] GUI 快照无法稳定采集 [有人@我]
[!] 群名无法可靠识别或存在重名
[!] 自动化经常定位错群
[!] 需要大量群长期无人值守
```

一旦出现最后一类需求，就应该暂停 GUI 快照路线，优先接入会话内容存档 SDK。
