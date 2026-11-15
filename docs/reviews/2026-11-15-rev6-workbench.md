# rev6 独立实现审查与处置

范围：`5eace2ee3c65bdf03d3b9bbdd823a753f96476d3..14bde1fdd0df14bbf8d5657adde3e6bcb718b514`。
审查者：独立代理 `rev6_implementation_review`，只读审查，未修改 checkout。

## 原始结论

Critical：无。Important：2 项，修复后可作为本地 UI 候选交付。Minor：1 项。
独立验证 8 个相关测试文件 / 45 项通过；隔离 Chrome 使用真实组件、xterm 和假 API/socket。

| 发现 | 影响与复现 | 主代理处置与证据 |
| --- | --- | --- |
| Important：隐藏终端自动连接新会话 | 打开 A 终端、关闭面板、选择 B；面板隐藏却发出 B 的 shell init，可能启动 CLI | 主代理复现。WorkspaceMain 显式传 `autoConnect={terminalOpen}`；新增生产 workspace→StandaloneShell→Shell runtime/socket 回归，RED 时出现 A/B init，修复后保持 A、隐藏切 B 不 init、重开才 init B；Chrome 同样通过。 |
| Important：活动栏裁剪底部操作 | 1100×500、5 个启用插件时，设置位于 515..563px，超出活动栏下边界 478px | 主代理复现。导航区允许垂直滚动，子项与底部操作区不收缩；Chrome 验证设置可达、每个插件可滚动触达。 |
| Minor：xterm 消费 Ctrl+J | 终端内按已公布的面板快捷键，实际发送换行且不关闭面板 | 主代理按“可能提交终端中的命令”的效果升为 Important 并修复。应用快捷键在 capture 阶段处理并停止传播；拦截按键目标的测试 RED→GREEN，Chrome 显示 Ctrl+J 关闭面板且 shell input 为空。 |

没有延期的小问题。

## 审查者未作判断的行为与主代理判断

- 发布、部署、真实远端 CLI 可用性：维持本地 UI 候选边界。隔离连接不能证明生产可用；若判断错误，需补真实服务验收，不能直接据此发布。
- 后端已知失败：后端、shared、发布脚本无 diff；保留原始结果，本轮不扩展修复。若据此忽略真实后端缺陷，会带入发布，所以不作完整发布验收通过的结论。
- 编辑器极限拖宽后聊天缩至 200px：基线已有相同下限，保留现有行为。成本是用户主动把聊天拖得很窄时，输入控件仍可能拥挤。

## 保留的回归步骤

1. 打开 A 的终端，关闭面板，确认原连接保持；切 B，确认没有新的 shell init；重开，确认仅此时发送 B init。
2. 启用 5 个插件，将桌面视口设为 1100×500，确认底部设置/终端始终可见，滚动导航可以依次点击所有插件。
3. 终端输入中按 Ctrl+J，确认面板收起且 socket 没有 input 帧；Cmd+J 同样可用，普通终端按键照常传递。

第 1/3 项的自动回归分别保存在 `workbenchTerminalRuntime.test.tsx`、`workbenchLayout.test.tsx`。
完整本地浏览器重放日志：工作区 `.claude/scratchpad/cloud-cli-rev6/review-repro-red.log`、`review-repro-green.log`、`review-fix-browser.log`。
