import type { ThreadOptions, UserInput } from '@openai/codex-sdk';

import { AppError, readObjectRecord } from '@/shared/utils.js';
import type { AnyRecord } from '@/shared/types.js';
import { codexAppServer } from './codex-app-server.client.js';
import { codexManagerService } from './codex-manager.service.js';

function nativeInput(input: string | UserInput[]) {
  return typeof input === 'string' ? [{ type: 'text', text: input }] : input.map((item) => (
    item.type === 'local_image' ? { ...item, type: 'localImage' } : item
  ));
}

function translateItem(item: AnyRecord): AnyRecord | null {
  const base = { ...item, id: item.id };
  switch (item.type) {
    case 'agentMessage': return { ...base, type: 'agent_message' };
    case 'reasoning': return { ...base, text: [...(item.summary || []), ...(item.content || [])].join('\n') };
    case 'commandExecution': return { ...base, type: 'command_execution', aggregated_output: item.aggregatedOutput || '', exit_code: item.exitCode, status: item.status === 'inProgress' ? 'in_progress' : item.status };
    case 'fileChange': return { ...base, type: 'file_change', changes: item.changes?.map((change: AnyRecord) => ({ ...change, kind: change.kind?.type || change.kind })) };
    case 'mcpToolCall': return { ...base, type: 'mcp_tool_call', status: item.status === 'inProgress' ? 'in_progress' : item.status };
    case 'webSearch': return { ...base, type: 'web_search' };
    default: return null;
  }
}

/** Used by codexRuntime for main turns and native same-turn steering. */
export const codexTurnClient = {
  createThread(resumeId: string | null, options: ThreadOptions) {
    let threadId = resumeId;
    let steerActive: ((input: string | UserInput[], messageId: string) => Promise<boolean>) | null = null;
    return {
      get id() { return threadId; },
      async steer(input: string | UserInput[], messageId: string): Promise<boolean> {
        return steerActive ? steerActive(input, messageId) : false;
      },
      async runStreamed(input: string | UserInput[], { signal }: { signal: AbortSignal }) {
        const queue: AnyRecord[] = [];
        let wake: (() => void) | undefined;
        let done = false;
        let failure: unknown;
        const emit = (event: AnyRecord) => { queue.push(event); wake?.(); };
        // Start the connection once; it lives until the native turn completes.
        const operation = codexAppServer.withConnection(async ({ call, onNotification, onExit }) => {
          const manager = codexManagerService.getProfile();
          const settings = {
            cwd: options.workingDirectory,
            model: options.model,
            sandbox: options.sandboxMode,
            approvalPolicy: options.approvalPolicy,
            ...(manager ? { modelProvider: 'bifrost', developerInstructions: manager.config.developer_instructions, config: manager.config } : {}),
          };
          const response = await call(resumeId ? 'thread/resume' : 'thread/start', {
            ...settings,
            ...(resumeId ? { threadId: resumeId } : {}),
          }) as AnyRecord;
          threadId = response?.thread?.id;
          if (!threadId) throw new Error('Codex returned no thread id.');
          emit({ type: 'thread.started', thread_id: threadId });
          let turnId: string | null = null;
          let turnEnded = false;
          let usage: AnyRecord | undefined;
          const pendingMessages = new Set<string>();
          const echoed = new Set<string>();
          const items = new Map<string, AnyRecord>();
          let finish!: () => void;
          let fail!: (error: Error) => void;
          const completed = new Promise<void>((resolve, reject) => { finish = resolve; fail = reject; });
          // Attach before turn/start: notifications may precede its response.
          const offExit = onExit(() => fail(new Error('Codex app-server connection closed during the turn.')));
          const offNotification = onNotification((method, value) => {
            const params = value as AnyRecord;
            if (params?.threadId !== threadId) return;
            if (method === 'turn/started') {
              turnId = params.turn?.id;
              emit({ type: 'turn.started' });
              return;
            }
            if (!turnId || params.turnId && params.turnId !== turnId) return;
            if (method === 'thread/tokenUsage/updated') {
              const total = params.tokenUsage?.total;
              usage = total ? { input_tokens: total.inputTokens, output_tokens: total.outputTokens, total_tokens: total.totalTokens, model_context_window: params.tokenUsage.modelContextWindow } : undefined;
            } else if (method === 'turn/plan/updated') {
              emit({ type: 'item.updated', item: { type: 'todo_list', id: `${turnId}-plan`, items: params.plan.map((step: AnyRecord) => ({ text: step.step, completed: step.status === 'completed' })) } });
            } else if (method === 'item/commandExecution/outputDelta') {
              const item = items.get(params.itemId);
              if (item) {
                item.aggregated_output += params.delta || '';
                emit({ type: 'item.updated', item: { ...item } });
              }
            } else if (method === 'item/started' || method === 'item/completed') {
              const item = params.item;
              if (item?.type === 'userMessage') {
                // A request acknowledgement is not delivery. Only the native
                // user item, with our client id, settles the pending card.
                if (pendingMessages.has(item.clientId) && !echoed.has(item.clientId)) {
                  echoed.add(item.clientId);
                  emit({ type: 'steer.delivered', messageId: item.clientId, content: item.content });
                }
              } else if (item) {
                const translated = translateItem(item);
                if (translated) items.set(item.id, translated);
                if (translated) emit({ type: method === 'item/started' ? 'item.started' : 'item.completed', item: translated });
              }
            } else if (method === 'turn/completed' && params.turn?.id === turnId) {
              turnEnded = true;
              steerActive = null;
              const turn = params.turn;
              emit(turn.status === 'completed'
                ? { type: 'turn.completed', usage }
                : { type: 'turn.failed', error: turn.error || { message: `Turn ${turn.status}.` } });
              finish();
            }
          });
          // Prevent an early exit during turn/start from becoming unhandled.
          void completed.catch(() => {});
          try {
            const started = await call('turn/start', { threadId, input: nativeInput(input), effort: options.modelReasoningEffort }) as AnyRecord;
            turnId ||= started?.turn?.id;
            if (!turnId) throw new Error('Codex returned no active turn id.');
            steerActive = turnEnded ? null : async (nextInput, messageId) => {
              const expectedTurnId = turnId;
              pendingMessages.add(messageId);
              try {
                await call('turn/steer', { threadId, expectedTurnId, input: nativeInput(nextInput), clientUserMessageId: messageId });
                return true;
              } catch (error) {
                // An explicit JSON-RPC rejection is safe to queue as a new
                // turn. A lost reply may already have delivered the message.
                if (echoed.has(messageId)) return true;
                const rpcCode = error instanceof AppError ? readObjectRecord(error.details)?.rpcCode : undefined;
                if (typeof rpcCode === 'number' && rpcCode !== -32603) {
                  pendingMessages.delete(messageId);
                  return false;
                }
                throw new AppError('Steer delivery is unknown. Check the transcript before sending it again.', { code: 'STEER_DELIVERY_UNKNOWN', statusCode: 502 });
              }
            };
            await completed;
          } finally {
            steerActive = null;
            offNotification();
            offExit();
          }
        }, signal).catch((error: unknown) => { failure = error; }).finally(() => { done = true; wake?.(); });
        return { events: (async function* () {
          try {
            while (!done || queue.length) {
              if (queue.length) yield queue.shift()!;
              else await new Promise<void>((resolve) => { wake = resolve; });
            }
            if (failure) throw failure;
          } finally {
            await operation;
          }
        })() };
      },
    };
  },
};
