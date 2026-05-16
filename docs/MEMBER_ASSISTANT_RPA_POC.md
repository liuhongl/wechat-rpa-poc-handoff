# 企业微信成员型小助理 RPA POC

## 目标

验证“真实企业微信成员账号作为小助理”是否能在外部客户群里形成自动回复闭环。

完整闭环分成三件事：

```text
会话内容存档读取外部客户群消息
企业微信客户端定位外部客户群并发送文本
企业微信客户端能否真正 @ 某个微信客户
```

这条路线不是纯官方服务端 API。官方 API 负责读取和管理，最后“以成员身份发消息”依赖企业微信桌面客户端自动化。

## 关键结论

1. AI 生成回复不是难点。
2. 难点是外部客户群没有开放“程序直接以成员身份发消息”的官方服务端接口。
3. 因此本 POC 的核心是验证桌面客户端自动化是否足够稳定。

## 当前实测结果

截至 2026-05-15，成员型小助理 RPA 线已完成两项真实客户端验证：

```text
[x] 企业微信客户端可以定位目标外部客户群
[x] 自动化可以把 AI/FAQ 生成的文本写入输入框
[x] 文本发送后，群内可见企业微信成员发出的消息
[x] 自动化可以插入微信客户 @ 对象
[x] 发送后，微信客户侧确认同时收到普通消息和 @我提醒
```

当前尚未接入真实会话内容存档 SDK，读取链路仍使用模拟明文数据验证解析和回复计划。

本机补充发现：AppleScript/System Events 路线会受 macOS 辅助功能权限影响；在本次验证中，Computer Use 可以直接定位企业微信输入框并写入内容。

## 前置条件

### 会话内容存档

企业微信后台需要开通会话内容存档，并准备：

```ini
WECOM_CORP_ID=
WECOM_MSGAUDIT_SECRET=
WECOM_MSGAUDIT_PRIVATE_KEY_PATH=
WECOM_MSGAUDIT_SDK_LIB_PATH=
WECOM_MSGAUDIT_TARGET_ROOMID=
```

`WECOM_MSGAUDIT_SDK_LIB_PATH` 通常指向企业微信会话内容存档 SDK 里的动态库，例如 macOS 下的 `libWeWorkFinanceSdk_C.dylib`。

私钥文件不要提交到仓库。

### 桌面自动化

当前脚本使用 macOS AppleScript/System Events，需要：

1. Mac 已登录企业微信客户端。
2. “小助理”企业微信成员账号已在目标外部客户群内。
3. 系统设置允许终端或 Codex 控制电脑：`系统设置 -> 隐私与安全性 -> 辅助功能`。
4. `.env` 里配置目标群名和待 @ 的微信客户昵称：

```ini
WECOM_DESKTOP_APP_NAME=企业微信
WECOM_DESKTOP_TARGET_CHAT_NAME=目标外部客户群名称
WECOM_DESKTOP_AT_MEMBER_NAME=微信客户在群里的昵称
WECOM_ASSISTANT_NAME=小助理成员在群里被 @ 的名称，例如刘红利
```

运行前可以先做一次无副作用体检：

```bash
.venv/bin/python scripts/wecom_desktop_preflight_poc.py \
  --chat-name "目标外部客户群名称"
```

这个命令只输出 JSON 报告，不打开企业微信、不搜索群、不输入文字、不发送消息。重点看：

```text
ok: 是否满足基本配置
osascript_available: AppleScript 是否可用
app_exists: Spotlight 是否能找到企业微信应用
missing: 缺失项
warnings: 风险提示
```

如果 `app_exists` 是 `false`，先确认本机是否安装企业微信，以及应用名称是否为 `企业微信` 或 `WeCom`。

## 验证 1：会话内容存档能否读到群消息

先用样例明文 JSON 验证解析逻辑：

```bash
.venv/bin/python scripts/msgaudit_reader_poc.py \
  --sample-plaintext-json tests/fixtures/msgaudit_plaintext_messages.json \
  --target-roomid wr_sample_target_room
```

这一步不需要开通会话内容存档，模拟的是 SDK 解密后的明文消息结构。它可以先验证：

```text
[ ] 只读取目标 roomid 的消息
[ ] 只输出文本消息
[ ] 其他群和图片消息会被忽略
```

真实 SDK 拉取：

```bash
.venv/bin/python scripts/msgaudit_reader_poc.py \
  --seq 0 \
  --limit 100 \
  --target-roomid "$WECOM_MSGAUDIT_TARGET_ROOMID"
```

成功标准：

```text
[ ] 客户在目标外部客户群发消息后，脚本能读到记录
[ ] 输出包含 seq/msgid/from/roomid/content
[ ] roomid 是目标客户群
[ ] 重复运行不会把其他群消息误判为目标群消息
```

输出会追加到：

```text
data/member_assistant_poc/msgaudit_records.jsonl
```

`data/` 已被 `.gitignore` 忽略。

## 模拟自动回复动作计划

在接真实 SDK 前，可以先从模拟会话存档生成“将要回复什么”的动作计划：

```bash
.venv/bin/python scripts/member_assistant_reply_planner_poc.py \
  --sample-plaintext-json tests/fixtures/msgaudit_plaintext_messages.json \
  --target-roomid wr_sample_target_room \
  --chat-name "模拟外部客户群"
```

回复规划脚本优先使用 `--assistant-name`，其次使用 `.env` 里的 `WECOM_ASSISTANT_NAME`，都没有时才回退到 `小助理`。默认只处理明确 @ 小助理名称的消息，避免普通群聊内容被误回复。如果当前小助理就是企业微信成员本人，例如 `刘红利`，需要配置 `WECOM_ASSISTANT_NAME=刘红利`，或者命令行显式加 `--assistant-name "刘红利"`。输出会写入：

```text
data/member_assistant_poc/reply_actions.jsonl
```

如果要验证“非 @ 消息也可进入回复计划”，可以加：

```bash
.venv/bin/python scripts/member_assistant_reply_planner_poc.py \
  --sample-plaintext-json tests/fixtures/msgaudit_plaintext_messages.json \
  --target-roomid wr_sample_target_room \
  --chat-name "模拟外部客户群" \
  --include-non-mentions
```

如果要同时输出即将交给桌面自动化的 AppleScript：

```bash
.venv/bin/python scripts/member_assistant_reply_planner_poc.py \
  --include-applescript
```

成功标准：

```text
[ ] 目标群文本消息被转换为回复动作
[ ] 默认只响应 @小助理 的消息
[ ] FAQ 命中时输出业务回复
[ ] 未命中 FAQ 时输出转人工草案
[ ] 生成的 AppleScript 默认不包含真正发送动作
```

## 模拟端到端自动回复干跑

端到端脚本会把上面的步骤串起来：

```text
模拟会话存档明文 -> 过滤目标 roomid -> 跳过已处理 msgid -> 生成回复 -> 可选调用桌面客户端
```

默认只打印动作计划，不操作企业微信：

```bash
.venv/bin/python scripts/member_assistant_desktop_auto_reply_poc.py \
  --sample-plaintext-json tests/fixtures/msgaudit_plaintext_messages.json \
  --target-roomid wr_sample_target_room \
  --chat-name "模拟外部客户群"
```

默认每次最多处理 1 条动作，避免误触发批量回复。要多处理可显式指定：

```bash
.venv/bin/python scripts/member_assistant_desktop_auto_reply_poc.py \
  --max-actions 3
```

运行 AppleScript 但不发送，只把回复输入到企业微信聊天框：

```bash
.venv/bin/python scripts/member_assistant_desktop_auto_reply_poc.py \
  --chat-name "目标外部客户群名称" \
  --run
```

真正发送需要显式加 `--send`：

```bash
.venv/bin/python scripts/member_assistant_desktop_auto_reply_poc.py \
  --chat-name "目标外部客户群名称" \
  --send
```

`--send` 会在成功执行后把消息标记为已处理，状态文件在：

```text
data/member_assistant_poc/processed_msgids.json
```

如果要忽略状态重新模拟：

```bash
.venv/bin/python scripts/member_assistant_desktop_auto_reply_poc.py \
  --ignore-state
```

成功标准：

```text
[ ] 默认不打开或操作企业微信
[ ] 默认只计划 1 条回复动作
[ ] 重复发送时能通过 processed_msgids 跳过已处理消息
[ ] --run 只输入不发送
[ ] --send 才真正发送并标记已处理
```

## 无 SDK 客户端自动回复 POC

这条链路不接会话内容存档 SDK，而是从企业微信桌面端 UI 里读取会话列表的 `[有人@我]` 提示，提取类似下面的行：

```text
汽车贷款小助手 [有人@我] sky: 需要经营证明吗 @刘红利
```

先用固定 UI 文本 dry-run 验证，不读取企业微信、不发送：

```bash
.venv/bin/python scripts/wecom_live_auto_reply_poc.py \
  --ui-text-file tests/fixtures/wecom_ui_live_mentions.txt \
  --chat-name "汽车贷款小助手" \
  --assistant-name "刘红利" \
  --ignore-state \
  --out /tmp/live_ui_reply_actions.jsonl
```

成功时会输出一条回复动作，`sender` 为 `sky`，`question_content` 为 `需要经营证明吗`。

读取真实企业微信 UI 但不输入、不发送：

```bash
.venv/bin/python scripts/wecom_live_auto_reply_poc.py \
  --chat-name "汽车贷款小助手" \
  --assistant-name "刘红利"
```

运行并把回复写入目标群输入框，但不发送：

```bash
.venv/bin/python scripts/wecom_live_auto_reply_poc.py \
  --chat-name "汽车贷款小助手" \
  --assistant-name "刘红利" \
  --run
```

真正发送必须显式加 `--send`：

```bash
.venv/bin/python scripts/wecom_live_auto_reply_poc.py \
  --chat-name "汽车贷款小助手" \
  --assistant-name "刘红利" \
  --send
```

如果实际发送是人工或 Computer Use 确认完成的，可以只把这批计划动作标记为已处理，避免下一轮重复回复：

```bash
.venv/bin/python scripts/wecom_live_auto_reply_poc.py \
  --ui-text-file tests/fixtures/wecom_ui_live_mentions.txt \
  --chat-name "汽车贷款小助手" \
  --assistant-name "刘红利" \
  --mark-planned
```

注意：这只是无 SDK 的客户端 RPA POC。它依赖 macOS 辅助功能权限和企业微信 UI 结构，只能读取当前 UI 暴露出的会话列表预览，不等价于完整消息流。生产方案仍建议最终接会话内容存档 SDK。

截至 2026-05-15 的本机实测结果：

```text
[x] Computer Use 能读取企业微信真实 UI，并识别 [有人@我] 会话预览
[x] Computer Use 能把回复写入输入框并发送
[x] osascript 加入 macOS 辅助功能后，不再报权限错误
[!] 企业微信窗口对 AppleScript 暴露的 accessible contents 为空，脚本无法直接读取聊天列表文本
```

因此，无 SDK 自动回复目前可验证到“Computer Use 驱动的半自动闭环”；如果要做稳定无人值守，仍需要接会话内容存档 SDK 或换成能稳定读取企业微信客户端 UI 的自动化层。

## 验证 2：客户端能否定位群并发送文本

只打印 AppleScript，不操作客户端：

```bash
.venv/bin/python scripts/wecom_desktop_send_poc.py \
  --chat-name "目标外部客户群名称" \
  --message "POC测试：只打印脚本" \
  --print-script
```

运行但不发送，只把内容输入到聊天框：

```bash
.venv/bin/python scripts/wecom_desktop_send_poc.py \
  --chat-name "目标外部客户群名称" \
  --message "POC测试：只输入不发送" \
  --run
```

真正发送：

```bash
.venv/bin/python scripts/wecom_desktop_send_poc.py \
  --chat-name "目标外部客户群名称" \
  --message "POC测试：企业微信客户端自动化发送文本" \
  --run \
  --send
```

成功标准：

```text
[ ] 企业微信客户端被激活
[ ] 能通过搜索打开目标外部客户群
[ ] dry-run 时只输入不发送
[ ] --send 时群内能看到小助理成员发出的文本
[ ] 连续 3 次成功定位同一个群
```

## 验证 3：能否真正 @ 微信客户

只打印脚本：

```bash
.venv/bin/python scripts/wecom_at_member_poc.py \
  --chat-name "目标外部客户群名称" \
  --member-name "11" \
  --message "账单还有3天到期，请确认。" \
  --print-script
```

运行但不发送：

```bash
.venv/bin/python scripts/wecom_at_member_poc.py \
  --chat-name "目标外部客户群名称" \
  --member-name "11" \
  --message "账单还有3天到期，请确认。" \
  --run
```

真正发送：

```bash
.venv/bin/python scripts/wecom_at_member_poc.py \
  --chat-name "目标外部客户群名称" \
  --member-name "11" \
  --message "账单还有3天到期，请确认。" \
  --run \
  --send
```

成功标准：

```text
[ ] 输入 @昵称 后出现候选人
[ ] 脚本按回车能选中正确微信客户
[ ] 发送后群内显示为真正 @，不是普通文本
[ ] 微信客户侧收到被 @ 提醒
```

如果候选人选择不稳定，需要改成半自动流程：脚本只输入 `@昵称` 并停住，由人工确认候选后再发送。

## 验证 4：触发规则是否可控

触发规则先用模拟会话存档验证，不操作企业微信：

```bash
.venv/bin/python scripts/member_assistant_reply_planner_poc.py \
  --sample-plaintext-json tests/fixtures/trigger_rule_messages.json \
  --target-roomid wr_sample_target_room \
  --assistant-sender-id wm_sample_assistant \
  --out /tmp/trigger_rule_actions.jsonl
```

当前规则：

```text
[x] 客户 @小助理 + 问题 -> 生成回复
[x] 客户没 @小助理 -> 默认不回复
[x] 小助理成员自己发出的消息 -> 跳过，避免自循环
[x] 客户先发问题，下一条只 @小助理 -> 追溯同一客户近期问题
[x] 同一客户连续多条消息后再 @小助理 -> 合并近期上下文
```

输出里的 `question_content` 是真正交给 FAQ/AI 判断的问题文本。比如客户先发“需要经营证明吗”，下一条只发 `@小助理`，输出仍会把 `question_content` 解析为“需要经营证明吗”。

生产接真实会话存档后，需要把小助理成员在会话存档中的发送者 ID 配到：

```ini
WECOM_ASSISTANT_SENDER_ID=小助理成员的发送者ID
```

## 验证 4.1：多群自动回复方案是否成立

当前阶段的目标是验证方案是否可以成立，而不是先追求生产级无人值守。核心验证链路是：

```text
模拟会话存档消息
-> 多个 roomid 区分外部群
-> 只处理启用群
-> 只处理 @刘红利 的客户文本消息
-> 按 msgid 去重
-> 生成对应群的回复发送任务
```

运行多群 dry-run：

```bash
.venv/bin/python scripts/multi_group_reply_planner_poc.py \
  --assistant-name "刘红利" \
  --ignore-state \
  --out /tmp/multi_group_reply_jobs.jsonl
```

样例配置在：

```text
tests/fixtures/multi_group_targets.json
tests/fixtures/multi_group_msgaudit_messages.json
```

当前样例会生成两条回复任务：

```text
汽车贷款小助手 / sky / 需要经营证明吗
汽车金融VIP群 / kay / 贷款利率是多少
```

并跳过：

```text
[x] 未 @刘红利 的普通消息
[x] 未配置 roomid 的未知群
[x] 配置为 enabled=false 的暂停群
[x] 非文本消息
```

如果要把已生成任务标记为已处理，避免重复规划：

```bash
.venv/bin/python scripts/multi_group_reply_planner_poc.py \
  --assistant-name "刘红利" \
  --mark-planned
```

后期接真实会话内容存档时，应把真实 SDK 解密后的消息转换成同样的明文结构，后续多群回复规划逻辑不需要重写。

## 验证 5：主动提醒规则是否可控

主动提醒先用模拟账单数据验证，不操作企业微信：

当前样例账单把 `bill-sky-001` 设为 2026-05-17 到期；以 2026-05-15 运行时，会生成“账单还有2天到期”的提醒。

```bash
.venv/bin/python scripts/bill_reminder_planner_poc.py \
  --sample-bills-json tests/fixtures/bill_reminders.json \
  --today 2026-05-15 \
  --ignore-state \
  --out /tmp/bill_reminder_actions.jsonl
```

当前规则：

```text
[x] 到期前 3/2/1 天生成提醒
[x] 同一账单同一天只提醒一次
[x] 已结清账单不提醒
[x] 不在提醒窗口内的账单不提醒
[x] 生成的动作包含 @ 微信客户所需的 AppleScript
```

默认只生成动作计划，不会发送。需要写入本地去重状态时再显式加：

```bash
.venv/bin/python scripts/bill_reminder_planner_poc.py \
  --today 2026-05-15 \
  --mark-planned
```

状态文件在：

```text
data/member_assistant_poc/bill_reminder_state.json
```

## 后续 MVP 形态

如果上述 POC 都通过，下一步再做真正自动回复：

```text
定时拉取会话内容存档
按 roomid 过滤目标客户群
只处理 @小助理 或关键词触发的客户消息
AI/FAQ 生成回复
敏感词和置信度校验
企业微信客户端自动发送
记录每次输入、回复、发送结果
```

金融类话术必须保守：不能承诺审批结果、额度、利率，只能给资料说明、流程说明和转人工提示。

## 风险

1. 桌面自动化受 UI、焦点、语言、窗口状态影响，生产稳定性弱于官方 API。
2. 真正 @ 微信客户依赖客户端候选列表，昵称重复时容易选错。
3. 会话内容存档涉及客户同意和合规配置，必须按企业微信要求开通。
4. 高频自动回复可能触发客户体验和风控问题，建议只对明确 @ 小助理的消息响应。
