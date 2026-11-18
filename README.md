# Cloud Cli rev

[源码仓库](https://github.com/nyaaorick/cloud-cli-rev) · [问题反馈](https://github.com/nyaaorick/cloud-cli-rev/issues)

独立维护的 CloudCLI UI 派生版本，供后续开发、问题追踪和版本管理使用。当前源码版本为 `1.37.8-rev.9`。

**上游来源：CloudCLI UI (https://github.com/siteboon/claudecodeui)。** 本项目包含修改，不是上游官方发行版，也不代表 Siteboon AI B.V. 对本项目的认可。

沿用 **AGPL-3.0-or-later**，完整保留 [LICENSE](LICENSE) 中的附加条款、[NOTICE](NOTICE) 中的原始署名与历史许可声明，以及上游 Git 历史。上游使用说明保存在 [README.upstream.md](README.upstream.md)。

## rev6 界面

工作台采用 VS Code Modern 的分区、密度和深浅色主题，中央默认保留 Codex 风格对话。
左侧活动栏集中管理会话、文件和源代码管理入口；文件树与编辑器按需打开，终端位于独立的底部面板。
顶部命令中心可搜索文件、会话和命令；保留 Cmd/Ctrl+K，并支持 Cmd/Ctrl+Shift+P 与 Cmd/Ctrl+J。

布局调整复用现有原生会话、工具、发送菜单和文件编辑能力。源码发布和线上部署仍分别执行。

## 维护起点

- 上游版本：v1.37.8，提交 `2053f3d7a086fd44f7fe373c913da487629b0a95`。
- 已验收 CN25 集成起点：`dede74da12c13c10ea7ae033c6681501cee447ac`。
- 保留网页聊天、原生工具、会话续接、文件预览、终端和单 owner 登录等上游能力。
- CN25 管理模式保留原生 Codex CLI、Bifrost provider 和管理身份；模型与思考深度可自由选择，配置中的 `gpt-6.1-sol` / `xhigh` 仅作为默认值；权限配置由服务端校验。
- Rev 9 增加 GPT-6.2 Astra 与 GPT-6.2 Sol。CN25 管理模式需要将独立的原生 CLI 升级到 0.170.0 并验证 Bifrost 的模型可用性。
- 此次仓库独立化包含项目名称、包元数据、文档及发布配置调整；线上已验收 release 与此源码版本分别记录。

## 从源码运行

需要 Node.js 22 及以上版本。

```bash
npm ci
npm run build
npm run server
```

开发时使用 `npm run dev`。标准开发服务默认通过 `http://localhost:3001` 访问，具体配置参考 `.env.example` 和上游说明。

依赖及 lockfile 沿用上游。发行渠道统一为 [Rev GitHub Releases](https://github.com/nyaaorick/cloud-cli-rev/releases)，提供源码、编译后的应用包、发布清单和 SHA256。未发布 npm 包、Docker 镜像或桌面二进制。保留 `cloudcli` 命令兼容性，并增加 `cloud-cli-rev` 命令别名。

网页与 CLI 共用 Rev 更新源及完整 SemVer 比较。托管安装通过网页 Update 或 `cloud-cli-rev update` 请求独立部署服务，在新目录校验版本，等会话与全部子进程空闲后更新固定应用服务，保留原端口、入口、数据和上一版回滚。源码和普通压缩包安装指向 GitHub 发行说明，不调用上游 npm 更新。发布流程、配置与回退见 [Rev 更新说明](deploy/cn25/REV-UPDATES.md)。

## CN25 集成

专用部署材料见 [deploy/cn25/README.md](deploy/cn25/README.md)。其中路径、账号和网络布局属于 CN25 场景，移植前应按实际机器检查，不能直接用于其他主机。

rev7 增加 [Cloudflare 物理直连环境](deploy/cn25/cloudflare/README.md) 和独立离线发行包，包含固定版 cloudflared、配置校验、systemd/sysusers、专用 DNS、幂等出口规则与只读诊断。网页使用现有系统字体回退，启动不再依赖 Google Fonts。现有命名隧道、DNS、凭证和历史继续保留。

服务端通过私有服务配置获得认证；仓库不包含服务凭证、owner 密码、JWT、API key、私有运行日志或会话数据。运行数据与 Git 源码分别维护。已有数据库、历史和运行中的管理服务不应随源码发布重新初始化。

## 本地验证

```bash
npm run typecheck
npm run test:client
npm test
npm run build
npm run lint
```

上游测试受机器并发和临时目录状态影响时，使用独立临时目录及适当并发；保留原始失败/取消记录，复验相关测试。模块开发约束见 [AGENTS.md](AGENTS.md)。

原上游发行、npm、桌面、Docker 和 Discord 通知 workflows 保存在 `.github/upstream-workflows/`，不作为本派生仓库的活动自动化。当前 `.release-it.json` 禁止 npm 发布。

## 继续维护

在自己的分支提交修改，通过测试后再合入 `main`。需要同步上游时，从 `upstream` remote 拉取并在独立分支审查差异；不要覆盖 CN25 集成或直接重写已发布历史。线上升级应独立构建、验证和切换，版本仓库的发布与运行服务的部署分别执行。

贡献说明见 [CONTRIBUTING.md](CONTRIBUTING.md)。提交修改时继续遵守原许可证及署名要求。

### Native Codex steering (Rev 2)

Codex main turns use the official CLI's stdio app-server. While a turn is
running, open the send menu and choose **Steer** to insert text or attachments
without stopping or starting another turn. The request uses `turn/steer` with
the active `expectedTurnId`; only the native user-message echo confirms delivery.
An uncertain connection result is shown explicitly and never automatically resent.
See the [official app-server protocol](https://learn.chatgpt.com/docs/app-server).

The isolated CN25 manager terminal uses its pinned CLI with `--no-daemon`:
its two-binary toolchain has no complete package for the shared daemon. Resume
failures remain visible and do not silently open another conversation. This does
not change the manager CLI installation, home, model, permissions or credentials.
