-- Compress-policy take-rate.
--
-- Every LLM agent runs under `context_policy: compress` unless it says
-- otherwise: ref tags on what it sees, a [context] nudge once the view is
-- 60% full, and compress / decompress / search_context / context_status among
-- its tools. This asks whether the model does anything with that.
--
-- Per ask — what the model did with a view that carried the nudge:
--
--   compressed   it called compress                         -> the nudge worked
--   looked       context_status / search_context / decompress, no compress
--   carried_on   other tool calls only                      -> ignored, this time
--   answered     no tool calls: the run ended               -> nothing to save
--
-- Per node — the outcome over a whole agent run:
--
--   compressed   compress called at least once, never evicted
--   evicted      the harness hid a range to stay under the limit; the model
--                never compressed in time. What the nudge exists to prevent.
--   ignored      asked at least once, never compressed, never evicted: the
--                run ended before the limit
--   quiet        never asked: the run stayed small; the policy cost four tool
--                schemas per call and nothing else
--
--   `unprompted` counts context tool calls made before the first ask — a
--   model exploring the tools, or (at iteration 1) answering them instead of
--   the task.
--
-- If `carried_on` dominates per ask and `evicted` per node, the nudge is the
-- wrong channel — the ask belongs in the guidance, or the harness should
-- compress on the model's behalf.
--
-- Reads the `context` object on `llm.call.completed` (what the harness sent:
-- policy, limit, tokens, nudged, hid, blocks, hidden, wrapping_up) and the
-- response in the same event. Calls made before that object existed are only
-- in the first result set, as policy `unknown`.
--
-- Run from the repo root:
--   docker compose exec -T postgres psql -U temper_ai -d temper_ai -f - < scripts/sql/compress_take_rate.sql

create temp view llm_calls as
select
    c.id,
    c.execution_id,
    c.parent_id                                                   as node_id,
    a.data ->> 'agent_name'                                       as agent,
    c.timestamp,
    (c.data ->> 'iteration')::int                                 as iteration,
    coalesce(c.data -> 'context' ->> 'policy', 'unknown')         as policy,
    (c.data -> 'context' ->> 'limit')::int                        as "limit",
    (c.data -> 'context' ->> 'tokens')::int                       as tokens,
    (c.data ->> 'prompt_tokens')::int                             as prompt_tokens,
    coalesce((c.data -> 'context' ->> 'nudged')::boolean, false)  as nudged,
    coalesce(json_array_length(c.data -> 'context' -> 'hid'), 0) > 0
                                                                  as evicted,
    coalesce((c.data -> 'context' ->> 'wrapping_up')::boolean, false)
                                                                  as wrapping_up,
    -- a JSON null when the response had no tool calls: not an SQL null
    case when json_typeof(c.data -> 'tool_calls_requested') = 'array'
         then array(select t ->> 'name' from json_array_elements(c.data -> 'tool_calls_requested') t)
         else '{}'::text[] end                                    as requested
from events c
left join events a on a.id = c.parent_id
where c.type = 'llm.call.completed';

create temp view compress_calls as
select
    l.*,
    l.requested && array['compress', 'decompress', 'search_context', 'context_status']
                                                                  as used_context_tools,
    min(l.timestamp) filter (where l.nudged)
        over (partition by l.node_id)                             as first_ask
from llm_calls l
where l.policy = 'compress';

-- 0. Which policy nodes actually ran under: the rollout, from the log.
select
    policy,
    count(distinct node_id)                         as nodes,
    count(*)                                        as calls,
    max(prompt_tokens)                              as max_prompt_tokens,
    min(timestamp)::date                            as first_seen,
    max(timestamp)::date                            as last_seen
from llm_calls
group by policy
order by nodes desc;

-- 1. Per ask.
select
    case
        when 'compress' = any(requested)                                        then 'compressed'
        when requested && array['decompress', 'search_context', 'context_status'] then 'looked'
        when cardinality(requested) > 0                                         then 'carried_on'
        else                                                                         'answered'
    end                                                       as response,
    count(*)                                                  as asks,
    count(distinct node_id)                                   as nodes,
    round(100.0 * count(*) / sum(count(*)) over (), 1)        as pct,
    round(avg(100.0 * tokens / nullif("limit", 0)))           as avg_pct_full
from compress_calls
where nudged
group by response
order by asks desc;

-- 2. Per node.
create temp view compress_nodes as
select
    node_id,
    min(execution_id)                                               as execution_id,
    min(agent)                                                      as agent,
    min(timestamp)                                                  as started,
    count(*)                                                        as calls,
    max(round(100.0 * tokens / nullif("limit", 0)))                 as max_pct,
    count(*) filter (where nudged)                                  as asks,
    count(*) filter (where 'compress' = any(requested))             as compressed,
    count(*) filter (where evicted)                                 as evictions,
    count(*) filter (where used_context_tools
                       and (first_ask is null or timestamp < first_ask))
                                                                    as unprompted,
    case
        when count(*) filter (where evicted) > 0                    then 'evicted'
        when count(*) filter (where 'compress' = any(requested)) > 0 then 'compressed'
        when count(*) filter (where nudged) > 0                     then 'ignored'
        else                                                             'quiet'
    end                                                             as outcome
from compress_calls
group by node_id;

select
    outcome,
    count(*)                                                  as nodes,
    round(100.0 * count(*) / sum(count(*)) over (), 1)        as pct,
    round(avg(max_pct))                                       as avg_max_pct,
    sum(asks)                                                 as asks,
    sum(compressed)                                           as compress_calls,
    sum(evictions)                                            as evictions,
    sum(unprompted)                                           as unprompted
from compress_nodes
group by outcome
order by nodes desc;

-- 3. The nodes, newest first, for reading the evicted / ignored rows.
select
    started,
    left(execution_id, 8)                       as run,
    agent,
    calls,
    max_pct,
    asks,
    compressed,
    evictions,
    unprompted,
    outcome
from compress_nodes
order by started desc
limit 30;

-- 4. Every compress the model wrote, newest first: what it folded and what it
--    saved. (Two compress calls in one turn share a parent and both show the
--    first result; rare enough to read around.)
select
    s.timestamp,
    left(s.execution_id, 8)                     as run,
    s.data ->> 'agent_name'                     as agent,
    case when json_typeof(s.data -> 'input_params' -> 'ranges') = 'array'
         then json_array_length(s.data -> 'input_params' -> 'ranges') end
                                                as ranges,
    case when json_typeof(s.data -> 'input_params' -> 'ranges') = 'array'
         then (select sum(length(r ->> 'summary'))
               from json_array_elements(s.data -> 'input_params' -> 'ranges') r) end
                                                as summary_chars,
    left(coalesce(d.data ->> 'output', d.data ->> 'error'), 160)
                                                as result
from events s
left join lateral (
    select data
    from events
    where parent_id = s.parent_id
      and type in ('tool.call.completed', 'tool.call.failed')
      and data ->> 'tool_name' = 'compress'
      and timestamp >= s.timestamp
    order by timestamp
    limit 1
) d on true
where s.type = 'tool.call.started'
  and s.data ->> 'tool_name' = 'compress'
order by s.timestamp desc
limit 30;
