import assert from 'node:assert/strict';
import fs from 'node:fs';
import test, { type TestContext } from 'node:test';

import { askClaudeSideQuestion } from '@/modules/providers/list/claude/claude-side-question.provider.js';
import { queryClaudeSDK } from '@/modules/providers/list/claude/claude-runtime.provider.js';
import { CLAUDE_PREDEFINED_MODELS } from '@/modules/providers/list/claude/claude-models.provider.js';
import { providerRegistry } from '@/modules/providers/provider.registry.js';
import { providerCapabilitiesService } from '@/modules/providers/services/provider-capabilities.service.js';
import { CN25_MANAGER_ROLE_PATH } from '@/shared/utils.js';
import type { AnyRecord, ProviderRuntimeContext } from '@/shared/types.js';

const launcher = '/usr/local/libexec/cn25-claude-code/manager-launch';
const role = 'You are the CN25 manager. Synthetic role.';

function assertLockedOptions(options: AnyRecord | undefined) {
  assert.ok(options, 'the SDK must receive exactly one set of options');
  assert.equal(options.model, 'openai/gpt-6.2-sol');
  assert.equal(options.effort, 'xhigh');
  assert.equal(options.pathToClaudeCodeExecutable, launcher);
  assert.equal(options.env.CLAUDE_CODE_ENTRYPOINT, 'claudecodeui');
  assert.deepEqual(Object.keys(options.env).filter((name) => !['CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_ARTIFACT',
    'CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS'].includes(name)), [], 'no host environment reaches the CLI');
  assert.deepEqual(options.settingSources, []);
  assert.equal(options.strictMcpConfig, true);
  assert.equal(options.extraArgs.bare, null);
  assert.equal(options.extraArgs['disable-slash-commands'], null);
  assert.equal(options.mcpServers, undefined);
  assert.equal(options.hooks, undefined);
  assert.equal(options.systemPrompt.type, 'preset');
  assert.equal(options.systemPrompt.preset, 'claude_code');
  assert.ok(options.systemPrompt.append.startsWith(role), 'the manager role leads the appended prompt');
}

function captureQuery() {
  const calls: AnyRecord[] = [];
  const createQuery: NonNullable<ProviderRuntimeContext['createQuery']> = ({ options }) => {
    calls.push(options);
    return Object.assign((async function* () {})(), { interrupt: async () => {} });
  };
  return { createQuery, calls };
}

function withRoleFile(t: TestContext, content: string | null = role) {
  const original = fs.readFileSync;
  t.mock.method(fs, 'readFileSync', ((file: fs.PathOrFileDescriptor, ...rest: unknown[]) => {
    if (file !== CN25_MANAGER_ROLE_PATH) return (original as (...args: unknown[]) => unknown)(file, ...rest);
    if (content === null) throw Object.assign(new Error('ENOENT'), { code: 'ENOENT' });
    return content;
  }) as typeof fs.readFileSync);
}

function withApiOnlyEnvironment(t: TestContext) {
  withRoleFile(t);
  const overrides = {
    CN25_CLAUDE_API_ONLY: '1',
    CLAUDE_CLI_PATH: '/tmp/untrusted-claude',
    CLAUDE_CODE_OAUTH_TOKEN: 'must-not-inherit',
    ANTHROPIC_BASE_URL: 'http://untrusted.invalid',
  };
  for (const [key, value] of Object.entries(overrides)) {
    const previous = process.env[key];
    t.after(() => {
      if (previous === undefined) delete process.env[key];
      else process.env[key] = previous;
    });
    process.env[key] = value;
  }
}

test('CN25 Claude runtime locks a resumed session after resolving its saved model', async (t) => {
  withApiOnlyEnvironment(t);
  const { createQuery, calls } = captureQuery();
  const context: ProviderRuntimeContext = {
    resolveProviderSessionId: () => 'native-candidate-session',
    resolveResumeModel: async () => 'claude-opus-5',
    getProviderModels: async () => CLAUDE_PREDEFINED_MODELS as never,
    normalizeMessage: () => [],
    isProviderInstalled: async () => true,
    createQuery,
  };

  await queryClaudeSDK('synthetic manager prompt', {
    sessionId: 'app-candidate-session', cwd: process.cwd(), model: 'claude-sonnet-5-5', effort: 'low',
  }, { send: () => {}, userId: null } as never, context);

  assert.equal(calls.length, 1);
  assertLockedOptions(calls[0]);
  assert.equal(calls[0].resume, 'native-candidate-session');
  assert.equal(calls[0].extraArgs['replay-user-messages'], null);
  assert.equal(calls[0].permissionMode, 'bypassPermissions');
  assert.ok(calls[0].env.CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS, 'the background-agent ceiling survives the lock');
  assert.equal(calls[0].allowDangerouslySkipPermissions, true);
  assert.equal(calls[0].systemPrompt.append, role);
});

test('CN25 Claude side questions keep the same lock on their native fork', async (t) => {
  withApiOnlyEnvironment(t);
  const { createQuery, calls } = captureQuery();
  await askClaudeSideQuestion({
    appSessionId: 'app-candidate-session', providerSessionId: 'native-candidate-session',
    projectPath: process.cwd(), question: 'synthetic side question', model: 'claude-sonnet-5-5',
    signal: new AbortController().signal,
  }, { delta: () => {} }, { createQuery, liveTasks: [] });

  assert.equal(calls.length, 1);
  assertLockedOptions(calls[0]);
  assert.equal(calls[0].resume, 'native-candidate-session');
  assert.equal(calls[0].forkSession, true);
  assert.equal(calls[0].persistSession, false);
  assert.equal(calls[0].permissionMode, 'dontAsk', 'side questions keep their read-only mode');
  assert.equal(calls[0].allowDangerouslySkipPermissions, undefined);
  assert.ok(calls[0].systemPrompt.append.length > role.length, 'the side-question instructions follow the role');
});

test('CN25 API-only serves Claude alone with Full Access', (t) => {
  withApiOnlyEnvironment(t);
  assert.deepEqual(providerRegistry.listProviders().map((provider) => provider.id), ['claude']);
  assert.equal(providerRegistry.resolveProvider('claude').id, 'claude');
  for (const other of ['codex', 'cursor', 'opencode']) {
    assert.throws(() => providerRegistry.resolveProvider(other), /Unsupported provider/);
  }
  const capabilities = providerCapabilitiesService.getProviderCapabilities('claude');
  assert.deepEqual(capabilities.permissionModes, ['bypassPermissions']);
  assert.equal(capabilities.defaultPermissionMode, 'bypassPermissions');
});

test('CN25 Claude runtime starts no session without the manager role', async (t) => {
  withApiOnlyEnvironment(t);
  withRoleFile(t, null);
  const { createQuery, calls } = captureQuery();
  const sent: AnyRecord[] = [];
  const context: ProviderRuntimeContext = {
    resolveProviderSessionId: () => null,
    resolveResumeModel: async () => undefined,
    getProviderModels: async () => CLAUDE_PREDEFINED_MODELS as never,
    normalizeMessage: () => [],
    isProviderInstalled: async () => true,
    createQuery,
  };
  await queryClaudeSDK('synthetic manager prompt', { cwd: process.cwd() },
    { send: (message: AnyRecord) => sent.push(message), userId: null } as never, context).catch(() => {});
  assert.equal(calls.length, 0, 'no CLI is spawned without the role');
});
