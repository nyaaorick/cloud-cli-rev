---
author: nyaaorick
progress:
  - date: 2026-11-15
    text: "修复 rev6 发布前的后端失败；相关 36 项回归已通过，全套发布检查与独立审查进行中。"
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

全套后端/前端、Python 部署测试、类型检查、lint、管理模式 build 与独立审查结果将在最终提交补齐。由 GitHub tag workflow 单独发布，避免双发布者。

原始失败和诊断日志保留在工作区 `.claude/scratchpad/cloud-cli-rev6/publish-*.log`，发布检查使用 `release-*.log`。
