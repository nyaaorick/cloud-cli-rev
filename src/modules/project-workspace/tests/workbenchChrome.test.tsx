import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { WorkbenchTitleBar } from '@/modules/project-workspace/WorkbenchChrome';
import { WorkbenchLayoutProvider } from '@/modules/project-workspace/context/WorkbenchLayoutContext';

const state = vi.hoisted(() => ({
  activeTab: 'files',
  sidebarVisible: true,
  setActiveTab: vi.fn(),
  setPreference: vi.fn(),
}));
vi.mock('@/modules/project-workspace/context/ProjectsStateContext', () => ({
  useProjectMainState: () => ({ activeTab: state.activeTab, setActiveTab: state.setActiveTab, selectedProject: null }),
  useProjectCommandState: () => ({}),
}));
vi.mock('@/shared/context/UiPreferencesContext', () => ({
  useUiPreferences: () => ({ sidebarVisible: state.sidebarVisible }),
  useSetUiPreference: () => state.setPreference,
}));
vi.mock('@/modules/project-workspace/WorkspaceTabs', () => ({ default: () => null }));
vi.mock('@/modules/task-master', () => ({ useTasksSettings: () => ({}) }));
vi.mock('@/modules/browser-use', () => ({ useBrowserUseEnabled: () => false }));
vi.mock('@/shared/context/WebSocketContext', () => ({ useWebSocket: () => ({}) }));

beforeEach(() => { vi.clearAllMocks(); state.activeTab = 'files'; state.sidebarVisible = true; });
afterEach(cleanup);

function renderTitleBar() {
  render(<MemoryRouter><WorkbenchLayoutProvider><WorkbenchTitleBar /></WorkbenchLayoutProvider></MemoryRouter>);
  return screen.getByRole('button', { name: 'Toggle Primary Side Bar' });
}

test('the sidebar control closes the open explorer and leaves chat visible', () => {
  fireEvent.click(renderTitleBar());
  expect(state.setActiveTab).toHaveBeenCalledWith('chat');
  expect(state.setPreference).toHaveBeenCalledWith('sidebarVisible', false);
});

test('the sidebar control reports an open explorer even when the session sidebar is hidden', () => {
  state.sidebarVisible = false;
  expect(renderTitleBar().getAttribute('aria-pressed')).toBe('true');
});
