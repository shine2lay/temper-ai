# Positioning document format (positioning/1)

The contract for a positioning document: the positioning workflow writes it, positioning_grade
grades it, and launch notes and articles read its messaging hierarchy. Two files side by side:
`positioning.md` (for people) and `positioning.json` (the hierarchy, for workflows). The
evidence is a folder of plain text or markdown files; every fact in the document points into it.

## positioning.md

Markdown. A title line, then these eight sections, each once, in this order, with these exact
headings:

    # <Product> positioning

    ## 1. Competitive alternatives
    ## 2. Unique attributes
    ## 3. Value and proof
    ## 4. Best-fit customers
    ## 5. Market category
    ## 6. Messaging hierarchy
    ## 7. What it doesn't do
    ## 8. Assumptions and open questions

Between the title and section 1 there may be one line `Evidence: <folder>`; nothing else.

**One claim per line.** Write each claim on its own line (a `- ` bullet or a plain line) and
never wrap a line by hand: the checker reads one line as one claim.

**Every claim line ends with its source.** In sections 1-7, and in the value proposition and
proof points, every line that is not a heading or a label line ends with one or more citations:

    - Cooks log waste by voice on their phones. [product/features.md: "Cooks log waste by voice on their phones, in English or Spanish."]

or, when no evidence backs it, with the tag `(assumption)`:

    - Groups with more than three locations may also fit. (assumption)

- A citation is `[<file>: "<quote>"]`. `<file>` is the path inside the evidence folder. The
  quote is copied exactly from that file (line breaks and repeated spaces don't matter; curly and
  straight quotes are the same). A long quote may skip words with `...` when every kept part has
  at least three words and the parts appear in that order. Several citations sit side by side:
  `[a.md: "..."] [b.md: "..."]`.
- Every number in a cited line (digits: 49, 11.2%, $189, 2026) appears in one of that line's
  quotes, as digits or as a word (two, twelve). Don't round, convert or derive numbers: quote the
  evidence's own numbers, or mark the line `(assumption)`.
- A quote stays true to its file: same speaker, same scope, same meaning. Don't quote a plan as
  if it had shipped.
- Section 8 lines are assumptions and questions already; they may cite but need not.

**Label lines** (no citation needed):

- Section 4 starts with `Segment: <one specific segment>`, then the lines on why they care.
- Section 5 has `Style: head-to-head`, `Style: subsegment` or `Style: new category`, then
  `Category: <name>`, then `Reason: <why this category makes the value obvious>` (the reason line
  cites or is marked `(assumption)`).

**Section 6** is the messaging hierarchy, in this shape:

    ## 6. Messaging hierarchy

    ### Value proposition
    <one sentence> [citation] ...

    ### Pillar 1: <benefit>
    - <proof point> [citation] ...
    - ...

    ### Pillar 2: <benefit>
    ...

- One value proposition, one sentence.
- 3 or 4 pillars, numbered in order. A pillar is a benefit to the reader (what they get), not a
  feature (what the product has), and comes from a value in section 3.
- 3 to 5 proof points per pillar, strongest first: measured results from real use, then outside
  validation, then user quotes, then features.

**Section 7** says what the product doesn't do, wherever a reader would assume it does.

**Plain words.** No hype words (the list is in rubric.md), active voice, sentences of 30 words or
fewer (citations don't count).

## positioning.json

The hierarchy of section 6, mirrored exactly (same text, same citations, same order; the text is
the line without its citations or tag):

    {
      "format": "positioning/1",
      "product": "<Product>",
      "value_proposition": {"text": "...", "citations": [{"file": "...", "quote": "..."}], "assumption": false},
      "pillars": [
        {"benefit": "...", "proof_points": [
          {"text": "...", "citations": [{"file": "...", "quote": "..."}], "assumption": false}
        ]}
      ]
    }

`product` matches the title. `assumption` is true when the line carries the `(assumption)` tag.
