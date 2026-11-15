import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { Dispatch, ReactNode, SetStateAction } from 'react';

type WorkbenchLayoutState = {
  terminalOpen: boolean;
  setTerminalOpen: Dispatch<SetStateAction<boolean>>;
  commandsOpen: boolean;
  setCommandsOpen: Dispatch<SetStateAction<boolean>>;
};

const WorkbenchLayoutContext = createContext<WorkbenchLayoutState | null>(null);

/** Used by ProjectWorkspaceRoute to share panel visibility across this module's chrome and content. */
export function WorkbenchLayoutProvider({ children }: { children: ReactNode }) {
  // Panel visibility is independent of the selected conversation or workspace view.
  const [terminalOpen, setTerminalOpen] = useState(false);
  // The title-bar command center and the existing palette share one open state.
  const [commandsOpen, setCommandsOpen] = useState(false);
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || event.altKey || event.repeat) return;
      if ((event.metaKey || event.ctrlKey) && !event.shiftKey && event.key.toLowerCase() === 'j') {
        event.preventDefault();
        setTerminalOpen((open) => !open);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);
  const value = useMemo(() => ({ terminalOpen, setTerminalOpen, commandsOpen, setCommandsOpen }), [terminalOpen, commandsOpen]);
  return <WorkbenchLayoutContext.Provider value={value}>{children}</WorkbenchLayoutContext.Provider>;
}

export function useWorkbenchLayout() {
  const context = useContext(WorkbenchLayoutContext);
  if (!context) throw new Error('useWorkbenchLayout must be used within WorkbenchLayoutProvider');
  return context;
}
