# 企业微信智能机器人 POC

这个目录是“客户自建智能机器人 + SaaS 后台”的最小技术验证版本。

## 验证目标

1. 企业微信后台能否通过 URL 验证。
2. 外部客户群中，普通微信客户 `@智能机器人` 后，本服务能否收到回调。
3. 本服务能否自动回复 FAQ 或转人工提示。
4. 通过回调里的 `response_url`，验证 1 小时内的主动回复能力。

真正的“无消息触发定时提醒”建议第二阶段再测长连接模式。

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`：

```ini
WECOM_AIBOT_TOKEN=企业微信智能机器人里配置的Token
WECOM_AIBOT_ENCODING_AES_KEY=企业微信智能机器人里配置的EncodingAESKey
WECOM_AIBOT_RECEIVE_ID=
HUMAN_USERID=需要转人工提醒的员工userid
```

启动服务：

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```powershell
curl http://127.0.0.1:8000/health
```

## 内网穿透

推荐先用 cloudflared 临时隧道：

```powershell
cloudflared tunnel --url http://localhost:8000
```

它会生成一个 `https://*.trycloudflare.com` 地址。

企业微信智能机器人 API 模式里的回调 URL 填：

```text
https://你的临时域名/wecom/aibot
```

## 测试顺序

1. 企业微信后台保存回调 URL，确认 URL 验证通过。
2. 把智能机器人加入测试外部客户群。
3. 普通微信客户在群里发送：`@机器人 申请贷款需要什么资料`
4. 打开：

```text
http://127.0.0.1:8000/debug/last-callback
```

查看最近一次明文回调。

5. 测试 `response_url` 主动回复：

```powershell
curl -X POST "http://127.0.0.1:8000/debug/send-last-response?content=POC主动回复测试"
```

注意：`response_url` 有效期 1 小时，且每个 `response_url` 只能调用一次。
