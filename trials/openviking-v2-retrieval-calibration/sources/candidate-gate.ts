// OpenViking v2 §5c.5: the candidate gate. A pair is a candidate only when cosine >= simLow AND the
// two texts (headline + body in the §5c.1 normal form) share >= 1 identifier token or >= 2 word
// stems. Pure script; the stop list is part of the rule (fixture F-MEM-09 `given.stop_words`).
import { normalizeClaimText } from "./claim-text.ts";
import type { StoredMemoryItem } from "./types.ts";

export const GATE_STOP_WORDS: ReadonlySet<string> = new Set(
	(
		"a an the and or of to in on at by for from with without as is are was were be been it its this that these those " +
		"do does did not no only own their there then than so if when while after before into out up down over under " +
		"can will must may has have had"
	).split(" "),
);

/** The rule's id on every `verdicts.jsonl` record the gate writes. */
export const GATE_RULE_ID = "5c.5";

const IDENTIFIER_RE = /[\p{L}\p{N}][-_./:][\p{L}\p{N}]/u;
const DIGIT_RE = /\p{N}/u;
/** §5c.5 (`V-11`, Architecture rm-604c8feb): a route such as `/entries` is a name; the slash is kept. */
const ROUTE_RE = /^\/\p{L}/u;
const STEM_SUFFIXES = ["'s", "ing", "ed", "es", "s"] as const;

export interface ClaimTokens {
	identifiers: Set<string>;
	stems: Set<string>;
}

function stemOf(token: string): string | null {
	if (!/^[\p{L}']+$/u.test(token)) return null;
	let word = token;
	for (const suffix of STEM_SUFFIXES) {
		if (word.endsWith(suffix)) {
			word = word.slice(0, -suffix.length);
			break;
		}
	}
	if (!/^\p{L}+$/u.test(word) || GATE_STOP_WORDS.has(token) || GATE_STOP_WORDS.has(word)) return null;
	return word.length >= 3 ? word : null;
}

/** Identifier tokens and word stems of an already normal-form text. */
export function claimTokens(normalized: string): ClaimTokens {
	const out: ClaimTokens = { identifiers: new Set(), stems: new Set() };
	for (const raw of normalized.split(" ")) {
		if (ROUTE_RE.test(raw)) {
			out.identifiers.add(raw.replace(/[^\p{L}\p{N}]+$/u, ""));
			continue;
		}
		// Marks kept by the normal form (between two letters / digits) stay; a trailing one never reached here.
		const token = raw.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
		if (!token) continue;
		if (DIGIT_RE.test(token) || IDENTIFIER_RE.test(token)) {
			out.identifiers.add(token);
			continue;
		}
		const stem = stemOf(token);
		if (stem) out.stems.add(stem);
	}
	return out;
}

export function gateTextOf(item: Pick<StoredMemoryItem, "headline" | "body">): string {
	return normalizeClaimText(`${item.headline}\n${item.body}`);
}

function sharedCount(a: ReadonlySet<string>, b: ReadonlySet<string>): number {
	let n = 0;
	for (const value of a) if (b.has(value)) n += 1;
	return n;
}

export interface GateResult {
	pass: boolean;
	sharedIdentifiers: number;
	sharedStems: number;
}

/** §5c.5 on two texts; the cosine half of the rule is checked by the caller (it already has the score). */
export function candidateGate(a: Pick<StoredMemoryItem, "headline" | "body">, b: Pick<StoredMemoryItem, "headline" | "body">): GateResult {
	const ta = claimTokens(gateTextOf(a));
	const tb = claimTokens(gateTextOf(b));
	const sharedIdentifiers = sharedCount(ta.identifiers, tb.identifiers);
	const sharedStems = sharedCount(ta.stems, tb.stems);
	return { pass: sharedIdentifiers >= 1 || sharedStems >= 2, sharedIdentifiers, sharedStems };
}
