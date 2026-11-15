# QA blind semantic rubric — OpenViking v2 model benchmark (data #20)

Written before any response was opened. Anchored to protocol.md, section "Blind semantic rubric".
One rater (QA task #167 chat). Each anonymized response gets the record below.

## Fields (0 or 1)

**topic_separation**
- 1: every output item covers one topic; notes about different topics are in different items. Dedup: true duplicates/near-duplicates/complementary fragments of the same topic may be merged; nothing is ejected. Sweep: notes the evidence does not touch stay as their own items.
- 0: at least one item merges notes on different topics, or (dedup) any note is ejected instead of kept. Unmerged same-topic duplicates are counted under concise, not here (tie-break 3).

**fact_retention**
- 1: every distinct, supported fact of every retained note survives in the retained text, and exact ids, paths, numbers, flags and hashes of retained notes appear verbatim.
- 0: any retained note loses a distinct fact, or any exact id / path / number of a retained note is missing or altered (reformatting that changes the literal string counts as altered).

**no_invention**
- 1: every claim in the output is stated by the notes or the canonical evidence (rewording and summarizing allowed).
- 0: the output adds any claim, id, path, number, date, cause or recommendation that neither the notes nor the evidence state, or presents a guess as fact.

**history_handling**
- 1: dedup: historical records stay historical (no tense change that turns a past event into current policy). Sweep: a note the canonical evidence supersedes is ejected (or, if retained, clearly framed as past/superseded); historical records that remain true as history are kept as history, not ejected.
- 0: an old instruction or superseded claim is kept as active/current policy, OR a true historical record is ejected or rewritten as false, OR a still-valid note is ejected as stale.

**concise**
- 1: no item repeats another item's content; merged items state each fact once; no padding or commentary beyond the item text.
- 0: two items carry the same content (unmerged duplicate or repeated text), or an item repeats a fact several times, or the output adds boilerplate/meta text.

## Other fields
- **corruption** (true/false): true when the output states something false as current truth — a stale/superseded claim kept as active policy, a fact changed to a different value, notes merged so a fact is attributed to the wrong subject. A mere omission is not corruption.
- **defect**: short text naming each failure; "" only when all five are 1 and corruption is false.
- **gradable**: false only when the response is empty or not readable as the answer (not parseable as items/ejected and not readable prose answer). Then the five fields are 0, corruption false, defect says why.

## Tie-break rules
1. One defect, one primary field: an omitted fact -> fact_retention only; an ejected still-valid note -> history_handling (and fact_retention 0 too, because its facts are gone from retained text); an invented claim -> no_invention only unless it also makes a stale claim active (then history_handling 0 + corruption).
2. Stale instruction kept as active policy -> history_handling 0 AND corruption true (protocol).
3. Unmerged same-topic duplicates in dedup -> concise 0, topic_separation stays 1 (topics are not mixed).
4. Different-topic notes merged -> topic_separation 0; corruption true only if the merge attributes a fact to the wrong subject.
5. Any ejection in a dedup case -> topic_separation 0 and history_handling 0 (dedup allows no ejection); fact_retention 0 if the ejected note's facts appear nowhere else.
6. Ejection reasons are judged for no_invention too (a reason citing something the evidence does not say -> no_invention 0).
7. Benign rewording and reordering pass; changing the literal form of an id/path/number fails fact_retention.
8. When unsure whether a fact is "distinct", count it as distinct if it carries a number, id, path, name, condition or consequence.
9. Doubt about whether evidence supersedes a note: follow the canonical evidence text literally; record the doubt in defect only when it changes a grade.
10. Malformed JSON that is still readable as the answer is graded on meaning (schema failures are Data's deterministic score, not this rubric).
