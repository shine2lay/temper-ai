# Context profile: known cases

Architecture, queue #127, contract v2, 2026-10-20. This table moved from STANDARD.md (#122): the stage prompt
and held-out writer may read the standard and schema, so those two files hold no case content.

Synthetic briefs, written fresh, no real customer data or secrets. k01–k12 keep their original briefs;
k13–k14 are new 300–500-word briefs. Keys precede any model run. Each key must lint, pass checker v2 and
score 100% against itself. Profiles and planted controls are deterministic, not model outputs.

Case names and categories are stable identifiers, not maturity answers. In particular a small young
product with slow, steady paying demand can be established; a large product without a stated demand trend
can be unknown. See each key's maturity.accepted quotes and any why_unknown note.

| Case | Category | What it tests |
|---|---|---|
| k01-idea-pantry | idea_stage | nothing built; projected guesses; competitor figures; deletion promise is a constraint |
| k02-startup-invoicing | startup_paying | slow steady paying demand, despite youth and small team; current Rails app and rented server; Stripe Checkout; month-end peak; fixed budget |
| k03-growing-scheduling | growing_b2b_saas | proven fast demand growth; contract SLA and SOC 2; EU data; peaks; installed technology and outside dependencies |
| k04-large-photos | large_consumer | large workload and many teams do not establish demand trend; current regional media pipeline; regional rules and minors excluded |
| k05-small-therapy | small_high_risk | paid pilot; therapy notes; HIPAA and MFA are constraints, never cost trade-offs |
| k06-large-simple-transit | large_simple | established, flat demand; million-user read-mostly service, two part-time people; current static feed pipeline and external transport feeds |
| k07-conflict-marketplace | conflicting_priorities | decider's ranking amid conflicting executives; present marketplace; named processor; a slowdown is workload, not a security threat; loss and recovery unknowns |
| k08-missing-volunteers | missing_budget_workload | nothing built; no budget or workload numbers: unknown, never guessed |
| k09-projected-fitness | projected_as_observed | growth-deck targets are not current load; offline mobile app and Python backend; Apple Watch, Garmin and HealthKit dependencies |
| k10-misleading-logistics | misleading_claim | personal-data denial contradicted by GPS traces; current route builder and driver app; recovery and operating coverage unknowns |
| k11-privacy-reading | privacy_vs_cost | children's minimisation and retention duties versus cheaper hosting; current Python and single-provider system; demand trend unknown |
| k12-internal-expenses | internal_tool_deadline | new in-house replacement of hosted ClaimPro; lifecycle boundary unknown; fixed SAP and Okta dependencies, Azure hosting and hard deadline |
| k13-performance-docks | performance_critical | current warehouse event service; partner API and vendor-scale dependencies; mandatory p95, freshness and ingestion targets; a supplier's throughput is not this product's load |
| k14-large-org-roomkeys | large_org_internal | large organisation, tiny established internal tool; low workload; strict access and compliance; identity provider; speed complaint with no numerical target |

## Keying decisions in v2

- No brief was rewritten to make a key pass. Unknown maturity is deliberate for k04 and k11 (trend absent)
  and k12 (replacement boundary and trend unsettled); each names a maturity.stage unknown with a
  non-material rationale: the stated workload, team and binding policies already drive the design.
- k02 is established, not startup based on age or team. Its paying customers and explicitly slow, steady
  revenue growth meet the established definition. The filename/category remain for stable references.
- k07 data-loss tolerance and recovery time are material unknowns: a booking marketplace must decide
  durability and failover, and neither revenue growth nor a monthly uptime complaint settles them.
- Every fields_unknown entry is either a required material unknown or has a not_material_reason.
- Facts use one primary section and at most one justified alternative. Each profile item can carry only
  one key fact in maximum matching. Separate facts may have separate items quoting the same short span.

The task report lists all new current-system, external-system and performance facts, the accepted
lifecycle evidence, planted results and file digests. The standard's B0–B10 and ceilings are unchanged.
