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
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

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
