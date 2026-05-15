# 企业微信智能机器人长连接方式总结

## 1. 一句话结论

企业微信智能机器人长连接方式，是让我们的程序主动连接企业微信 WebSocket 服务，并通过这条连接接收消息、回复消息和主动发送消息。

它适合验证：

- 企业内部群或智能机器人可加入的群中，用户 `@机器人` 后自动回复。
- 不依赖公网 HTTPS 回调地址的本地开发。
- 定时提醒、异步通知、任务完成通知等主动消息。

它不适合作为完整的“外部客户群 + 微信客户 + 小助理自动回复”最终方案，因为当前实测和官方能力边界都指向：智能机器人不能稳定加入并服务外部客户群里的微信客户。

## 2. 长连接和短连接的区别

| 对比项 | 短连接回调 URL | 长连接 WebSocket |
|---|---|---|
| 连接方向 | 企业微信请求我们的公网 URL | 我们主动连接企业微信 |
| 是否需要公网 HTTPS | 需要 | 不需要 |
| 凭证 | Token、EncodingAESKey | BotID、Secret |
| 消息加解密 | 需要处理 AES 加解密 | 长连接消息体不需要回调 URL 加解密 |
| 实时性 | 一般 | 更好 |
| 主动发消息 | 受 response_url 限制 | 支持 `aibot_send_msg` |
| 运行要求 | Web 服务 + 公网隧道/服务器 | 常驻 WebSocket 进程 |
| 风险点 | URL 校验、隧道稳定性、加解密 | 心跳、断线重连、单机器人单连接 |

注意：智能机器人 API 模式通常只能在“设置接收消息回调地址”和“长连接”之间二选一。切到长连接后，原回调 URL 不再生效。

## 3. 基本工作流

```text
程序启动
  ↓
连接 wss://openws.work.weixin.qq.com
  ↓
使用 BotID + Secret 发送 aibot_subscribe
  ↓
企业微信通过长连接推送 aibot_msg_callback / aibot_event_callback
  ↓
程序解析消息并生成回复
  ↓
通过 replyStream / aibot_send_msg 回复或主动发送消息
  ↓
定期 ping 保持连接
```

## 4. 需要准备的配置

从企业微信后台智能机器人 API 模式的长连接配置里获取：

```ini
WECOM_AIBOT_BOT_ID=
WECOM_AIBOT_SECRET=
```

安全注意：

- `Secret` 是长连接专用密钥，不是短连接模式的 `Token` 或 `EncodingAESKey`。
- 不要把 `BotID`、`Secret`、`Token`、`EncodingAESKey` 写进 Git、截图或公开文档。
- 同一个机器人同一时间只能保持一个有效长连接，新连接订阅成功后会踢掉旧连接。

## 5. 当前项目中的相关文件

```text
app/wecom_ws.py
scripts/wecom_aibot_ws_poc.py
tests/test_wecom_ws.py
docs/LONG_CONNECTION_POC.md
```

职责说明：

- `app/wecom_ws.py`：封装订阅、主动发消息、心跳等 WebSocket 消息格式。
- `scripts/wecom_aibot_ws_poc.py`：最小长连接验证脚本。
- `tests/test_wecom_ws.py`：覆盖长连接消息构造和响应判断。
- `docs/LONG_CONNECTION_POC.md`：命令级 POC 验证步骤。

## 6. 本地验证命令

进入项目：

```bash
cd /Users/liuhongli/Desktop/lingchen/wechat-rpa-poc-handoff
source .venv/bin/activate
```

自检：

```bash
python -m unittest tests.test_wecom_ws
python -m compileall app scripts tests
```

只建立长连接并打印消息：

```bash
python scripts/wecom_aibot_ws_poc.py
```

主动向群聊发消息：

```bash
python scripts/wecom_aibot_ws_poc.py \
  --send-chatid "群聊chatid" \
  --send-content "POC测试：账单还有3天到期，请确认是否能收到提醒。" \
  --chat-type 2
```

`chatid` 需要先通过一次真实群消息回调获得。

## 7. 已验证结果

当前项目已经验证过：

- `aibot_subscribe` 订阅成功。
- `ping` 心跳成功。
- 群里 `@机器人` 后可以收到 `aibot_msg_callback`。
- 可以拿到群聊 `chatid`。
- 可以通过 `aibot_send_msg` 主动向已知群聊发送消息。
- 本地单元测试通过。
- 代码编译检查通过。

这说明长连接技术链路本身可用。

## 8. 关键限制

1. 群消息通常需要用户 `@机器人`，企业微信才会把消息推给程序。
2. 主动发送消息必须知道目标 `chatid` 或用户 `userid`。
3. 同一个机器人只能保留一个有效长连接。
4. 生产环境必须实现断线重连、心跳、日志、去重和异常告警。
5. 机器人主动消息是否能真正 `@` 普通微信客户，不能只靠文本推断，必须客户端实测。
6. 长连接解决的是“智能机器人消息通道”，不是“企业微信成员账号小助理 RPA”。

## 9. 和外部客户群自动回复的关系

你的目标场景是：

```text
外部客户群
  ↓
群里有微信客户
  ↓
客户提问
  ↓
小助理自动回复
  ↓
账单到期前主动提醒客户
```

长连接只能覆盖其中一部分：

| 目标能力 | 长连接是否适合 |
|---|---|
| 智能机器人可加入的群里自动回复 | 适合 |
| 内部企业微信群定时提醒 | 适合 |
| 无公网服务器开发调试 | 适合 |
| 外部客户群里的微信客户自动回复 | 不适合作为最终方案 |
| 以企业微信成员“小助理”身份发言 | 不适合 |

因此，如果坚持实现“外部客户群自动回复”，更接近的最终方案是：

```text
企业微信成员账号：小助理
  ↓
加入外部客户群
  ↓
会话内容存档读取消息
  ↓
AI/业务规则生成回复
  ↓
客户端自动化/RPA 控制企业微信发出
```

长连接 POC 的价值是证明“机器人通道自动回复和主动提醒”可行，但它不能替代成员账号小助理方案。

## 10. 下一步建议

建议按两个 POC 并行拆开：

1. 长连接 POC：继续完善机器人自动回复、主动提醒、断线重连。
2. 小助理 RPA POC：验证企业微信成员账号能否被稳定自动化发送消息到外部客户群。

判断是否进入 MVP 的最低标准：

- 能稳定读到外部客户群消息。
- 能稳定定位目标群并发送文本。
- 能识别客户是否 `@小助理`。
- 能避免重复回复。
- 金融类高风险问题能转人工或输出合规话术。

## 11. 官方参考

- 企业微信智能机器人长连接：https://developer.work.weixin.qq.com/document/path/101463
- 应用推送消息到群聊会话限制：https://developer.work.weixin.qq.com/document/path/90248
- 会话内容存档概述：https://developer.work.weixin.qq.com/document/path/91360
- 获取会话内容：https://developer.work.weixin.qq.com/document/path/91774
- 获取会话同意情况：https://developer.work.weixin.qq.com/document/path/91782
