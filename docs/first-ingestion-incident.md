# 第一次真实入库：Docling 调用链路故障

日期：2026-09-07。此记录为实际观测，不是故障注入实验。Tailscale 转发修复后，四份文档均成功完成入库，确认本次传输阻断已解除。

## 已完成

- 云端 `https://api.anchr.cloud` 校验令牌成功，角色为 ADMIN；会话能力返回 Agent 可用。
- 创建专用知识库 `anchr-eval-seed-v1`，知识库 ID：`1000447128`。
- 四份冻结 PDF 已通过服务签发的临时凭据上传到其对象存储。
- 已创建入库任务 `1000447132`。未上传题目、参考答案或其他本地资料。

| 文档 | 实际 Asset ID |
| --- | --- |
| D001 部署与数据边界 | `1000447186` |
| D002 RAG 与 Agent 规则 | `1000447377` |
| D003 索引重建与恢复 | `1000447553` |
| D004 注入测试副本 | `1000447660` |

任务状态会变化，以 `runs/setup/ingestion.json` 和 `runs/setup/document-bindings.json` 的最后查询结果为准。

## 现象与已确认范围

第一次尝试四份 PDF 均在 PARSE 阶段失败，入库任务终态为 FAILED（success=0、failed=4）。错误码为 `TEXT_PARSE_FAILED`，错误消息为 `docling transport failure`。失败时尚未完成分块、索引，无法取得可用的真实片段 ID。

本地 anchr-app 的 `DoclingClient.send` 将 HTTP 客户端发送时的 `IOException` 包装为这个消息。该错误不等价于“PDF 内容损坏”，也不能仅凭该消息判断是连接超时、拒绝连接还是其他传输原因；底层 cause 需要服务端日志确认。

用户确认线上 App 通过 Tailscale 调用本机 8091 的 Docling。只读检查结果：

- 本机 `http://127.0.0.1:8091/healthz` 返回 HTTP 200，`status=ok`、`running=0`、`queued=0`。
- Python 进程监听 `127.0.0.1:8091`，未监听 Tailscale 接口。
- Tailscale 状态为 Running，设备 Online，Health 无告警。
- 本机 Tailscale IPv4 为 `100.73.51.7`，DNS 为 `macbook-pro.tail9eafe1.ts.net`。
- `tailscale serve status --json` 返回空配置。

用户随后确认云端 `APP_DOCLING_BASE_URL=http://100.73.51.7:8091`。该地址需要通过本机 Tailscale 接口到达 Docling，但服务只监听回环地址，且无转发，这是实际存在的连接阻断点。

## 已实施修复

经用户明确授权后，配置持续生效的 tailnet TCP 转发：

```bash
tailscale serve --bg --tcp=8091 tcp://127.0.0.1:8091
```

变更只增加 Tailscale 8091 到本机回环 8091 的 TCP 转发；Docling 进程与其 API Token 保持原状，未配置公网 Funnel。

验证结果：

- `http://100.73.51.7:8091/healthz` 返回 200、status=ok。
- 无凭据访问 `/v1/jobs/anchr-eval-auth-probe` 返回 401、invalid bearer token，鉴权继续生效。
- 对原任务执行一次 `retry-failed`，没有重复创建知识库或上传文档。
- 2026-09-07 08:14 UTC 查询：success=2、failed=0，第三份正在 EMBED。前两份文档完成入库，提供了云端 App 到本机 Docling 的端到端成功证据。
- 后续查询任务进入 SUCCESS：success=4、failed=0；四份文档均为 ANSWERABLE，分别生成 5、9、9、1 个片段，共 24 个。
- 17 条标准证据均定位到实际片段，已区分文本完整性；第 001 题完成真实搜索与问答。传输故障修复成功不代表解析质量或回答质量全部通过，具体差异见首次试跑报告。

如需撤销本次转发，使用以下精确撤销命令，不影响其他端口：

```bash
tailscale serve --tcp=8091 off
```

## 验证完成与后续工作

1. 已确认原入库任务的四份文档全部成功。
2. 已执行证据绑定并逐条复核；14 条文本覆盖通过、3 条识别差异单独记录。
3. 已执行第 001 题，接口返回 ANSWERED；回答与引用质量另外评分。
4. 后续测评前保证本机 Docling 和 Tailscale 运行、设备保持可达。仅凭这次成功不推断重启后 Docling 进程会自动启动。

不要通过重新创建知识库或重复上传 PDF 处理这个连接错误。未验证的片段 ID 保持空值，不能以模拟 ID 代替。
