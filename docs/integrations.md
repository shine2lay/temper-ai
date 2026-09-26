# Integrations — connecting temper to third-party services

Temper reaches outside services through MCP servers. A server is one YAML
file in `configs/mcp_servers/`; its tools then appear to agents as
`<server>.<tool>` and are declared in an agent's `tools:` list like any
built-in.

Nothing connects at startup. A configured server costs nothing until an
agent actually calls one of its tools, so a hundred configured integrations
still means zero subprocesses and zero sockets on a run that uses none of
them.

## The three kinds of server

| Kind | When to use it | Credential |
|---|---|---|
| `transport: stdio` | The integration ships a local server you run as a subprocess | Usually an API token in `env:` |
| `transport: http` + `headers:` | Remote server that takes a long-lived API token | Static header, from the environment |
| `transport: http` + `auth: oauth` | Remote server behind an authorization flow | Authorized once, stored, refreshed automatically |
| `transport: http` + `auth: client_credentials` | Remote server where temper should act as its own app, not as a person | Client id and secret from the environment; no login |

Linear uses the last kind, and also sends temper webhooks that start
workflows: see [linear.md](linear.md). Slack is not an MCP server: temper
runs its own Slack bot for commands, notices and gate buttons; see
[slack.md](slack.md).

### stdio

```yaml
mcp_server:
  name: git
  transport: stdio
  command: uvx
  args: ["mcp-server-git", "--repository", "${GIT_WORKSPACE:/workspace}"]
```

`${VAR:default}` is substituted from the environment when the config loads.
`LD_PRELOAD`, `LD_LIBRARY_PATH`, `DYLD_INSERT_LIBRARIES` and `PYTHONPATH` are
stripped from `env:` — a server config should not be a way to inject code
into the subprocess.

### HTTP with a static token

```yaml
mcp_server:
  name: example
  transport: http
  url: https://mcp.example.com/mcp
  headers:
    Authorization: "Bearer ${EXAMPLE_API_TOKEN}"
```

### HTTP with OAuth

```yaml
mcp_server:
  name: notion
  transport: http
  url: https://mcp.notion.com/mcp
  auth: oauth
```

Then, once, on a machine with a browser:

```bash
temper connect notion
```

That is the only interactive step. It opens the provider's consent screen,
completes the authorization code exchange with PKCE, and stores the grant.
Every run afterwards — CLI, API server, container worker — refreshes the
access token on its own and never needs a human.

Optional keys: `scope:` to request specific scopes, and `callback_port:` if
8765 is taken on your machine.

### When the browser is on another machine

`temper connect` listens on `localhost:8765` for the redirect, which only
works if the browser can reach *this* host. On a headless or remote box it
cannot, so either forward the port:

```bash
ssh -L 8765:localhost:8765 you@your-box
```

or skip the listener entirely:

```bash
temper connect notion --manual
```

Manual mode prints the authorization URL, you approve it in any browser, the
redirect fails harmlessly, and you paste that failed URL back at the prompt.
Nothing listens on a port. Paste the whole URL — the code is percent-encoded
in the address bar and temper decodes it for you.

## Managing connections

```bash
temper connect notion            # authorize once
temper connect notion --manual   # ... when the browser is on another machine
temper connections               # what is configured, and what is authorized
temper disconnect notion         # forget the stored grant
```

`temper connect` finishes by listing the server's tools, so a success means
the grant was actually used, not merely written.

`temper disconnect` deletes temper's copy of the grant. It does **not**
revoke access at the provider — do that in the provider's own connection
settings if that is what you mean.

## Where the grant lives

In the `mcp_credentials` table, encrypted. A refresh token is a standing key
to someone's workspace, and a database is shared infrastructure that gets
dumped, replicated and backed up; plaintext there would outlive anyone's
intention to clean it up.

The sealing key is resolved in this order:

1. `TEMPER_SECRET_KEY`
2. `~/.temper/secret.key`, created `0600` on first use

A laptop needs no setup. A deployment should pin `TEMPER_SECRET_KEY` so the
key survives container rebuilds and is the same across replicas:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

If the key is missing, changed, or the row was sealed by a different
deployment, the grant reads as **not connected** — it never falls back to
plaintext and never raises out of a tool call. `temper connections` says
which case it is, and the fix is always `temper connect <server>` again.

Re-pointing an existing server name at a different `url` also invalidates the
stored grant: same name, different resource, different consent.

## Running unattended

An agent run never opens a browser. If a server needs authorization and none
is stored, the tool call fails with a message naming the command to run,
rather than hanging on a callback that cannot arrive on a headless worker.

For containers, either mount the key or — better — set `TEMPER_SECRET_KEY`
in the environment. The grant itself travels in the database, so a worker
needs no credential files.

## Adding a new OAuth integration

For a server that supports dynamic client registration, the whole
integration is the YAML file. Check first:

```bash
curl -s https://mcp.example.com/.well-known/oauth-authorization-server | jq
```

A `registration_endpoint` means there is no OAuth app to create by hand, and
`refresh_token` in `grant_types_supported` means the authorization survives
without a human. Both are true of Notion.

## Notes

- Tool names are `<server>.<tool>`; an agent only sees the ones it declares.
- A server that answers `initialize` but not `tools/list` fails at connect
  time rather than handing a model a placeholder schema at prompt time.
- Per-agent tool scoping still applies: declaring `notion.search` on one
  agent does not make it callable from another.
