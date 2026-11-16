// OpenViking v2 §5c.1: the one text normal form of a claim. The write-time duplicate key (§5.3), the
// §6.2 headline key, the §3 line duplicate checks and the candidate gate (§5c.5) all use it.
// `content_sha` keeps its earlier form (`contentClaimText`) so no stored hash, receipt or plan changes.

const LEADING_MARKER_RE = /^[ \t]*(?:>[ \t]*|(?:[-+*]|#{1,6}|\d+[.)])(?:[ \t]+|$))/;
const DROPPABLE_MARKS = new Set([".", ",", ";", ":", "?", '"', "'", "(", ")", "[", "]", "{", "}", "`", "*", "_"]);
const LETTER_OR_DIGIT_RE = /[\p{L}\p{N}]/u;

function dropMarks(line: string): string {
	const chars = [...line];
	let out = "";
	for (let i = 0; i < chars.length; i++) {
		const ch = chars[i];
		if (DROPPABLE_MARKS.has(ch) && !(LETTER_OR_DIGIT_RE.test(chars[i - 1] ?? "") && LETTER_OR_DIGIT_RE.test(chars[i + 1] ?? ""))) continue;
		out += ch;
	}
	return out;
}

/**
 * §5c.1: NFC → lower case → per line drop a leading list / heading / quote marker → drop
 * `. , ; : ? " ' ( ) [ ] { } \` * _` unless a letter or digit is on both sides → collapse whitespace.
 * `1.5 s` vs `15 s`, `x != 5` vs `x == 5`, `said_on`, `a/b.ts` keep their marks.
 */
export function normalizeClaimText(text: string): string {
	return text
		.normalize("NFC")
		.toLowerCase()
		.split(/\r?\n/)
		.map((line) => dropMarks(line.replace(LEADING_MARKER_RE, "")))
		.join(" ")
		.replace(/\s+/g, " ")
		.trim();
}

/** The earlier form, kept only for `content_sha` (NFC, trim, collapse whitespace, lower case). */
export function contentClaimText(text: string): string {
	return text.normalize("NFC").trim().replace(/\s+/g, " ").toLowerCase();
}
