import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Terminal, X } from 'lucide-react';

import { useWorkbenchLayout } from '@/modules/project-workspace/context/WorkbenchLayoutContext';

/** Used by WorkspaceMain to dock its existing terminal below the conversation. */
export function WorkbenchTerminalPanel({ children }: { children: ReactNode }) {
  const { terminalOpen, setTerminalOpen } = useWorkbenchLayout();
  // Lazily create the native terminal once, then retain its connection and buffer while hidden.
  const [hasOpened, setHasOpened] = useState(terminalOpen);
  useEffect(() => {
    if (terminalOpen) setHasOpened(true);
  }, [terminalOpen]);
  if (!terminalOpen && !hasOpened) return null;

  return (
    <section className="workbench-panel" aria-label="Terminal" hidden={!terminalOpen}>
      <div className="workbench-panel-header">
        <span className="workbench-panel-title"><Terminal size={13} aria-hidden="true" />TERMINAL</span>
        <button type="button" className="workbench-icon-button" aria-label="Close Panel" onClick={() => setTerminalOpen(false)}>
          <X size={16} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
    </section>
  );
}
