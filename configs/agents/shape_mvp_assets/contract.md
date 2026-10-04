# shape_mvp contract (product role)

Shape Up (Ryan Singer, Basecamp): fix the time, vary the scope. A pitch states its appetite
before any solution and has five parts: problem, appetite, solution, rabbit holes, no-gos. This
workflow adds checkable success criteria and a verification plan, and keeps every unresolved
assumption and prerequisite. A shaped pitch is input to the owner's betting table. It is not an
approval to build, not a market choice and not a promise to anyone.

## Input: shape_mvp.opportunity/1 (state/shape/input.json; readable copy input.md)
- id, title; buyer (who pays); user (who uses it, optional); job (what the product does for them)
- upstream_status {state open|provisional|parked|validated|killed, summary, source, reopened}
- evidence [{id, claim, quote, source, kind primary|secondary|vendor|estimate|assertion,
  party neutral|interested, checked}]. The claim is the earlier researcher's reading; the quote
  is the source's own words. Only quotes are verbatim.
- open_unknowns [{id, question, fatal true|false, source}]
- appetite {time_weeks, builders, source owner|test_fixture, note}
- constraints [{id, text, source}]
- proposed_solution {summary, source, features [{id, name, does, proposer_estimate_builder_weeks}]}
  (optional; a proposal to shape, not a commitment)
- owner_inputs {target_price {value, source}, success_bar {value, source}} (optional; missing
  ones are owner-input gaps, listed in setup.json and input.md)
- fixture {fictional, label} (optional)
Setup has already checked the critical inputs. A value whose source is test_fixture is test
data: use it, label it, never call it the owner's decision.

## Output: shape_mvp.pitch/1 (one JSON file; check_shape.py renders the .md next to it)
```json
{
  "schema": "shape_mvp.pitch/1",
  "case_id": "<input id>",
  "status": "shaped | blocked",
  "problem": {"statement": "<the named buyer's problem doing the named job, in plain words>",
              "evidence_ids": ["E1"]},
  "appetite": {"time_weeks": 6, "builders": 1, "source": "test_fixture"},
  "appetite_note": "<what this appetite means for scope: what fits, what had to go>",
  "upstream_status": {"state": "<copied exactly from the input>", "note": "<what it means here>"},
  "solution": {
    "summary": "<the narrow first version, fat-marker level>",
    "elements": [{"id": "S1", "name": "<short>", "does": "<what it does for the user>",
                  "estimate_builder_weeks": 1.5, "from_features": ["F1"],
                  "evidence_ids": [], "assumption_ids": ["A2"]}],
    "human_steps": ["<work people keep doing, by design>"]
  },
  "scope_cuts": [{"feature": "F4", "item": "<what is left out>", "why": "<why>"}],
  "rabbit_holes": [{"id": "RH1", "risk": "<what could sink the build>", "patch": "<how it is
                    bounded or worked around>", "evidence_ids": []}],
  "no_gos": [{"item": "<explicitly out>", "why": "<why>"}],
  "claims": [{"id": "C1", "text": "<what the pitch relies on>", "support": "supported | partial |
              assumption", "evidence_ids": ["E1"], "quote": "<optional: verbatim from E1's quote>"}],
  "assumptions": [{"id": "A1", "text": "<what must be true>", "risk": "value | usability |
                   feasibility | viability", "fatal": true, "from_unknowns": ["U1"],
                   "evidence_ids": [], "test": "V1"}],
  "prerequisites": [{"id": "P1", "kind": "data_access | platform_permission | legal | privacy |
                     procurement | security | integration | owner_input | other",
                     "text": "<what must be in place>", "status": "unresolved | resolved",
                     "blocks": "build | serve | sell | test", "evidence_ids": [],
                     "from_unknowns": ["U3"]}],
  "prerequisites_none_reason": "<only if prerequisites is empty>",
  "success_criteria": [{"id": "M1", "metric": "<what is counted>", "method": "<how it is
                        measured>", "threshold": "<number>", "horizon": "<number + time unit>",
                        "threshold_source": "owner | test_fixture | method | proposed",
                        "owner_input_gap": "OG-success_bar or null"}],
  "verification_plan": [{"id": "V1", "order": 1, "tests": ["A1"], "method": "<the test>",
                         "pass_if": "<...>", "kill_if": "<...>", "effort": "<time and who>",
                         "cost": "free | paid", "needs_owner_approval": true}],
  "owner_input_gaps": [{"id": "OG-target_price", "needed": "<what the owner must decide>",
                        "why": "<why it matters>"}],
  "fixture_values": ["<each test-fixture value used>"],
  "blocked": {"reasons": ["<why no pitch>"], "unblock_needs": ["<what would unblock it>"],
              "evidence_ids": []},
  "critique_responses": [{"critique_id": "K1", "action": "accepted | rejected", "note": "<the
                          change made, or why the critique is wrong, citing the input>"}]
}
```
- shaped: blocked may be omitted. blocked: solution.elements must be empty; reasons and
  unblock_needs are required; problem/claims may still say what the evidence shows.
- Copy appetite (time_weeks, builders, source) and upstream_status.state exactly.

## Rules the checker enforces (D1-D13, B)
- Estimates: every element > 0 builder-weeks; the total <= time_weeks x builders. Cut scope,
  never stretch the appetite. Every proposed feature is kept (from_features) or cut (scope_cuts
  with its feature id).
- Evidence: cited ids exist; the problem cites a non-assertion item; supported/partial claims
  cite evidence; a claim's quote must appear verbatim in a cited item's quote.
- Unknowns: every input unknown appears in from_unknowns of an assumption or prerequisite; a
  fatal unknown becomes an assumption with fatal true; resolved needs evidence.
- Tests: every assumption's test names a step whose tests list it; steps have unique whole-number
  order, method, pass_if, kill_if, effort, cost and needs_owner_approval; paid needs approval.
  Fatal first: with k fatal unknowns in the input, each one's fatal assumption is listed in the
  tests of one of the first max(2, k + 1) steps by order.
- Success criteria: metric and method always; threshold with a number and horizon with a number
  and a time unit, unless owner_input_gap names a listed gap. threshold_source owner or
  test_fixture only when the input's success_bar has that source; proposed needs a gap.
- Every setup owner-input gap is carried; test-fixture values are listed in fixture_values.
- Final pitch: every must_fix/should_fix critique item has a response.
Run `python3 state/shape/check_shape.py pitch <path to pitch.json> --stage draft|final` and fix
every problem it prints. It also writes the rendered .md next to the JSON.

## How to shape (draft and revise)
1. Problem: the named buyer's problem doing the named job. Do not broaden, swap or upgrade
   the buyer or the job. Cite evidence that shows the problem exists for THIS buyer. If no
   supplied evidence shows it (only other buyers, general market size, vendor claims about
   everyone, or the proposer's own assertion), status is blocked: reasons cite the evidence ids,
   unblock_needs name the evidence that would settle it. Unproven willingness to pay, price,
   market size or competition do NOT block: they are assumptions with tests.
2. Appetite first: copy it exactly and work out what fits in time_weeks x builders
   builder-weeks before designing anything.
3. Solution: the narrowest version that does the core job end to end for this buyer, at
   fat-marker level (elements are what the user can do, not tech tasks). Estimate each element
   honestly for a capable builder with AI coding help, including testing and the unglamorous
   parts (data intake, error handling, review screens); never shrink estimates to fit. If it
   does not fit, cut scope and say what went; if no version of the core job fits, status is
   blocked (unblock need: a larger appetite or a narrower job, the owner's call). Account for
   every proposed feature. Human steps the job needs (review, sign-off, sending) are part of
   the design: keep and name them.
4. Rabbit holes: the specific technical, data-access, permission, legal/privacy and accuracy
   risks visible in the evidence, unknowns and constraints, each with a patch (how it is
   bounded, e.g. manual upload instead of an integration). No-gos: adjacent scope explicitly
   out, and everything the constraints forbid.
5. Evidence and assumptions: claims with honest support (supported only when the cited quote
   says it; partial when it shows part of it or a proxy; assumption when nothing shows it).
   Never invent facts: numbers, rivals, prices, permissions, customer words, dates, owner
   decisions. Carry every open unknown, keep fatal ones fatal, never soften them; do not
   raise a non-fatal one to fatal unless a cited evidence item shows that failing it would
   end the idea (say which). Keep the upstream status (not validated, provisional, parked) as it is. Prerequisites (data access,
   platform permission, legal duties, privacy, procurement, security, integration, owner
   inputs) stay unresolved unless the evidence resolves them.
6. Success criteria: what would show the first version works, as metric, method, threshold (a
   number) and horizon (a number and a time unit); behaviour and money over words. Thresholds
   come from the owner's success bar if given (keep its source label), from a named standard
   method, or are your proposal (threshold_source proposed plus an owner-input gap). No
   promises.
7. Verification plan: riskiest first, then cheapest. Every fatal assumption is tested in the
   first steps (with k fatal unknowns in the input, within the first max(2, k + 1) steps by
   order). If its decisive test needs contact, money, personal or patient data or owner
   approval, put a free desk step that could already kill it early (a step may test several
   assumptions) and the paid or contact step later. That early step must be able to end the
   assumption on its own: its kill_if names the result that would. Among the other steps,
   cheapest first and desk tests before contact. Pass and kill rules use the buyer's own
   measures where the input allows; when a rule rests on a stand-in figure from the input (an
   unloaded median wage standing in for a firm's full cost of labour, say), say what the
   stand-in leaves out, invent no correction, and have the test measure the buyer's real
   figure, so a stand-in causes neither a false kill nor a false pass. pass_if and kill_if for
   each step; anything involving contact
   with people, sign-ups, ads, real money, or personal or patient data needs owner approval
   (nothing runs without the owner). Building comes after the fatal assumptions' tests.
8. Owner inputs needed: every gap in setup.json, plus any decision only the owner can make.
   fixture_values: every test-fixture value used, never presented as an owner decision.

## What the checker cannot see (the grader and a person check it)
Whether the evidence says what a claim says; whether estimates are honest; whether the problem
is the named buyer's; whether risks, no-gos and tests are the right ones; whether anything was
invented. Those are your job.
