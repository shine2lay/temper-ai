// Temper Pi worker box probe: lets the host check, before any model call, that the worker is
// the role it was started as, with exactly the tools it was launched with.
//
// - Command "/temper-box-state" writes public metadata (never prompts, messages or tool schemas)
//   to TEMPER_BOX_STATE_OUT: mode, UI flag, session id, the identity pi-identity reports, the
//   identity entries in the session, the active tools and the role notebook's sha256.
// - An input guard refuses any non-command prompt (no model call happens) while the identity or
//   the active tools differ from TEMPER_BOX_ROLE / TEMPER_BOX_TOOLS, or the session's active
//   branch ends unsettled, and writes a marker file the host reads. Extension commands never
//   reach input handlers, so binding still works.
// - Command "/temper-box-rewind <entry id>" moves the active branch back to a settled entry in
//   the same session file (after the owner decided about a cut-off turn).
// - In a team member's box only (TEMPER_BOX_TEAM=1): the "send_message" tool. It writes the
//   message to the box's team socket and shows Temper's answer. The socket is bound by Temper
//   to this member's running turn, so the tool sends no identity and no token: who sent a
//   message is Temper's to say. Pi activates the tool only when --tools names it.
import { Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createConnection } from "node:net";
import { dirname, join } from "node:path";

const TEAM_SOCKET = "/box-sock/team.sock";
const TEAM_TIMEOUT_MS = 30000;

// One send: one JSON line out, one JSON line back.
const teamSend = (payload: Record<string, unknown>): Promise<any> =>
  new Promise((resolve) => {
    const conn = createConnection({ path: TEAM_SOCKET });
    let buf = "";
    let done = false;
    const finish = (value: any) => {
      if (done) return;
      done = true;
      conn.destroy();
      resolve(value);
    };
    conn.setTimeout(TEAM_TIMEOUT_MS, () =>
      finish({ ok: false, code: "invalid_channel", detail: "Temper did not answer in time" }));
    conn.on("connect", () => conn.write(JSON.stringify(payload) + "\n"));
    conn.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      const end = buf.indexOf("\n");
      if (end < 0) return;
      try {
        finish(JSON.parse(buf.slice(0, end)));
      } catch {
        finish({ ok: false, code: "invalid_channel", detail: "Temper's answer was unreadable" });
      }
    });
    conn.on("error", () =>
      finish({ ok: false, code: "invalid_channel", detail: "the team channel is closed" }));
    conn.on("close", () =>
      finish({ ok: false, code: "invalid_channel", detail: "the team channel is closed" }));
  });

export default function (pi: ExtensionAPI) {
  const out = process.env.TEMPER_BOX_STATE_OUT || "/w/state/box-state.json";
  const blockedOut = join(dirname(out), "box-blocked.json");
  const rewindOut = join(dirname(out), "box-rewind.json");
  const role = process.env.TEMPER_BOX_ROLE || "";
  const tools = (process.env.TEMPER_BOX_TOOLS || "").split(",").filter(Boolean).sort();
  const identityDir = process.env.PI_IDENTITY_DIR || "";

  const write = (path: string, value: unknown) => {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify(value) + "\n", { mode: 0o600 });
  };
  const identityOf = (ctx: ExtensionContext): any => {
    let answer: any;
    pi.events.emit("pi-identity:ask", {
      sessionId: ctx.sessionManager.getSessionId(), ctx,
      reply: (value: any) => { answer = value; },
    });
    return answer;
  };
  const notebookSha = (id: string): string | null => {
    if (!identityDir || !/^[A-Za-z0-9._-]+$/.test(id)) return null;
    try {
      return createHash("sha256").update(readFileSync(join(identityDir, id, "notebook.md"))).digest("hex");
    } catch {
      return null;
    }
  };
  // The active branch ends settled when its last message is a finished assistant answer (or
  // there is none yet): a turn cut off mid-way leaves an unanswered prompt or tool call.
  const branchSettled = (ctx: ExtensionContext): boolean => {
    const msgs = ctx.sessionManager.getBranch().filter((e: any) => e.type === "message");
    const last: any = msgs.length ? msgs[msgs.length - 1] : null;
    return !last || (last.message?.role === "assistant" &&
      ["stop", "error", "aborted", "length"].includes(last.message?.stopReason));
  };
  const state = (ctx: ExtensionContext) => {
    const ident = identityOf(ctx);
    const id: string | null = ident?.id ?? null;
    return {
      v: 1, mode: ctx.mode, has_ui: ctx.hasUI,
      session_id: ctx.sessionManager.getSessionId(),
      leaf_id: ctx.sessionManager.getLeafId(), branch_settled: branchSettled(ctx),
      identity_id: id, identity_via: ident?.via ?? null,
      identity_entries: ctx.sessionManager.getBranch()
        .filter((e: any) => e.type === "custom" && e.customType === "identity")
        .map((e: any) => ({ id: e.data?.id ?? null, via: e.data?.via ?? null })),
      active_tools: [...pi.getActiveTools()].sort(),
      notebook_sha256: id ? notebookSha(id) : null,
      helper_env: process.env.PI_SUBAGENT_CHILD === "1",
    };
  };

  pi.registerCommand("temper-box-state", {
    description: "Write the worker box's role and tool metadata for the Temper host",
    handler: async (_args, ctx) => {
      write(out, state(ctx));
    },
  });

  // After the owner decided about a cut-off turn: move the session's active branch back to
  // the last settled entry, in the same session file (the cut-off branch stays in the file).
  // No summary, so no model call.
  pi.registerCommand("temper-box-rewind", {
    description: "Move the session back to its last settled entry (Temper host only)",
    handler: async (args, ctx) => {
      const target = String(args || "").trim();
      let cancelled = true;
      let error: string | null = null;
      try {
        cancelled = !!(await ctx.navigateTree(target, { summarize: false })).cancelled;
      } catch {
        error = "navigate_failed";
      }
      write(rewindOut, { v: 1, target, cancelled, error, leaf_id: ctx.sessionManager.getLeafId(),
        branch_settled: branchSettled(ctx) });
    },
  });

  if (process.env.TEMPER_BOX_TEAM === "1") {
    let members: string[] = [];
    try {
      const parsed = JSON.parse(process.env.TEMPER_BOX_TEAM_MEMBERS || "[]");
      if (Array.isArray(parsed)) members = parsed.map(String);
    } catch {
      members = [];
    }
    pi.registerTool({
      name: "send_message",
      label: "Send message",
      description:
        "Send a message to another member of your team, through Temper. It reaches them at " +
        "their next turn, once your turn has finished. Members you can message: " +
        (members.length ? members.join(", ") : "(none)") + ". kind: work_request (asks " +
        "for work), info (for their information) or reply (answers a message you received: " +
        "set in_reply_to to its id; it goes back to its sender).",
      parameters: Type.Object({
        to: Type.Optional(Type.String({ description: "The member's team name (not needed for a reply)" })),
        kind: Type.String({ description: "work_request, info or reply" }),
        body: Type.String({ description: "The message" }),
        in_reply_to: Type.Optional(Type.String({ description: "For a reply: the id of the message it answers" })),
        outcome: Type.Optional(Type.String({ description: "For a reply: answered (default) or declined" })),
      }),
      async execute(toolCallId: string, params: any) {
        const payload: Record<string, unknown> = { client_msg_id: String(toolCallId).slice(0, 128) };
        for (const key of ["to", "kind", "body", "in_reply_to", "outcome"]) {
          if (params?.[key] !== undefined && params?.[key] !== null) payload[key] = params[key];
        }
        const reply = await teamSend(payload);
        const text = reply?.ok
          ? `Sent message ${reply.message_id} to ${reply.to}` +
            (reply.duplicate ? " (already sent: the same message, sent once)" : "") +
            ". It reaches them at their next turn, after this turn finishes."
          : `Not sent (${reply?.code ?? "invalid_channel"}): ${reply?.detail ?? ""}`;
        return {
          content: [{ type: "text" as const, text }],
          details: { ok: !!reply?.ok, code: reply?.code ?? null, message_id: reply?.message_id ?? null },
        };
      },
    });
  }

  pi.on("input", (_event, ctx) => {
    const now = state(ctx);
    const allowed = now.identity_id === role && !now.helper_env && now.branch_settled &&
      JSON.stringify(now.active_tools) === JSON.stringify(tools);
    if (allowed) return { action: "continue" };
    write(blockedOut, { blocked: true, identity_id: now.identity_id, branch_settled: now.branch_settled,
      active_tools: now.active_tools, expected_tools: tools, before_provider: true });
    return { action: "handled" };
  });
}
