# MiniMax 国内文生视频 CLI

Python 3.10+，仅标准库，无需安装第三方依赖。固定 API 主机为 `https://api.minimax.cn`。这是最小的 V1 文生视频实现，不包含图生视频或 H3/V2。

## 1. 离线检查（默认模式）

```bash
python minimax_video.py submit --prompt '日出时海浪轻拍沙滩'
python -m unittest -v
```

默认不读取密钥、不联网、不创建任务。支持 `MiniMax-Hailuo-2.3`（默认）和 `MiniMax-Hailuo-02`；6 秒支持 768P/1080P，10 秒仅支持 768P，提示词最多 2000 字符。

## 2. 经确认后提交付费任务

由用户在环境的密钥管理中配置名为 `MINIMAX_API_KEY` 的网络密钥；文档占位符为 `<MINIMAX_API_KEY>`。不要把实际值放进代码、命令行、聊天或仓库。本项目不创建或加载 `.env`。

以下命令会创建付费任务，只有确定要生成时才执行：

```bash
python minimax_video.py submit --prompt '日出时海浪轻拍沙滩' --execute --journal submission.json
```

提交前以独占方式创建本地记录；成功后输出并保存 `task_id`。任何错误均不自动重试。已有记录会阻止再次提交。超时、连接中断、业务错误或本地保存失败后，必须先检查原任务和账户记录；不要直接删除记录或换记录名重提，否则可能重复扣费。记录是本地防误操作措施，不是服务端幂等键，也不能阻止不同目录/记录名的重复生成。

## 3. 查询已有任务

```bash
python minimax_video.py query --task-id 你的数字任务ID
```

每次只查询一次。`Preparing`、`Queueing`、`Processing` 表示尚未完成，可稍后再次查询同一任务；`Fail` 不会触发新任务；`Success` 输出 `file_id`。

## 4. 保存结果

```bash
python minimax_video.py download --file-id 你的数字文件ID --output result.mp4
```

先取得文件信息，再从 HTTPS 下载地址流式保存。下载请求不携带 API 密钥，不输出签名 URL。现有文件不会被覆盖；中断时保留 `.part`，检查并删除该残片后可重新下载同一文件，不必重新生成。程序拒绝 HTTP 重定向；若实际 CDN 要求重定向，需先核实目标后再完善下载逻辑。

## 接口依据

2026-10-15 核对官方国内文档：

- [文生视频](https://platform.minimax.cn/docs/api-reference/video-generation-t2v)：POST `/v1/video_generation`，JSON `model`、`prompt`、`duration`、`resolution`；返回 `task_id`。
- [查询任务](https://platform.minimax.cn/docs/api-reference/video-generation-query)：GET `/v1/query/video_generation?task_id=...`，成功后返回 `file_id`。
- [下载文件](https://platform.minimax.cn/docs/api-reference/video-generation-download)：GET `/v1/files/retrieve?file_id=...`，读取 `file.download_url`。

API 采用 Bearer 鉴权并检查 `base_resp.status_code`；不会打印鉴权头、密钥或原始错误正文。

## 运行前提与验证范围

云端环境需要能够解析并连接 `api.minimax.cn`，以及 API 返回的视频下载主机。若发生 DNS 解析失败，应由环境管理员排查；本程序不修改网络或安全设置。

用户需通过密钥管理配置国内站凭证，并明确授权付费生成。离线测试不验证账户额度、模型权限或线上可用性。
