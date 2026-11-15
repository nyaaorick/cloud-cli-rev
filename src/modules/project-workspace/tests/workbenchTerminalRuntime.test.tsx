import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import '@/modules/i18n';
import WorkspaceMain from '@/modules/project-workspace/WorkspaceMain';
import { WorkbenchLayoutProvider, useWorkbenchLayout } from '@/modules/project-workspace/context/WorkbenchLayoutContext';
import type { Project, ProjectSession } from '@/shared/types';

// Keep the production workspace -> standalone shell -> shell runtime/socket path.
// Only the canvas-based terminal renderer and unrelated workspace panels are replaced.
vi.mock('@xterm/xterm', () => ({ Terminal: class {
  options = {}; cols = 80; rows = 24;
  constructor(options: object) { this.options = options; }
  open(node: HTMLElement) { node.appendChild(document.createElement('textarea')); }
  loadAddon() {} attachCustomKeyEventHandler() {} focus() {} write() {} clear() {} dispose() {}
  onData() { return { dispose() {} }; }
} }));
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }));
vi.mock('@xterm/addon-clipboard', () => ({ ClipboardAddon: class {} }));
vi.mock('@xterm/addon-web-links', () => ({ WebLinksAddon: class {} }));
vi.mock('@xterm/addon-webgl', () => ({ WebglAddon: class {} }));
vi.mock('@/shared/context/ThemeContext', () => ({ useTheme: () => ({ isDarkMode: true }) }));
vi.mock('@/shared/context/UiPreferencesContext', () => ({ useUiPreferences: () => ({}) }));
vi.mock('@/modules/chat', () => ({ ChatInterface: () => <textarea aria-label="Chat draft" />, getClaudeSettings: () => ({ skipPermissions: false }) }));
vi.mock('@/modules/file-tree', () => ({ FileTree: () => null }));
vi.mock('@/modules/git-panel', () => ({ GitPanel: () => null }));
vi.mock('@/modules/plugins', () => ({ PluginTabContent: () => null }));
vi.mock('@/modules/browser-use', () => ({ BrowserUsePanel: () => null, useBrowserUseEnabled: () => false }));
vi.mock('@/modules/task-master', () => ({ TaskMasterPanel: () => null, useTaskMasterProjectSync: () => {}, useTasksSettings: () => ({}) }));
vi.mock('@/modules/command-palette', () => ({ usePaletteOpsRegister: () => {} }));
vi.mock('@/modules/code-editor', () => ({ EditorSidebar: () => null, useEditorSidebar: () => ({ editingFile: null }) }));
vi.mock('@/modules/project-workspace/WorkspaceHeader', () => ({ default: () => null }));

class FakeSocket {
  static OPEN = 1; static CONNECTING = 0;
  static instances: FakeSocket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  frames: Array<{ type: string; sessionId?: string }> = [];
  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
    setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 1);
  }
  send(raw: string) { this.frames.push(JSON.parse(raw)); }
  close() { this.readyState = 3; this.onclose?.(); }
}

const PROJECT: Project = { projectId: 'test', path: '/test', fullPath: '/test', displayName: 'test', isStarred: false, sessions: [], sessionMeta: { total: 0, hasMore: false } };
const session = (id: string): ProjectSession => ({ id, __provider: 'codex' });
const noop = () => {};
function ToggleTerminal() {
  const { setTerminalOpen } = useWorkbenchLayout();
  return <button onClick={() => setTerminalOpen(true)}>Open terminal</button>;
}
function workspace(selectedSession: ProjectSession) {
  return <WorkbenchLayoutProvider><ToggleTerminal /><WorkspaceMain
    selectedProject={PROJECT} selectedSession={selectedSession} activeTab="chat" setActiveTab={noop}
    ws={null} sendMessage={noop} isMobile={false} onMenuClick={noop} isLoading={false}
    onNavigateToSession={noop} onSessionEstablished={noop} onShowSettings={noop}
    externalMessageUpdate={0} newSessionTrigger={0} onProjectSelect={noop} onProjectsRefresh={noop}
    onRenameSession={async () => true}
  /></WorkbenchLayoutProvider>;
}
const initSessions = () => FakeSocket.instances.flatMap(s => s.frames.filter(f => f.type === 'init').map(f => f.sessionId));
const settle = async () => { await act(async () => { await vi.advanceTimersByTimeAsync(500); }); };

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.instances = [];
  localStorage.setItem('auth-token', 'fixture-token');
  vi.stubGlobal('WebSocket', FakeSocket);
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); localStorage.clear(); });

test('hidden terminal retains its live socket, then waits for reopen before launching a different session', async () => {
  const view = render(workspace(session('A')));
  fireEvent.click(screen.getByRole('button', { name: 'Open terminal' }));
  await settle();
  expect(initSessions()).toEqual(['A']);
  const firstSocket = FakeSocket.instances[0];
  fireEvent.click(screen.getByRole('button', { name: 'Close Panel' }));
  await settle();
  expect(firstSocket.readyState).toBe(FakeSocket.OPEN);
  view.rerender(workspace(session('B')));
  await settle();
  expect(initSessions()).toEqual(['A']);
  expect(FakeSocket.instances).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Open terminal' }));
  await settle();
  expect(initSessions()).toEqual(['A', 'B']);
});
