import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';

import TOML from '@iarna/toml';
import type { CodexOptions } from '@openai/codex-sdk';

import { readObjectRecord } from '@/shared/utils.js';

function getProfile() {
  if (process.env.CN25_MANAGER_MODE !== '1') return null;
  const cliPath = process.env.CN25_MANAGER_CODEX_PATH;
  const home = process.env.CODEX_HOME;
  if (!cliPath || !path.isAbsolute(cliPath) || !home || !path.isAbsolute(home)) {
    throw new Error('Manager requires its fixed native CLI and CODEX_HOME.');
  }
  const profile = readObjectRecord(TOML.parse(readFileSync(path.join(home, 'config.toml'), 'utf8')));
  const providers = readObjectRecord(profile?.model_providers);
  const bf = readObjectRecord(providers?.bifrost);
  const role = profile?.developer_instructions;
  if (profile?.model !== 'gpt-6.1-sol' || profile?.model_provider !== 'bifrost'
    || profile?.model_reasoning_effort !== 'xhigh' || profile?.approval_policy !== 'never'
    || profile?.sandbox_mode !== 'danger-full-access' || typeof role !== 'string'
    || !role.includes('CN25') || !role.includes('大管理')
    || bf?.wire_api !== 'responses' || bf?.env_key !== 'CODEX_GATEWAY_API_KEY'
    || typeof bf?.base_url !== 'string' || !bf.base_url.startsWith('https://')
    || !process.env.CODEX_GATEWAY_API_KEY) {
    throw new Error('Manager BF profile or server credential is unavailable; no fallback is allowed.');
  }
  // Select only non-secret settings. SDK serializes these into CLI arguments;
  // authentication stays exclusively in PID1's inherited environment.
  const config = {
    model: 'gpt-6.1-sol', model_provider: 'bifrost', model_reasoning_effort: 'xhigh',
    approval_policy: 'never', sandbox_mode: 'danger-full-access', developer_instructions: role,
    model_providers: { bifrost: {
      name: 'Bifrost', base_url: bf.base_url, env_key: 'CODEX_GATEWAY_API_KEY',
      wire_api: 'responses', requires_openai_auth: false,
    } },
  } satisfies NonNullable<CodexOptions['config']>;
  return { cliPath, model: 'gpt-6.1-sol', effort: 'xhigh' as const, config };
}

let readiness: { key: string; expires: number; result: Promise<boolean> } | null = null;

function getCliConfigArgs(): string[] {
  const profile = getProfile();
  if (!profile) return [];
  const args: string[] = [];
  for (const [key, value] of Object.entries(profile.config)) {
    if (key === 'model_providers') {
      for (const [field, setting] of Object.entries(profile.config.model_providers.bifrost)) {
        args.push('-c', `model_providers.bifrost.${field}=${JSON.stringify(setting)}`);
      }
    } else args.push('-c', `${key}=${JSON.stringify(value)}`);
  }
  return args;
}

async function checkReady(): Promise<boolean> {
  const profile = getProfile();
  if (!profile) return false;
  const key = JSON.stringify([profile.cliPath, profile.config]);
  if (readiness?.key === key && readiness.expires > Date.now()) return readiness.result;
  const result = new Promise<boolean>((resolve) => {
    const args = ['exec', '--ephemeral', '--json', '--skip-git-repo-check', '--sandbox', 'danger-full-access'];
    args.push(...getCliConfigArgs());
    args.push('-');
    const child = spawn(profile.cliPath, args, {
      cwd: '/srv/review/manager-home/workspace', env: process.env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let completed = false;
    let buffered = '';
    const timer = setTimeout(() => child.kill('SIGTERM'), 60_000);
    child.stdout.on('data', (chunk) => {
      buffered += String(chunk);
      const lines = buffered.split('\n');
      buffered = lines.pop() || '';
      for (const line of lines) {
        try { if (JSON.parse(line).type === 'turn.completed') completed = true; } catch { /* Ignore non-events. */ }
      }
    });
    // Probe output and stderr can contain gateway response details. Keep them
    // out of HTTP responses and logs; readiness reports only success/failure.
    child.stderr.resume();
    child.stdin.on('error', () => {});
    child.on('error', () => { clearTimeout(timer); resolve(false); });
    child.on('close', (code) => { clearTimeout(timer); resolve(code === 0 && completed); });
    child.stdin.end('Do not use tools. Reply exactly BF_READY.');
  });
  readiness = { key, expires: Date.now() + 60_000, result };
  return result;
}

/** Used by Codex runtime/auth/models/app-server to bind this console to the accepted manager profile. */
export const codexManagerService = { getProfile, getCliConfigArgs, checkReady };

/** Used by the websocket shell to launch the isolated manager without a package daemon. */
export function buildManagerCodexShellCommand(resumeId: string): string | null {
  const profile = getProfile();
  if (!profile) return null;
  const executable = `'${profile.cliPath.replace(/'/g, "'\\''")}'`;
  // This immutable toolchain is a standalone binary, not a complete install.
  // Resume errors must remain visible instead of silently opening a new chat.
  return `${executable} --no-daemon${resumeId ? ` resume '${resumeId.replace(/'/g, "'\\''")}'` : ''}`;
}
