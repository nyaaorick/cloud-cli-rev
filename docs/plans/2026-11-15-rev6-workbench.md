# rev6 VS Code / Codex Workbench Implementation Plan

> **For agentic workers:** Follow the repository's execution/parallelization policy and the authorized method. Use subagent-driven-development or executing-plans as appropriate; steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 用 VS Code 风格工作台承载中央 Codex 对话，文件与终端按需打开。

**Architecture:** 复用 project-workspace 状态和现有功能模块，增加模块私有的布局 context 与工作台外框。通过主题变量统一视觉，不修改后端协议。

**Tech Stack:** React 18、TypeScript、Tailwind、Vitest、CodeMirror、xterm。

**Spec:** [改版设计](2026-11-15-rev6-workbench-design.md)。

## Global Constraints

- Node.js 22+；npm lockfile；不新增运行依赖。
- 前端遵循 `.agents/skills/frontend-module-standards/SKILL.md`。
- 聊天保持挂载，沿用发送/工具/会话行为；不改后端和线上环境。
- 桌面以聊天居中为默认；手机保留可用导航；深浅色继续工作。

## Review Focus

- 打开和关闭终端时，聊天草稿与终端实例不能丢失。
- 输入框内的普通按键不能误触发布局快捷键。
- 文件树展开后仍能使用聊天，编辑器关闭后可继续原对话。
- 连接断开时必须继续显示现有失联提示。
- 可选插件/任务关闭及窄屏时，导航仍可达，没有死按钮。

### Task 1: 工作台布局与行为

**Files:** `src/modules/project-workspace/` 的 shell、main、header、新增工作台外框/context/tests；`src/modules/command-palette/CommandPalette.tsx`；多文件使用的类型放 `src/shared/types.ts`。

**Interfaces:** 布局 context 提供 `terminalOpen: boolean`、`setTerminalOpen: Dispatch<SetStateAction<boolean>>`；CommandPalette 增加可选受控 `open` / `onOpenChange`。

- [x] 补终端开关、热键、聊天与文件/终端共存和命令中心行为测试；运行确认因缺少行为失败。
- [x] 加布局 context，标题栏、活动栏、状态栏；复用原入口回调。让终端在聊天下方独立开关，隐藏后保留实例；文件树不替换聊天。
- [x] 接入可控命令面板并支持 Cmd/Ctrl+Shift+P；保留 Cmd/Ctrl+K。
- [x] 运行相关测试，预期全部通过；按路径提交本任务。

### Task 2: VS Code / Codex 视觉

**Files:** `src/index.css`、`src/shared/context/ThemeContext.tsx`、`src/modules/sidebar/`、`src/modules/chat/composer/PromptInput.tsx` 和聊天空态。

**Interfaces:** 使用既有主题/偏好；工作台样式使用明确的语义类名，不用全局匹配 Tailwind 字符串的覆盖。

- [x] 对齐设计里的 Dark Modern / Light Modern 精确颜色、系统字体、边框和密度。
- [x] 收拢侧栏品牌/页脚和导航，保持项目/会话操作与升级提示可达。
- [x] 精简聊天空态和输入框视觉，保留模型、附件、权限和发送逻辑。
- [x] 浏览器验证桌面/手机、深浅色和真实交互；运行前端全测，预期通过；按路径提交。

### Task 3: rev6 准备和交付

**Files:** `package.json`、`package-lock.json`、`README.md`、`CHANGELOG.md`、验证记录。

**Interfaces:** 版本 `1.37.8-rev.6`，沿用原发布渠道与脚本。

- [x] 统一更新本地版本和改版说明，不创建 tag 或发布。
- [x] 运行 `npm run test:client`、`npm run typecheck`、`npm run lint`、`npm run build`；保存实际结果。
- [x] 独立审查整个改动，验证并修复重要发现，再运行受影响检查。
- [x] 交付可查看的本地结果、验证状态和未发布状态。

## 执行记录

Task 1/2 共用工作台与视觉文件，采用一个本地候选提交统一送独立审查；不切分成无法单独浏览验证的中间版本。详细验证与限制见 [交接记录](../journal/2026-11-15-rev6-workbench.md)。
