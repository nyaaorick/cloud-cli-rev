import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import type { ThreadOptions } from '@openai/codex-sdk';

import type { ProviderRuntimeContext } from '@/shared/index.js';

import { buildManagerCodexShellCommand, codexManagerService } from '../list/codex/codex-manager.service.js';
import { CodexProviderModels } from '../list/codex/codex-models.provider.js';
import { codexRuntime } from '../list/codex/codex-runtime.provider.js';
import { codexTurnClient } from '../list/codex/codex-turn.client.js';
import { providerCapabilitiesService } from '../services/provider-capabilities.service.js';

for (const resumed of [false, true]) {
  test(`manager ${resumed ? 'resume' : 'new'} honors selected model and effort while retaining its identity and permissions`, async (t) => {
    const home = mkdtempSync(path.join(os.tmpdir(), 'cloudcli-manager-'));
    writeFileSync(path.join(home, 'config.toml'), `model = "gpt-6.1-sol"
model_provider = "bifrost"
model_reasoning_effort = "xhigh"
approval_policy = "never"
sandbox_mode = "danger-full-access"
developer_instructions = "你是 CN25 审查机的大管理。维护、故障定位、任务协调。"
[model_providers.bifrost]
name = "Bifrost"
base_url = "https://example.invalid/v1"
env_key = "CODEX_GATEWAY_API_KEY"
wire_api = "responses"
requires_openai_auth = false
`);
    const names = ['CN25_MANAGER_MODE', 'CN25_MANAGER_CODEX_PATH', 'CODEX_HOME', 'CODEX_GATEWAY_API_KEY'];
    const previous = names.map((name) => process.env[name]);
    Object.assign(process.env, { CN25_MANAGER_MODE: '1', CN25_MANAGER_CODEX_PATH: '/fixed/native/codex', CODEX_HOME: home, CODEX_GATEWAY_API_KEY: 'test-only-not-a-credential' });
    t.after(() => {
      names.forEach((name, i) => { if (previous[i] === undefined) delete process.env[name]; else process.env[name] = previous[i]; });
      rmSync(home, { recursive: true, force: true });
    });
    let captured: ThreadOptions | undefined;
    let executable: string | undefined;
    let config: Record<string, any> | undefined;
    const thread = { id: 'native-manager', async runStreamed() { return { events: (async function* () { yield { type: 'thread.started', thread_id: 'native-manager' }; })() }; } } as unknown as ReturnType<typeof codexTurnClient.createThread>;
    t.mock.method(codexTurnClient, 'createThread', (id: string | null, options: ThreadOptions) => {
      assert.equal(id, resumed ? 'native-manager' : null);
      captured = options;
      const profile = codexManagerService.getProfile();
      executable = profile?.cliPath;
      config = profile?.config;
      return thread;
    });
    const selectedModel = resumed ? 'gpt-6.2-astra' : 'gpt-6.2-sol';
    const selectedEffort = resumed ? 'low' : 'ultra';
    const capabilities = providerCapabilitiesService.getProviderCapabilities('codex');
    for (const effort of ['low', 'medium', 'high', 'xhigh', 'max', 'ultra']) {
      assert.ok(capabilities.effortLevels.includes(effort), `manager capability must allow ${effort}`);
    }
    assert.deepEqual(capabilities.permissionModes, ['bypassPermissions']);
    const models = new CodexProviderModels();
    const catalog = await models.getSupportedModels();
    for (const model of ['gpt-6.2-astra', 'gpt-6.2-sol', 'gpt-6-astra', 'gpt-6.1-sol', 'gpt-6.1-terra']) {
      assert.deepEqual(catalog.OPTIONS.find((option) => option.value === model)?.effort?.values.map((value) => value.value),
        ['low', 'medium', 'high', 'xhigh', 'max', 'ultra']);
    }
    const context: ProviderRuntimeContext = {
      resolveProviderSessionId: () => resumed ? 'native-manager' : null,
      resolveResumeModel: async () => 'gpt-6.1-sol',
      getProviderModels: () => models.getSupportedModels(),
      normalizeMessage: () => [],
      isProviderInstalled: async () => true,
    };
    await codexRuntime.run('identify', { sessionId: resumed ? 'app-manager' : undefined, cwd: home, model: selectedModel, effort: selectedEffort, permissionMode: 'default' }, { isWebSocketWriter: true, send() {} }, context);
    assert.equal(executable, '/fixed/native/codex');
    assert.equal(buildManagerCodexShellCommand(resumed ? 'native-manager' : ''), resumed ? "'/fixed/native/codex' --no-daemon resume 'native-manager'" : "'/fixed/native/codex' --no-daemon");
    assert.equal(captured?.model, selectedModel);
    assert.equal(captured?.modelReasoningEffort, selectedEffort);
    assert.equal(captured?.sandboxMode, 'danger-full-access');
    assert.equal(captured?.approvalPolicy, 'never');
    assert.equal(config?.model_provider, 'bifrost');
    assert.equal(config?.model, undefined, 'manager overrides must not replace the selected model');
    assert.equal(config?.model_reasoning_effort, undefined, 'manager overrides must not replace the selected effort');
    assert.match(String(config?.developer_instructions), /CN25.*大管理/);
    assert.equal(config?.model_providers?.bifrost?.env_key, 'CODEX_GATEWAY_API_KEY');
    assert.ok(!JSON.stringify(config).includes('test-only-not-a-credential'));
    const configurableProfile = String.raw`model = "gpt-6.1-terra"
model_reasoning_effort = "ultra"
` + String.raw`model_provider = "bifrost"
approval_policy = "never"
sandbox_mode = "danger-full-access"
developer_instructions = "你是 CN25 审查机的大管理。"
[model_providers.bifrost]
base_url = "https://example.invalid/v1"
env_key = "CODEX_GATEWAY_API_KEY"
wire_api = "responses"
`;
    writeFileSync(path.join(home, 'config.toml'), configurableProfile);
    assert.equal(codexManagerService.getProfile()?.model, 'gpt-6.1-terra');
    delete process.env.CODEX_GATEWAY_API_KEY;
    assert.throws(() => codexManagerService.getProfile(), /no fallback/);
    process.env.CODEX_GATEWAY_API_KEY = 'test-only-not-a-credential';
    writeFileSync(path.join(home, 'config.toml'), 'model = "worker-model"\n');
    assert.throws(() => codexManagerService.getProfile(), /no fallback/);
  });
}
