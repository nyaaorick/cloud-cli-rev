import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import type { AnyRecord } from '@/shared/types.js';

import { codexAppServer } from '../list/codex/codex-app-server.client.js';
import { codexTurnClient } from '../list/codex/codex-turn.client.js';

const messageId = '0b5c3f8e-6d1a-4c2b-9e7f-1a2b3c4d5e6f';

for (const mode of ['accept', 'reject', 'disconnect', 'timeout', 'abort'] as const) {
  test(`native steer uses the owning connection and active turn: ${mode}`, async (t) => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'codex-steer-'));
    const launcher = path.join(temp, 'fake.cjs');
    const log = path.join(temp, 'requests.jsonl');
    t.after(() => rm(temp, { recursive: true, force: true }));
    await writeFile(launcher, `
const fs = require('node:fs');
const rl = require('node:readline').createInterface({ input: process.stdin });
const send = x => process.stdout.write(JSON.stringify(x) + '\\n');
const note = (method, params) => send({ method, params: { threadId: 'native-thread', turnId: 'turn-1', ...params } });
const complete = () => note('turn/completed', { turn: { id: 'turn-1', status: 'completed' } });
setTimeout(() => process.exit(9), 10000).unref();
rl.on('line', line => {
 const r = JSON.parse(line); fs.appendFileSync(${JSON.stringify(log)}, line + '\\n');
 const reply = result => send({ id: r.id, result });
 switch (r.method) {
  case 'initialize': reply({}); break;
  case 'thread/start': case 'thread/resume': reply({ thread: { id: 'native-thread' } }); break;
  case 'turn/start':
   note('turn/started', { turn: { id: 'turn-1', status: 'inProgress' } });
   note('item/started', { item: { id: 'initial', type: 'userMessage', content: r.params.input } });
   reply({ turn: { id: 'turn-1' } });
   setTimeout(() => note('item/started', { item: { type: 'commandExecution', id: 'cmd-1', command: 'sleep 1', status: 'inProgress' } }), 20);
   break;
  case 'turn/steer':
   if (${JSON.stringify(mode)} === 'disconnect') { process.exit(4); break; }
   if (${JSON.stringify(mode)} === 'reject') {
    send({ id: r.id, error: { code: -32600, message: 'expectedTurnId does not match active turn' } }); setTimeout(complete, 40); break;
   }
   if (${JSON.stringify(mode)} === 'timeout') break;
   note('item/commandExecution/outputDelta', { itemId: 'cmd-1', delta: 'working' });
   reply({ turnId: 'turn-1' });
   setTimeout(() => {
    const item = { type: 'userMessage', id: 'native-user', clientId: r.params.clientUserMessageId, content: r.params.input };
    note('item/started', { item }); note('item/completed', { item });
    note('item/completed', { item: { type: 'agentMessage', id: 'answer', text: 'steered answer' } });
    note('thread/tokenUsage/updated', { tokenUsage: { total: { inputTokens: 12, outputTokens: 4, totalTokens: 16 }, modelContextWindow: 1000 } });
    complete();
   }, 50);
 }
});
`);
    t.mock.method(codexAppServer, 'resolveLauncher', () => launcher);
    const thread = codexTurnClient.createThread(mode === 'reject' ? 'native-thread' : null, { workingDirectory: temp, model: 'test-model', modelReasoningEffort: 'high', sandboxMode: 'workspace-write', approvalPolicy: 'on-request' });
    const controller = new AbortController();
    const stream = await thread.runStreamed('initial', { signal: controller.signal });
    const events: AnyRecord[] = [];
    let ready!: () => void;
    const running = new Promise<void>((resolve) => { ready = resolve; });
    const consumption = (async () => {
      for await (const event of stream.events) {
        events.push(event);
        if (event.item?.type === 'command_execution') ready();
      }
    })();
    void consumption.catch(() => {});
    await running;
    assert.equal(events.filter((event) => event.type === 'steer.delivered').length, 0);
    if (mode === 'abort') {
      controller.abort();
      await assert.rejects(consumption, /closed|aborted|exited/);
    } else if (mode === 'timeout') {
      t.mock.timers.enable({ apis: ['setTimeout'] });
      const result = thread.steer('unknown after timeout', messageId);
      t.mock.timers.tick(30001);
      await assert.rejects(result, /delivery is unknown/i);
      controller.abort();
      await assert.rejects(consumption, /closed/);
    } else if (mode === 'disconnect') {
      await assert.rejects(thread.steer('new direction', messageId), /delivery is unknown/i);
      await assert.rejects(consumption, /closed/);
    } else {
      const accepted = await thread.steer([{ type: 'text', text: 'new direction' }, { type: 'local_image', path: '/tmp/image.png' }], messageId);
      assert.equal(accepted, mode === 'accept');
      // Acknowledged, but the native user item has not arrived yet.
      assert.equal(events.filter((event) => event.type === 'steer.delivered').length, 0);
      await consumption;
      const echoes = events.filter((event) => event.type === 'steer.delivered');
      assert.equal(echoes.length, mode === 'accept' ? 1 : 0);
      if (mode === 'accept') {
        assert.equal(echoes[0].messageId, messageId);
        assert.ok(events.some((event) => event.type === 'item.updated' && event.item.id === 'cmd-1' && event.item.aggregated_output === 'working'));
        assert.equal(events.at(-1)?.usage.total_tokens, 16);
      }
    }
    assert.equal(await thread.steer('after completion', messageId), false);
    const requests = (await readFile(log, 'utf8')).trim().split('\n').map((line) => JSON.parse(line));
    assert.equal(requests.filter((request) => request.method === 'initialize').length, 1);
    assert.equal(requests.filter((request) => request.method === 'turn/start').length, 1);
    assert.equal(requests.filter((request) => request.method === 'thread/fork' || request.method === 'turn/interrupt').length, 0);
    const steer = requests.find((request) => request.method === 'turn/steer');
    if (mode !== 'abort') {
      assert.equal(steer.params.threadId, 'native-thread');
      assert.equal(steer.params.expectedTurnId, 'turn-1');
      assert.equal(steer.params.clientUserMessageId, messageId);
      if (mode === 'accept') assert.equal(steer.params.input[1].type, 'localImage');
      assert.equal(steer.params.model, undefined);
    }
  });
}
