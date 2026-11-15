import { useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import '@/modules/i18n';
import { ThemeProvider } from '@/shared/context/ThemeContext';
import { CommandPalette } from '@/modules/command-palette';

afterEach(cleanup);
afterEach(() => vi.unstubAllGlobals());
const originalScroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
afterEach(() => {
  if (originalScroll) Object.defineProperty(Element.prototype, 'scrollIntoView', originalScroll);
  else Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
});
beforeEach(() => {
  // cmdk measures its list in the browser; jsdom has no layout observer.
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
});

function CommandCenter() {
  const [open, setOpen] = useState(false);
  return <>
    <button onClick={() => setOpen(true)}>Command Center</button>
    <CommandPalette selectedProject={null} onStartNewChat={() => undefined} onOpenSettings={() => undefined} open={open} onOpenChange={setOpen} />
  </>;
}

function renderCenter() {
  render(<MemoryRouter><ThemeProvider><CommandCenter /></ThemeProvider></MemoryRouter>);
}

test('the title-bar command center opens the real command palette', () => {
  renderCenter();
  fireEvent.click(screen.getByRole('button', { name: 'Command Center' }));
  expect(screen.getByRole('dialog')).toBeDefined();
});

test.each([{ ctrlKey: true }, { metaKey: true }])('VS Code command shortcut opens and closes the palette (%o)', (modifier) => {
  renderCenter();
  fireEvent.keyDown(document, { key: 'P', shiftKey: true, ...modifier });
  expect(screen.getByRole('dialog')).toBeDefined();
  fireEvent.keyDown(document, { key: 'P', shiftKey: true, ...modifier });
  expect(screen.queryByRole('dialog')).toBeNull();
});
