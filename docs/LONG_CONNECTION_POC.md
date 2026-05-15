# 智能机器人长连接 POC

## 目标

验证企业微信智能机器人长连接模式是否可用，并为后续测试 `aibot_send_msg` 主动向群聊发消息做准备。

这不是当前回调 URL 模式的替代上线方案，只是最小技术验证脚本。

## 重要限制

企业微信智能机器人 API 模式只能二选一：

```text
设置接收消息回调地址
长连接
```

切到长连接后，原来的回调 URL 将不再生效。建议新建第二个测试机器人做长连接实验，不要直接切换已经跑通的机器人。

## 配置

从企业微信后台的长连接模式获取：

```ini
WECOM_AIBOT_BOT_ID=长连接模式 BotID
WECOM_AIBOT_SECRET=长连接模式 Secret
```

`Secret` 是长连接专用密钥，不是回调 URL 模式的 `Token` 或 `EncodingAESKey`。

## 只建立长连接并打印事件

```bash
cd /Users/liuhongli/Desktop/lingchen/wechat-rpa-poc-handoff
source .venv/bin/activate
python scripts/wecom_aibot_ws_poc.py
```

脚本会：

```text
连接 wss://openws.work.weixin.qq.com
发送 aibot_subscribe
打印企业微信推送过来的消息和事件
```

## 主动发一条群消息

先通过长连接收到一次群消息，记录回调里的 `chatid`，再执行：

```bash
python scripts/wecom_aibot_ws_poc.py \
  --send-chatid "群聊chatid" \
  --send-content "POC测试：账单还有3天到期，请确认是否能收到提醒。" \
  --chat-type 2
```

如果要测试是否能提醒普通微信客户，只能先把客户昵称写进内容里观察客户端表现。是否能真正形成 `@` 提醒，需要实测，不能提前承诺。

## 验收标准

```text
[ ] aibot_subscribe 返回 errcode=0
[ ] @机器人 后能收到 aibot_msg_callback
[ ] 能拿到群聊 chatid
[ ] aibot_send_msg 返回 errcode=0
[ ] 群里能看到机器人主动消息
[ ] 普通微信客户是否收到真正 @ 提醒
```
