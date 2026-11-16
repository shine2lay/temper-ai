import type { OpenVikingClient } from "./client.ts";
import { buildSlotTelemetry, unavailableSlotTelemetry, type L0SkipReason } from "./telemetry.ts";
import {
	DEFAULT_OPENVIKING_URL,
	L0_CARD_HEADER,
	type LeadTurnInput,
	WORKER_CASE_L2_MAX_TOKENS,
	WORKER_PREFETCH_MAX_CHARS,
	WORKER_PREFETCH_MAX_TOKENS,
	WORKER_SPEC_L2_MAX_TOKENS,
	type WorkerTurn1Bundle,
	type WorkerTurn1SlotInput,
	estimateTokens,
	isTestTouchPath,
	resolveCraftPreferences,
	selectInjectionMode,
} from "./types.ts";

export { isTestTouchPath, resolveCraftPreferences, selectInjectionMode };

const SHORT_FOLLOWUP_SET = new Set([
	"yes", "y", "no", "n", "ok", "okay", "k", "sure", "go", "go ahead",
	"do it", "proceed", "continue", "sounds good", "looks good", "lgtm",
	"ship it", "thanks", "thank you", "done", "ack",
]);

export function shouldSkipLeadL0Injection(message: string, touches: readonly string[] = []): boolean {
	if (touches.length > 0) return false;
	const trimmed = message.trim();
	if (!trimmed) return true;
	if (trimmed.startsWith("[Queue]")) return false;
	const normalized = trimmed.toLowerCase().replace(/[.!?,;:]+$/g, "").trim();
	if (SHORT_FOLLOWUP_SET.has(normalized)) return true;
	const hasPathOrUri =
		trimmed.includes("/") ||
		trimmed.includes("viking://") ||
		trimmed.includes(".ts") ||
		trimmed.includes(".py") ||
		trimmed.includes(".md");
	return trimmed.replace(/\s+/g, "").length < 15 && !hasPathOrUri;
}

export const LEAD_L0_MAX_TOKENS = 300;
export const LEAD_L0_MAX_CHARS = LEAD_L0_MAX_TOKENS * 4;

export function buildFoldedL0Card(input: LeadTurnInput): string | null {
	if (shouldSkipLeadL0Injection(input.message, input.touches)) return null;
	const threshold = input.scoreThreshold ?? 0.35;
	const maxItems = input.maxItems ?? 5;
	const matching = input.candidates
		.filter((c) => c.score >= threshold && !input.seenUris.has(c.uri))
		.sort((a, b) => b.score - a.score || a.uri.localeCompare(b.uri));
	if (matching.length === 0) return null;
	for (const c of matching) {
		input.seenUris.add(c.uri);
	}
	const eligible = matching.slice(0, maxItems);

	const prefItems: typeof eligible = [];
	const factItems: typeof eligible = [];
	for (const item of eligible) {
		const isPref = item.isPreference ?? (item.uri.includes("/preferences/") || item.uri.endsWith("/preferences.md"));
		if (isPref) prefItems.push(item);
		else factItems.push(item);
	}

	const renderWithAbstractLimit = (maxAbsChars: number): string => {
		const lines: string[] = [L0_CARD_HEADER];
		if (prefItems.length > 0) {
			lines.push("Preferences (L0):");
			for (const item of prefItems) {
				lines.push(`- ${item.uri} — ${item.abstract.replace(/\s+/g, " ").trim().slice(0, maxAbsChars)}`);
			}
		}
		if (factItems.length > 0) {
			if (prefItems.length > 0) lines.push("Project Facts & Specs (L0):");
			for (const item of factItems) {
				lines.push(`- ${item.uri} — ${item.abstract.replace(/\s+/g, " ").trim().slice(0, maxAbsChars)}`);
			}
		}
		return lines.join("\n");
	};

	let card = renderWithAbstractLimit(256);
	if (estimateTokens(card) > LEAD_L0_MAX_TOKENS) {
		card = renderWithAbstractLimit(120);
	}
	if (card.length > LEAD_L0_MAX_CHARS) {
		card = card.slice(0, LEAD_L0_MAX_CHARS);
	}
	return card;
}

export function buildWorkerTurn1Bundle(input: WorkerTurn1SlotInput): WorkerTurn1Bundle {
	if (input.serverError) {
		const banner = [
			`[OpenViking Worker Pre-Fetch UNAVAILABLE · server ${input.serverUrl ?? DEFAULT_OPENVIKING_URL} unreachable/timeout (${input.serverError})]`,
			"Turn-1 pre-fetch did NOT run (this does NOT mean project docs or role memories are absent). Use read/grep on local repo and .temper/ files directly; do not call viking_find/viking_read on Turn 1.",
		].join("\n");
		return {
			mode: "worker_turn1",
			text: banner,
			preferencesSection: "",
			factsAndSpecsSection: "",
			estTokens: estimateTokens(banner),
			injectedUris: [],
			degradedSlots: [],
			droppedSlots: [],
			degradedToLocalFallback: true,
			slots: unavailableSlotTelemetry(),
		};
	}

	const injectedUris: string[] = [];
	const degradedSlots: string[] = [];
	const droppedSlots: string[] = [];
	const prefs = resolveCraftPreferences(input.role, input.touches, input.project);

	const prefLines: string[] = ["[Preferences: Role & Domain] · [Preferences: Role & Craft]"];
	if (input.personalPreferencesContent) {
		injectedUris.push(prefs.personalUri);
		prefLines.push(`- Personal Role Preferences (${prefs.personalUri}): ${input.personalPreferencesContent.trim()}`);
	} else {
		prefLines.push(`- [Personal Role Preferences (${input.role}): NOT FOUND at ${prefs.personalUri}]`);
	}
	for (const file of prefs.craftFiles) {
		const uri = `viking://user/memories/preferences/${file}`;
		const body = input.craftPreferenceContents?.[file];
		if (body) {
			injectedUris.push(uri);
			prefLines.push(`- Craft Preference (${uri}): ${body.trim()}`);
		} else {
			prefLines.push(`- [Craft Preference: ${uri} (routed)]`);
		}
	}
	// OpenViking v2 (§3.1): instructions and craft arrive in the always-injected block instead.
	const preferencesSection = input.omitPreferenceSlots ? "" : prefLines.join("\n");

	const project = input.project;
	const slot1Uri = project ? `viking://resources/${project}/.overview.md` : null;
	const slot2Uri = project ? `viking://user/memories/entities/${project}.md` : null;

	const slot1Line = project
		? input.projectOverviewL1
			? (injectedUris.push(slot1Uri!), `### Slot 1 — Project L1 Overview (${slot1Uri})\n${input.projectOverviewL1.trim()}`)
			: `- [Slot 1 project L1 overview: NOT INDEXED at ${slot1Uri} — read .temper/core/map.md on disk]`
		: "- [Slot 1 project L1 overview: skipped (no project slug)]";

	const slot2Line = project
		? input.sharedEntityL1
			? (injectedUris.push(slot2Uri!), `### Slot 2 — Shared Entity State (${slot2Uri})\n${input.sharedEntityL1.trim()}`)
			: `- [Slot 2 shared entity status: NOT FOUND at ${slot2Uri}]`
		: "- [Slot 2 shared entity status: skipped (no project slug)]";

	let specLevel: "L2" | "L1" = "L2";
	if (input.matchingSpec) {
		injectedUris.push(input.matchingSpec.uri);
		if (estimateTokens(input.matchingSpec.l2Content) > WORKER_SPEC_L2_MAX_TOKENS) {
			specLevel = "L1";
			degradedSlots.push("slot3:spec_l2_to_l1");
		}
	}

	type CaseRender = { uri: string; level: "L2" | "L1"; l2Content: string; l1Overview: string };
	const activeCases: CaseRender[] = (input.personalCases ?? []).slice(0, 2).map((c) => {
		injectedUris.push(c.uri);
		const level: "L2" | "L1" = estimateTokens(c.l2Content) <= WORKER_CASE_L2_MAX_TOKENS ? "L2" : "L1";
		return { uri: c.uri, level, l2Content: c.l2Content, l1Overview: c.l1Overview };
	});

	const activeSiblings = [...(input.siblingDocsL0 ?? [])].slice(0, 8);
	for (const sib of activeSiblings) injectedUris.push(sib.uri);

	// One rendered string per slot (1..5), in order; the facts section joins them.
	const renderSlotParts = (): string[] => {
		const parts: string[] = [slot1Line, slot2Line];
		if (input.matchingSpec) {
			const specBody =
				specLevel === "L2"
					? input.matchingSpec.l2Content.trim()
					: `[L2 > 2,000 tokens -> degraded to L1 overview; call viking_read(uri, level="full") if full text needed]\n${input.matchingSpec.l1Overview.trim()}`;
			parts.push(`### Slot 3 — Top Matching Spec (${input.matchingSpec.uri} · ${specLevel})\n${specBody}`);
		} else {
			parts.push(`- [Slot 3 top matching spec: 0 hits >= 0.35 in viking://resources/${project ?? "unknown"}/ — inspect .temper/features/ on disk]`);
		}

		if (activeCases.length > 0) {
			const caseLines = activeCases.map((c) => `- ${c.uri} (${c.level}): ${(c.level === "L2" ? c.l2Content : c.l1Overview).trim()}`);
			parts.push(`### Slot 4 — Personal Role Cases & Experiences (${input.role})\n${caseLines.join("\n")}`);
		} else {
			parts.push(`- [Slot 4 personal role memories (${input.role}): 0 hits >= 0.35 in viking://agent/memories/]`);
		}

		if (activeSiblings.length > 0) {
			const sibLines = activeSiblings.map((s) => `- ${s.uri} — ${s.abstract.replace(/\s+/g, " ").trim().slice(0, 256)}`);
			parts.push(`${L0_CARD_HEADER}\n${sibLines.join("\n")}`);
		} else {
			parts.push("- [Slot 5 sibling project docs: none beyond slots above]");
		}
		return parts;
	};
	const renderFactsSection = (): string => ["[Facts & Specs: Project & Cases]", ...renderSlotParts()].join("\n\n");

	const totalTokens = (): number => estimateTokens(`${preferencesSection}\n\n${renderFactsSection()}`);

	if (totalTokens() > WORKER_PREFETCH_MAX_TOKENS && input.matchingSpec && specLevel === "L2") {
		specLevel = "L1";
		if (!degradedSlots.includes("slot3:spec_l2_to_l1")) degradedSlots.push("slot3:spec_l2_to_l1");
	}
	while (totalTokens() > WORKER_PREFETCH_MAX_TOKENS && activeSiblings.length > 0) {
		const removed = activeSiblings.pop()!;
		droppedSlots.push(`slot5:${removed.uri}`);
	}
	if (totalTokens() > WORKER_PREFETCH_MAX_TOKENS && activeCases.length > 0) {
		for (const c of activeCases) {
			if (c.level === "L2") {
				c.level = "L1";
				degradedSlots.push(`slot4:${c.uri}:l2_to_l1`);
			}
		}
	}
	while (totalTokens() > WORKER_PREFETCH_MAX_TOKENS && activeCases.length > 0) {
		const removed = activeCases.pop()!;
		droppedSlots.push(`slot4:${removed.uri}`);
	}

	const factsAndSpecsSection = renderFactsSection();
	const slotText = renderSlotParts();
	// Slots 1, 2, 3 and 5 all search `viking://resources/<project>/`. With no slug nothing is
	// looked up, so they are `skipped`; a `miss` would claim the namespace was searched and empty.
	const noSlug = project ? undefined : ("skipped" as const);
	const slots = buildSlotTelemetry([
		{ state: noSlug, uris: project && input.projectOverviewL1 ? [slot1Uri!] : [], expanded: 1, text: slotText[0] },
		{ state: noSlug, uris: project && input.sharedEntityL1 ? [slot2Uri!] : [], expanded: 1, text: slotText[1] },
		{ state: noSlug, uris: input.matchingSpec ? [input.matchingSpec.uri] : [], expanded: 1, text: slotText[2] },
		{ uris: activeCases.map((c) => c.uri), expanded: activeCases.length, text: slotText[3] },
		{ state: noSlug, uris: activeSiblings.map((s) => s.uri), expanded: 0, text: slotText[4] },
	]);
	let combined = preferencesSection ? `${preferencesSection}\n\n${factsAndSpecsSection}` : factsAndSpecsSection;
	if (combined.length > WORKER_PREFETCH_MAX_CHARS) {
		const notice = '\n[truncated at 3,000-token worker budget; call viking_read(uri, level="full")]';
		combined = combined.slice(0, WORKER_PREFETCH_MAX_CHARS - notice.length) + notice;
	}

	return {
		mode: "worker_turn1",
		text: combined,
		preferencesSection,
		factsAndSpecsSection,
		estTokens: estimateTokens(combined),
		injectedUris: Array.from(new Set(injectedUris)),
		degradedSlots,
		droppedSlots,
		degradedToLocalFallback: false,
		slots,
	};
}

export async function fetchLeadFoldedL0Card(
	client: OpenVikingClient,
	params: {
		message: string;
		role?: string;
		project?: string | null;
		touches?: string[];
		seenUris: Set<string>;
		scoreThreshold?: number;
		maxItems?: number;
		/** Keeps a hit on the card; OpenViking v2 drops preference files and what the chat may not read. */
		candidateFilter?: (uri: string) => boolean;
		onDecision?: (decision: { reason?: L0SkipReason; uris?: string[] }) => void;
	},
): Promise<string | null> {
	if (shouldSkipLeadL0Injection(params.message, params.touches)) {
		params.onDecision?.({ reason: "short_followup" });
		return null;
	}
	try {
		const searchQuery = [params.message, ...(params.touches ?? [])].join(" ").trim();
		const findRes = await client.find({
			query: searchQuery,
			scope: params.role ? "all" : "shared",
			role: params.role,
			limit: 8,
			score_threshold: params.scoreThreshold,
		});
		const candidates = findRes.hits.filter((hit) => params.candidateFilter?.(hit.uri) ?? true).map((hit) => ({
			uri: hit.uri,
			abstract: hit.abstract,
			score: hit.score,
			isPreference: hit.uri.includes("/preferences/") || hit.uri.endsWith("/preferences.md"),
		}));
		const card = buildFoldedL0Card({
			message: params.message,
			role: params.role,
			project: params.project ?? undefined,
			touches: params.touches,
			candidates,
			seenUris: params.seenUris,
			scoreThreshold: params.scoreThreshold,
			maxItems: params.maxItems,
		});
		params.onDecision?.(card
			? { uris: candidates.filter((c) => card.includes(c.uri)).map((c) => c.uri) }
			: { reason: "nothing_new" });
		return card;
	} catch {
		params.onDecision?.({ reason: "server_unavailable" });
		return null;
	}
}

export async function fetchWorkerTurn1Bundle(
	client: OpenVikingClient,
	params: {
		role: string;
		project: string | null;
		touches: string[];
		taskPrompt: string;
		scoreThreshold?: number;
		omitPreferenceSlots?: boolean;
	},
): Promise<WorkerTurn1Bundle> {
	try {
		await client.health();
	} catch (err) {
		return buildWorkerTurn1Bundle({
			role: params.role,
			project: params.project,
			touches: params.touches,
			taskPrompt: params.taskPrompt,
			serverError: err instanceof Error ? err.message : String(err),
			serverUrl: client.baseUrl,
		});
	}

	const prefs = resolveCraftPreferences(params.role, params.touches, params.project);
	const tryRead = async (uri: string, level: "overview" | "full", role?: string): Promise<string | null> => {
		try {
			const res = await client.read({ uri, level, role });
			return res.content.trim() || null;
		} catch {
			return null;
		}
	};

	const [personalPreferencesContent, craftEntries] = params.omitPreferenceSlots
		? ([null, []] as [string | null, Array<readonly [string, string | null]>])
		: await Promise.all([
			tryRead(prefs.personalUri, "full", params.role),
			Promise.all(
				prefs.craftFiles.map(async (file) => {
					const content = await tryRead(`viking://user/memories/preferences/${file}`, "full");
					return [file, content] as const;
				}),
			),
		]);

	const craftPreferenceContents: Record<string, string> = {};
	for (const [file, content] of craftEntries) {
		if (content) craftPreferenceContents[file] = content;
	}

	const project = params.project;
	const [projectOverviewL1, sharedEntityL1] = project
		? await Promise.all([
				tryRead(`viking://resources/${project}/.overview.md`, "overview"),
				tryRead(`viking://user/memories/entities/${project}.md`, "overview"),
			])
		: [null, null];

	const queryText = [params.taskPrompt, ...params.touches].join(" ").trim() || project || params.role;
	const threshold = params.scoreThreshold ?? 0.25;

	let matchingSpec: WorkerTurn1SlotInput["matchingSpec"] = null;
	const siblingDocsL0: NonNullable<WorkerTurn1SlotInput["siblingDocsL0"]> = [];

	if (project) {
		try {
			const resSearch = await client.find({
				query: queryText,
				scope: "shared",
				target_uri: `viking://resources/${project}`,
				limit: 8,
			});
			const queryTerms = queryText
				.toLowerCase()
				.split(/[^a-z0-9]+/)
				.filter((w) => w.length >= 4 && w !== "rollcall" && w !== "task" && w !== "queue");
			const docHits = resSearch.hits
				.filter(
					(h) =>
						!h.uri.endsWith("/.overview.md") &&
						!h.uri.endsWith("/.abstract.md") &&
						!h.uri.endsWith("/design/app.md") &&
						h.score >= threshold,
				)
				.sort((a, b) => {
					const aMatch = queryTerms.filter((t) => a.uri.toLowerCase().includes(t)).length;
					const bMatch = queryTerms.filter((t) => b.uri.toLowerCase().includes(t)).length;
					return bMatch * 0.15 + b.score - (aMatch * 0.15 + a.score);
				});
			if (docHits.length > 0) {
				const topHit = docHits[0];
				const [l2Content, l1Overview] = await Promise.all([
					tryRead(topHit.uri, "full"),
					tryRead(topHit.uri, "overview"),
				]);
				if (l2Content) {
					matchingSpec = {
						uri: topHit.uri,
						l2Content,
						l1Overview: l1Overview ?? topHit.abstract,
						score: topHit.score,
					};
				}
				for (const sib of docHits.slice(1, 7)) {
					siblingDocsL0.push({ uri: sib.uri, abstract: sib.abstract, score: sib.score });
				}
			}
		} catch {
			// Leave slot 3 & 5 empty on search failure so R-FAIL-4 markers render
		}
	}

	const personalCases: NonNullable<WorkerTurn1SlotInput["personalCases"]> = [];
	try {
		const personalSearch = await client.find({
			query: queryText,
			scope: "personal",
			role: params.role,
			limit: 6,
		});
		const caseHits = personalSearch.hits
			.filter(
				(h) =>
					(h.uri.includes("/cases/") || h.uri.includes("/experiences/")) &&
					!h.uri.endsWith("/.overview.md") &&
					!h.uri.endsWith("/.abstract.md") &&
					h.score >= threshold,
			)
			.slice(0, 2);
		for (const hit of caseHits) {
			const [l2Content, l1Overview] = await Promise.all([
				tryRead(hit.uri, "full", params.role),
				tryRead(hit.uri, "overview", params.role),
			]);
			if (l2Content) {
				personalCases.push({
					uri: hit.uri,
					l2Content,
					l1Overview: l1Overview ?? hit.abstract,
					score: hit.score,
				});
			}
		}
	} catch {
		// Leave slot 4 empty on search failure so R-FAIL-4 marker renders
	}

	return buildWorkerTurn1Bundle({
		role: params.role,
		project,
		touches: params.touches,
		taskPrompt: params.taskPrompt,
		personalPreferencesContent,
		craftPreferenceContents,
		projectOverviewL1,
		sharedEntityL1,
		matchingSpec,
		personalCases,
		siblingDocsL0,
		omitPreferenceSlots: params.omitPreferenceSlots,
	});
}
