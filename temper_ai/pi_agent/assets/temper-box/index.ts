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
// - Also in a team member's box: the review tools of the leader loop (task #38), over the same
//   socket: "request_review" and "decide" (the leader's) and "give_view" (a reviewer's). Each
//   records a request with Temper for this turn; Temper carries it out once the turn has
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

    // The leader loop's review tools. Temper's answer says what it recorded; nothing happens
    // until this turn has finished.
    const reviewCall = async (op: string, toolCallId: string, params: any, keys: string[]) => {
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
      name: "request_review",
      label: "Request review",
      description:
        "Ask the other members to review your work as it is when this turn finishes. Temper " +
        "commits your project copy, gives every reviewer exactly that version, and brings " +
        "you their views (satisfied or changes, with a note).",
      parameters: Type.Object({
        note: Type.Optional(Type.String({ description: "What to look at, in a sentence or two" })),
      }),
      async execute(toolCallId: string, params: any) {
        return reviewCall("request_review", toolCallId, params, ["note"]);
      },
    });
    pi.registerTool({
      name: "give_view",
      label: "Give view",
      description:
        "Give your view on the version under review: satisfied, or changes (say which in " +
        "the note). Name the review by the id in the review request.",
      parameters: Type.Object({
        review_id: Type.String({ description: "The review's id, from the review request" }),
        verdict: Type.String({ description: "satisfied or changes" }),
        note: Type.String({ description: "A short note: what is good, or what to change" }),
      }),
      async execute(toolCallId: string, params: any) {
        return reviewCall("give_view", toolCallId, params, ["review_id", "verdict", "note"]);
      },
    });
    pi.registerTool({
      name: "decide",
      label: "Decide",
      description:
        "After the views of a review have reached you: done (the reviewed version is the " +
        "result) or keep_going (another round). Done counts only if your copy is still " +
        "exactly the reviewed version and nothing new has reached you since this turn began.",
      parameters: Type.Object({
        review_id: Type.String({ description: "The review's id" }),
        decision: Type.String({ description: "done or keep_going" }),
        summary: Type.String({ description: "A short summary of the result or of what comes next" }),
      }),
      async execute(toolCallId: string, params: any) {
        return reviewCall("decide", toolCallId, params, ["review_id", "decision", "summary"]);
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
