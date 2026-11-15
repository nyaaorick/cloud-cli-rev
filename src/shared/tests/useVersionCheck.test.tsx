import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { api } from '@/shared/api';
import { APP_VERSION } from '@/shared/constants';
import { useVersionCheck } from '@/shared/hooks/useVersionCheck';

vi.mock('@/shared/api', () => ({ api: { system: { health: vi.fn(), release: vi.fn() } } }));
afterEach(() => vi.clearAllMocks());

test('sidebar/About receive one backend-selected Rev release and managed installation mode', async () => {
  vi.mocked(api.system.health).mockResolvedValue(new Response(JSON.stringify({ version: APP_VERSION })));
  vi.mocked(api.system.release).mockResolvedValue(new Response(JSON.stringify({
    latestVersion: '1.37.9-rev.1', updateAvailable: true, installMode: 'managed',
    releaseInfo: { title: 'Rev', htmlUrl: 'https://github.com/nyaaorick/cloud-cli-rev/releases/tag/v1.37.9-rev.1' },
  })));
  const hook = renderHook(() => useVersionCheck());
  await waitFor(() => expect(hook.result.current.latestVersion).toBe('1.37.9-rev.1'));
  expect(hook.result.current.updateAvailable).toBe(true);
  expect(hook.result.current.installMode).toBe('managed');
  expect(hook.result.current.restartRequired).toBe(false);
  expect(hook.result.current.releaseInfo?.htmlUrl).toContain('/nyaaorick/cloud-cli-rev/');
  hook.unmount();
});

test('failed release checks are visible and do not claim an available update', async () => {
  vi.mocked(api.system.health).mockResolvedValue(new Response(JSON.stringify({ version: APP_VERSION })));
  vi.mocked(api.system.release).mockResolvedValue(new Response('', { status: 503 }));
  const hook = renderHook(() => useVersionCheck());
  await waitFor(() => expect(hook.result.current.releaseCheckError).toBe(true));
  expect(hook.result.current.latestVersion).toBeNull();
  expect(hook.result.current.updateAvailable).toBe(false);
  hook.unmount();
});

test('old browser assets detect that a new server version has been activated', async () => {
  vi.mocked(api.system.health).mockResolvedValue(new Response(JSON.stringify({ version: '99.0.0-rev.1' })));
  vi.mocked(api.system.release).mockResolvedValue(new Response(JSON.stringify({
    latestVersion: '99.0.0-rev.1', updateAvailable: false, installMode: 'managed', releaseInfo: null,
  })));
  const hook = renderHook(() => useVersionCheck());
  await waitFor(() => expect(hook.result.current.restartRequired).toBe(true));
  expect(hook.result.current.runningVersion).toBe('99.0.0-rev.1');
  hook.unmount();
});
