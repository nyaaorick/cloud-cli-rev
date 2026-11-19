# CN25 Claude Code (API-only)

The CN25 manager runs Claude Code through CloudCLI with `CN25_CLAUDE_API_ONLY=1`.

- `relay.py` (`cn25-claude-relay.service`, root): the only reader of the Bifrost key. One Unix socket per role in
  `/run/cn25-claude/`, owned by that role's account. Forwards only `POST /v1/messages` naming the role's pinned
  model to `https://hubs.foliodude.it.com:8443/anthropic/v1/messages`, re-serialized from a strict parse (ambiguous
  keys and gateway routing fields are refused) and with the role's effort set on every request. Logs policy facts only.
- `launch.py`, installed as `/usr/local/libexec/cn25-claude-code/<role>-launch`: starts the fixed CLI `--bare` with
  a fixed environment and a placeholder key, bridging a loopback port that only its own account may use to the
  role's socket. No relay, no session. Account and installer subcommands are refused.
- `manager-role.md`: the manager identity appended to every manager session; no session starts without it.
- `relay.json` → `/etc/cn25-claude-relay.json`: upstream and per-role user/model/effort.

Install (root, on cn25):

```sh
install -o root -g root -m 0644 relay.py manager-role.md /usr/local/libexec/cn25-claude-code/
install -o root -g root -m 0755 launch.py /usr/local/libexec/cn25-claude-code/manager-launch
install -o root -g root -m 0755 launch.py /usr/local/libexec/cn25-claude-code/worker-launch
install -o root -g root -m 0644 relay.json /etc/cn25-claude-relay.json
install -o root -g root -m 0644 cn25-claude-relay.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now cn25-claude-relay.service
```
