# positioning_grade rubric (positioning_grade/1)

Grades one positioning document (FORMAT.md, positioning/1) for soundness against its own
evidence folder: April Dunford's five components (Obviously Awesome), the messaging hierarchy,
every claim traced to its evidence, and plain words. It does not judge whether the market will
buy (a message test does that) and it never rewrites the document.

Each criterion ends **pass**, **revise** or **unknown**:

- **revise** only with at least one counted **material** finding on that criterion. A finding
  counts when every passage it cites is verbatim in the file it names and at least one passage is
  from the graded document.
- **unknown** when the files can't settle it (say what is missing), or when a lead the checker
  left is not resolved.
- **pass** otherwise. Minor findings are reported and don't change the status.

Overall: revise if any criterion is revise, else unknown if any is unknown, else pass.

**Material** means it would mislead a reader, or a workflow that builds on the document: a
false, contradicted or unproven claim, a wrong number, an invented or altered quote, a limit a
reader would assume away left unsaid, or a segment, category or pillar that defeats the
document's purpose. Every checker finding is material (it breaks the format contract).
**Minor** means polish: it doesn't change what a reader takes away about the product, who it is
for, or its proof.

**The stretch test** draws that line for a stretch: a line whose quotes support its main point
while a word or a missing note reaches past them (an added only, most, all, every, always or at
all, or a word that hints at more than the quote says; a limit or a note on how a result was
measured that the document leaves out). The main point is the line without the stretching word,
or with the missing note added. If the quotes support the main point and a reader would still
take away the same alternative, attribute, value, segment, category, pillar, proof and numbers,
the stretch is minor. It is material when the reach changes one of those as a reader takes it:
the product doing more, or for more cases, than the evidence shows; a wider segment; a bigger
number or share; proof that covers more than it does; a system the user needs, or a group the
product fails, assumed away. A note on how a result was measured is material only when the
evidence shows that leaving it out makes the result look bigger than it is. Not stretches, and
material: a main point no quote supports, a main point the evidence contradicts, and a
superlative or promise with no proof.

Work from the files only. Judge against the evidence folder, not against what you know about
the market: what the evidence doesn't cover is unknown, an assumption, or out of reach, never a
finding.

## P1 Competitive alternatives

What best-fit users would really do if the product didn't exist: do it by hand, use general
tools (spreadsheets, chat, paper), hire someone, live with the problem, or buy a product they
actually consider. Dunford: start from what users do now, not from a competitor list.

- Revise: the alternatives are only competing products when the evidence shows what users do
  now (by hand, general tools, nothing); alternatives that belong to a different group than the
  best-fit segment; an alternative the evidence contradicts.
- Not a finding: products listed next to the status quo; the order of the list.

## P2 Unique attributes are true today

What the product has or does that the alternatives don't.

- Revise: an attribute the evidence contradicts, or describes as planned, coming, in beta or on
  a roadmap; an attribute stated wider than the evidence allows (any POS where the evidence names
  two; all languages where it names two).
- Not a finding: whether an attribute is unique in the whole market (out of reach without the
  web); minor when the evidence itself shows a named alternative has it.

## P3 Value, with the strongest proof

Each attribute leads to a value: what changes for the user, said as a benefit. Each value has
proof, the strongest kind the evidence offers: measured results from real use, then outside
validation, then user quotes, then features.

- Revise: a value with no proof that shows it; proof that shows something else; a value that is
  only a feature restated; most attributes leading to no value.
- Minor: one attribute with no value; a stronger proof in the evidence left unused.

## P4 One best-fit segment

Geoffrey Moore: one specific segment first. The `Segment:` line names one group (who, what kind
and size, what situation) that the evidence shows cares most, and the lines after it say what
makes them care.

- Revise: the segment is everyone or a whole broad market ("any business", "all restaurants",
  "teams of every size"); several unrelated segments; a segment that includes groups the
  evidence shows are a poor fit; no reason why they care.
- Not a finding: naming groups that are not a fit; a segment narrower than all the evidence.

## P5 Market category

The frame that makes the value obvious. Dunford's styles: head-to-head (win an existing
category), subsegment (a part of an existing category with needs it serves badly), new category
(only when existing categories fail the buyer, and the evidence shows it).

- Revise: no style, or one that contradicts the category; a buzzword category name a best-fit
  buyer wouldn't recognise, with no reason tying it to the value; a new category without
  evidence that existing ones fail the buyer; a reason that explains nothing ("the market is
  ready").
- Not a finding: a plain, modest category name; a subsegment named by what it is for.

## P6 Messaging hierarchy

One value proposition in one sentence; 3-4 pillars; 3-5 proof points each, strongest first.
positioning.json mirrors section 6 exactly (the checker settles shape and mirroring).

- Revise: a pillar that is a feature or a part of the product (what it has) instead of a benefit
  (what the reader gets); a pillar with no root in the values of section 3; a value proposition
  that promises what no pillar supports; proof points that mostly don't prove their pillar.
- Minor: proof points not strongest first.

## P7 Every claim traced and honest

Every claim cites a quote that resolves or is marked (assumption); numbers match their quote;
no invented quotes (the checker settles these mechanically). The review adds meaning:

- Revise: a quote that resolves but doesn't support the line's main point (another speaker,
  another product or group, a plan read as shipped, an added number); a stretch the stretch test
  calls material; a superlative, uniqueness claim or promise with no proof (fastest, best, the
  only tool that, cuts X in half); a limit the evidence states that a reader would assume away (a
  required system, something similar tools do, a group it fails) and that the document never
  says.
- Minor: a stretch the stretch test calls minor.
- Not a finding: generalising from the evidence's examples to the segment in neutral words,
  without an added number or scope word; a paraphrase that keeps the meaning; an honest
  (assumption) tag; a limit the document states anywhere.

## P8 Plain words

Clear beats clever (Google developer documentation style guide; plainlanguage.gov).

- The checker settles: no hype word below outside a quote; no sentence over 30 words (citations
  don't count).
- Revise: passive voice that hides who does what in a claim; jargon or buzzwords a best-fit
  reader wouldn't use, in the value proposition, a pillar or the category.
- Not a finding: words inside quotes; plain technical names the buyer uses (POS, prep list).

## Hype words

Matched as whole words, any case; a hyphen and a space are the same.

- revolutionary
- revolutionize
- game-changing
- game-changer
- groundbreaking
- cutting-edge
- state-of-the-art
- next-generation
- next-gen
- best-in-class
- best-of-breed
- world-class
- industry-leading
- market-leading
- seamless
- seamlessly
- effortless
- effortlessly
- powerful
- robust
- innovative
- disruptive
- unparalleled
- unmatched
- unrivaled
- unprecedented
- blazing-fast
- lightning-fast
- supercharge
- supercharged
- turbocharge
- magical
- ultimate
- synergy
- empower
- empowers
- empowering
- transformative
- amazing
- incredible
- awesome
- stunning
- mind-blowing
