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

默认只处理明确 `@小助理` 的消息，避免普通群聊内容被误回复。输出会写入：

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
