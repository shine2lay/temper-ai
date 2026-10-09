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
// - One exception to "unsettled", in a team member's box only (TEMPER_BOX_TEAM=1): a team
//   message Temper hands into the member's running turn. It arrives over RPC as a steer (Pi
//   queues it after the current tool calls, before the next model call) and its text starts
//   with TEAM_MESSAGE_PREFIX. Identity, tools and helper checks still apply; an image with it
//   is refused. Temper checks afterwards that each handed message is in the session file.
//   A refused handed message writes no marker: it came after the prompt went in, so it never
//   says the prompt was refused. Temper finds it missing from the session file.
// - Command "/temper-box-rewind <entry id>" moves the active branch back to a settled entry in
//   the same session file (after the owner decided about a cut-off turn).
// - In a team member's box only (TEMPER_BOX_TEAM=1): the "send_message" tool. It writes the
//   message to the box's team socket and shows Temper's answer. The socket is bound by Temper
//   to this member's running turn, so the tool sends no identity and no token: who sent a
//   message is Temper's to say. Pi activates the tool only when --tools names it.
// - Also in a team member's box: the free-flowing team's tools (FLOW F3/F4), over the same
//   socket: "share" (put your work into the team's shared version), "idle" (nothing more for
//   you now; a message wakes you) and the leader's "done" (the shared version is the result).
//   Each records a request with Temper for this turn; Temper carries it out once the turn has
//   finished, and decides who may use which (it refuses a call from the wrong member). Pi
//   activates only the ones --tools names, so a member sees only its own.
import { Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createConnection } from "node:net";
import { dirname, join } from "node:path";

const TEAM_SOCKET = "/box-sock/team.sock";
const TEAM_TIMEOUT_MS = 30000;
// The text a team message handed into a running turn starts with. The host's turn runner
// (temper_ai/pi_agent/turn.py) reads this exact line, so it stays one line and one plain
// double-quoted string: one constant for both sides.
const TEAM_MESSAGE_PREFIX = "[temper:team-message] ";

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
        "Send a message to another member of your team, through Temper. It reaches them once " +
        "your turn has finished (in their running turn if they are working). Members you can message: " +
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
            ". It reaches them after this turn finishes."
          : `Not sent (${reply?.code ?? "invalid_channel"}): ${reply?.detail ?? ""}`;
        return {
          content: [{ type: "text" as const, text }],
          details: { ok: !!reply?.ok, code: reply?.code ?? null, message_id: reply?.message_id ?? null },
        };
      },
    });

    // The team's own tools. Temper's answer says what it recorded; nothing happens until this
    // turn has finished.
    const teamCall = async (op: string, toolCallId: string, params: any, keys: string[]) => {
      const payload: Record<string, unknown> = { op, client_msg_id: String(toolCallId).slice(0, 128) };
      for (const key of keys) {
        if (params?.[key] !== undefined && params?.[key] !== null) payload[key] = params[key];
      }
      const reply = await teamSend(payload);
      const text = reply?.ok
        ? String(reply.detail ?? "Recorded.") +
          (reply.duplicate ? " (already recorded: the same request, recorded once)" : "")
        : `Not recorded (${reply?.code ?? "invalid_channel"}): ${reply?.detail ?? ""}`;
      return {
        content: [{ type: "text" as const, text }],
        details: { ok: !!reply?.ok, code: reply?.code ?? null, act_id: reply?.act_id ?? null },
      };
    };
    pi.registerTool({
      name: "share",
      label: "Share",
      description:
        "Put your work into the team's shared version, as your project copy is when this " +
        "turn finishes. Temper commits your copy and merges it into the shared version; if " +
        "it conflicts, your copy keeps git's conflict markers and the files are named to you " +
        "at your next turn: fix them and share again. Sharing wakes nobody: tell the members " +
        "who need it with send_message.",
      parameters: Type.Object({
        note: Type.Optional(Type.String({ description: "What changed, in a sentence" })),
      }),
      async execute(toolCallId: string, params: any) {
        return teamCall("share", toolCallId, params, ["note"]);
      },
    });
    pi.registerTool({
      name: "idle",
      label: "Idle",
      description:
        "Nothing more is yours to do now: stop after this turn. A message to you wakes you " +
        "again. Without it you keep working, turn after turn.",
      parameters: Type.Object({
        note: Type.Optional(Type.String({ description: "Why, or what you wait for" })),
      }),
      async execute(toolCallId: string, params: any) {
        return teamCall("idle", toolCallId, params, ["note"]);
      },
    });
    pi.registerTool({
      name: "done",
      label: "Done",
      description:
        "The leader's: the team's shared version is the result. Temper shares your copy, lets " +
        "running turns finish, and counts done only if the shared version is then exactly " +
        "your copy and nothing new reached you after this done call; otherwise you get one " +
        "more turn with what came in.",
      parameters: Type.Object({
        summary: Type.String({ description: "A short summary of the result" }),
      }),
      async execute(toolCallId: string, params: any) {
        return teamCall("done", toolCallId, params, ["summary"]);
      },
    });
  }

  pi.on("input", (event, ctx) => {
    const now = state(ctx);
    const same = now.identity_id === role && !now.helper_env &&
      JSON.stringify(now.active_tools) === JSON.stringify(tools);
    // Temper's team message in a team member's box, over RPC...
    const handed = process.env.TEMPER_BOX_TEAM === "1" && event.source === "rpc" &&
      typeof event.text === "string" && event.text.startsWith(TEAM_MESSAGE_PREFIX);
    // ...is the one input let in while the branch is unsettled (mid-turn), as a steer.
    const teamSteer = handed && event.streamingBehavior === "steer" &&
      !(event.images && event.images.length);
    const allowed = same && (now.branch_settled || teamSteer);
    if (allowed) return { action: "continue" };
    if (handed) return { action: "handled" };  // refused, no marker (see the top)
    write(blockedOut, { blocked: true, identity_id: now.identity_id, branch_settled: now.branch_settled,
      active_tools: now.active_tools, expected_tools: tools, before_provider: true });
    return { action: "handled" };
  });
}
