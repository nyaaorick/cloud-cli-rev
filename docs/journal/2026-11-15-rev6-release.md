---
author: nyaaorick
progress:
  - date: 2026-11-15
    text: "rev6 发布检查通过：后端 1026 通过/4 跳过、前端 1142 通过、部署 Python 18 通过；独立审查 37/37，无待修发现。"
---

# rev6 失败修复与发布

## 目标与边界

用户本轮原话：「修复失败 发布成rev6」。完成标准为修复上一轮验证失败，通过仓库现有发布检查并发布 `v1.37.8-rev.6` GitHub Release。本轮授权包括提交、合入个人仓库 main、推送和打 tag，线上服务部署仍单独执行。

Path: 修复失败后发布 → Shortest: 修正真实 Codex 错误分类和失真的测试夹具，复用现有 tag 发布 workflow，不新增依赖或发布机制。

| 验收 | 修改 | 复用 |
| --- | --- | --- |
| 非用户取消的 Codex 错误明确报失败 | 当前运行的取消状态判断；错误通知回归 | codexTurnClient、现有通知事件与取消状态 |
| CLI 回归不受临时 JS 启动延迟干扰 | POSIX 版本夹具使用 shell 内建；超时验证等待 updater 启动后检查终止标记 | 原有真实 updater/进程组测试、生产 5 秒版本探测和更新超时不变 |
| 发布 rev6 | 更新发行说明、全套检查、不可变 tag | `.github/workflows/rev-release.yml`、现有打包与 GitHub 发布脚本 |

## 根因与修复证据

- 原始相关测试 36 项中 1 项稳定失败；通知测试模拟旧 SDK，未覆盖当前 app-server 入口，实际上可能调用本机 CLI。改为模拟 `codexTurnClient.createThread` 后，先确认上游 aborted 错误没有发送失败通知（RED）。修复后只有真实 abortController/session 取消才报取消，普通错误和上游 AbortError 均报失败。
- CLI 版本夹具以新建 Node 文件回答 `--version`，本机实测每次约 550–650ms，整套并发时曾超过生产的 5 秒限制。POSIX 改为 shell 内建读写版本文件；Windows 保留原夹具，更新器继续运行真实 Node 子进程。
- 原超时测试把前后版本探测也计入 `<2500ms`；复现日志显示 updater 正确报 timed_out，但整轮调用可能超过这个总耗时。改为等待真实 updater 子进程出现，使用已有 deadline 限定返回，并在其自然完成时间之后验证父/子完成标记均未写入，继续确认整组进程被终止。
- 第一轮相关 36 项全部通过；新增上游 AbortError 回归包含在最终全套结果中。

## 发布记录

本地发布检查结果：

- 后端 `npm test`：1030 项，1026 通过、0 失败、4 项既有平台跳过。
- 前端 `npm run test:client`：156 文件、1142 项通过。
- Python 部署测试：18 项通过。
- `npm run typecheck`、`npm run lint`、`VITE_CN25_MANAGER_MODE=1 npm run build` 均退出 0；lint 与打包体积警告仍保留，不放宽现有检查。
- 全量首轮遇到一次 Node 测试进程通信的反序列化异常；相关 Agent 测试单独复验和完整后端重跑均通过。新增两项错误用例最初复用同一 sessionId，触发桌面通知去重；已使用独立 sessionId，生产去重逻辑不变。

独立审查 `6578091b..a14d627e` 通过：Critical/Important/Minor 均无；审查者重跑 37 项全部通过，并实测含单引号、空格和 `$()` 的路径可以正确执行版本探测与更新。Windows 夹具分支未改，当前 Mac 未执行 Windows 实机验证。UI 使用上一轮独立审查及主代理修复复验记录，未重复扩大审查。

由 GitHub tag workflow 单独发布，避免双发布者；需要该 workflow 自身全部通过并确认 assets/manifest 后才报告发布成功。发行地址为 `https://github.com/nyaaorick/cloud-cli-rev/releases/tag/v1.37.8-rev.6`，线上服务仍单独部署。

原始失败和诊断日志保留在工作区 `.claude/scratchpad/cloud-cli-rev6/publish-*.log`，发布检查使用 `release-*.log`。
