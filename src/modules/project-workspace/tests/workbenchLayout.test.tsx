import { useEffect } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { WorkbenchLayoutProvider, useWorkbenchLayout } from '@/modules/project-workspace/context/WorkbenchLayoutContext';
import { WorkbenchTerminalPanel } from '@/modules/project-workspace/WorkbenchTerminalPanel';

afterEach(cleanup);

function Controls() {
  const { terminalOpen, setTerminalOpen } = useWorkbenchLayout();
  return <button onClick={() => setTerminalOpen((open) => !open)} aria-pressed={terminalOpen}>Terminal</button>;
}

// A native terminal is an external resource; remounting this child represents
// losing that resource. The assertions target the production panel's lifecycle.
function TerminalSession({ onMount }: { onMount: () => void }) {
  useEffect(onMount, [onMount]);
  return <textarea aria-label="Terminal input" defaultValue="unfinished command" />;
}

test('closing and reopening the bottom terminal preserves its session and input', () => {
  const onMount = vi.fn();
  render(<WorkbenchLayoutProvider><Controls /><WorkbenchTerminalPanel><TerminalSession onMount={onMount} /></WorkbenchTerminalPanel></WorkbenchLayoutProvider>);
  expect(screen.queryByLabelText('Terminal input')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Terminal' }));
  const input = screen.getByLabelText('Terminal input');
  fireEvent.change(input, { target: { value: 'pending command' } });
  fireEvent.click(screen.getByRole('button', { name: 'Close Panel' }));
  expect(screen.getByRole('button', { name: 'Terminal' }).getAttribute('aria-pressed')).toBe('false');
  fireEvent.click(screen.getByRole('button', { name: 'Terminal' }));
  expect(screen.getByLabelText('Terminal input')).toBe(input);
  expect((input as HTMLTextAreaElement).value).toBe('pending command');
  expect(onMount).toHaveBeenCalledTimes(1);
});

test.each([{ ctrlKey: true }, { metaKey: true }])('Cmd/Ctrl+J toggles the bottom panel from the composer (%o)', (modifier) => {
  render(<WorkbenchLayoutProvider><Controls /><textarea aria-label="Chat draft" /></WorkbenchLayoutProvider>);
  const draft = screen.getByLabelText('Chat draft');
  fireEvent.change(draft, { target: { value: 'keep this draft' } });
  fireEvent.keyDown(draft, { key: 'j', ...modifier });
  expect(screen.getByRole('button').getAttribute('aria-pressed')).toBe('true');
  fireEvent.keyDown(draft, { key: 'j', ...modifier });
  expect(screen.getByRole('button').getAttribute('aria-pressed')).toBe('false');
  expect((draft as HTMLTextAreaElement).value).toBe('keep this draft');
});

test('typing, alternate shortcuts and an already handled key do not toggle the panel', () => {
  render(<WorkbenchLayoutProvider><Controls /></WorkbenchLayoutProvider>);
  fireEvent.keyDown(document, { key: 'j' });
  fireEvent.keyDown(document, { key: 'j', ctrlKey: true, altKey: true });
  const handled = new KeyboardEvent('keydown', { key: 'j', ctrlKey: true, bubbles: true, cancelable: true });
  handled.preventDefault();
  document.dispatchEvent(handled);
  expect(screen.getByRole('button').getAttribute('aria-pressed')).toBe('false');
});

test('Ctrl+J reaches the workbench before a terminal can consume it as input', () => {
  const terminalInput = vi.fn();
  render(<WorkbenchLayoutProvider><Controls /><textarea aria-label="Terminal keyboard" onKeyDown={(event) => {
    event.stopPropagation();
    terminalInput(event.key);
  }} /></WorkbenchLayoutProvider>);
  fireEvent.keyDown(screen.getByLabelText('Terminal keyboard'), { key: 'j', ctrlKey: true });
  expect(screen.getByRole('button').getAttribute('aria-pressed')).toBe('true');
  expect(terminalInput).not.toHaveBeenCalled();
});
