# anchr-eval

通过 Anchr App REST API 进行离线测评。当前已完成第一批测评资料、10 道题、资料入库、证据绑定、可恢复的批量执行和基于明确复核标注的离线评分。第一轮 10 题基线已经保存，版本对比与优化实验尚未实施。

从 [测评数据说明](datasets/anchr-seed-v1/README.md) 开始，或直接阅读 [10 道题及参考答案](datasets/anchr-seed-v1/review/questions.md)。

上传用 PDF 位于 `output/pdf/`。题目、参考答案、标注和完整来源快照仅保留在测评端，不应上传到被测知识库。

## 安装与配置

使用 Python 3.11 或更高版本：

```bash
uv sync
```

在项目根目录的 `.env` 中配置 `ANCHR_BASE_URL` 和 `ANCHR_ACCESS_TOKEN`，格式参考 `.env.example`。当前已经保存用户提供的本地配置，文件权限为仅当前用户可读写，且被 `.gitignore` 排除。环境变量优先于 `.env`；Token 不写入报告。

## 已实现命令

```bash
uv run anchr-eval validate
uv run anchr-eval doctor
uv run anchr-eval ingest
uv run anchr-eval status
uv run anchr-eval bind
uv run anchr-eval review-bindings
uv run anchr-eval smoke --case-id ANCHR-010-001
uv run anchr-eval batch --name baseline-v1
uv run anchr-eval score --name baseline-v1
uv run pytest -q
```

请从项目根目录运行，或通过 `--root` 显式指定项目路径。

- `validate` 检查题目 ID 与四份上传 PDF 的 SHA-256。
- `doctor` 只读检查令牌角色与会话能力，结果保存到 `runs/setup/doctor.json`。
- `ingest` 创建或复用带专用说明标记的知识库，通过临时 STS 凭据向服务配置的 OSS 上传四份 PDF，再提交带 `clientRequestId` 的入库任务。
- `status` 单次查询任务与文档状态，不自动重试失败任务。
- `bind` 在四份文档均为 `ANSWERABLE` 后执行证据检索，并逐个调用预览接口核验真实片段。只接受同页完整摘录匹配；跨片段、表格重排或解析文本差异保留 `needs_review`。最多三个并发只读探测；探测可能触发服务内部改写和追问生成，但不计入测评结果。
- `review-bindings` 在本地应用 `runs/setup/binding-review.json` 中逐条写明的来源复核。校验服务、文档哈希、原文哈希、页码、片段正文哈希和实际摘录后，输出 `bindings.reviewed.json` 与派生的 `cases.bound.jsonl`；原始 `cases.jsonl` 不变。定位成功但关键字符缺失的证据仍标为 `located_text_partial`，不会升级成文本完整。
- `smoke` 为指定题目执行一次检索与普通 RAG 问答，显式限定文档，每次新建会话。原始响应、耗时、范围和绑定快照保存到独立 `runs/smoke-.../`。未自动判分，也不把缺失的 Token 用量或费用记为零。
- `batch` 按顺序执行全部十题，保存每题执行意图与结果。已有完整结果会复用；存在结果不确定的写请求时停止并要求先核对，不盲目重复调用。首次建立基线时用 `--reuse-run runs/smoke-20f868cf-6889-45c7-b686-eedec5370822` 复用了已完成的第一题；之后直接运行同名 batch 会复用全部结果。
- `score` 校验 `runs/<批次名>/review.json` 与实际答案哈希、题目事实、引用数量一致，再离线汇总 `scores.json`。评分依据逐题明确复核，不把接口返回成功直接算为正确；无效实验样本单列，澄清题与无答案题分别汇总。
- `retry-failed` 仅在故障原因已经排除且入库任务终止后，由用户显式执行，复用原任务重试失败项，不重新上传资料。

入库进度保存在 `runs/setup/ingestion.json`，不包含访问令牌或 STS 密钥。提交结果不确定时再次执行 `ingest` 会先按同一 `clientRequestId` 查回任务，不盲目重复提交；若查回失败，需要核对服务端状态后处理。已经上传但尚未提交的对象不会被自动删除。

客户端识别 HTTP 状态与业务响应 `code` 两层错误，不跟随携带令牌的重定向，也不自动重试创建会话、知识库、消息等写入请求。当前 REST 合同依据本地 anchr-app 代码，线上完整入库流程需实际验证。

## 当前进度与限制

已修复 Docling 的 Tailscale 访问链路，原任务四份 PDF 均入库成功，共 24 个片段。17 条证据均已定位到真实片段：6 条严格匹配、8 条按来源复核为等价、3 条存在解析文本缺失。实际 ID 和最新状态见 `runs/setup/`；带真实 ID 的派生题目为 [cases.bound.jsonl](runs/setup/cases.bound.jsonl)。来源复核由 Codex 完成，尚未经过独立人工审核。

第一轮 10 题均完成普通 RAG 调用，10 个持久化回答均与即时响应一致。基于 Codex 的严格来源复核，9 道有效题通过 2 道，第010题因文档攻击文本失真单列；该复核不是独立人工盲审。详见 [完整基线报告](reports/baseline-v1.md)、[首次试跑报告](reports/seed-smoke-001.md) 与 [故障修复记录](docs/first-ingestion-incident.md)。10题规模较小，延迟百分位仅描述本次样本。

现有 `AssetDTO` 和片段预览 DTO 不公开 generation 数值。绑定中明确保留 `index_generation=null`，不把 `versionNo` 冒充索引 generation。预览接口在当前本地实现中检查片段是否属于 active generation，但这只能作为绑定时点的有效性证据；严格的版本复现还需补充服务版本及索引配置快照。正式片段指标不可把试跑结果当成已验证基线。

本次索引模型/维度/fingerprint、分块参数、检索参数和生成模型名称已保存在 `runs/setup/server-snapshot.json`，不包含凭据；线上 Git commit 仍不可用。已有复核仅适用于捕获时的片段正文；重建分块或重新解析后，应重新绑定和复核。
