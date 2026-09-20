-- Scratch-directory take-rate.
--
-- The path check refuses a write outside the workspace and names the run's
-- scratch directory in the refusal (ToolExecutor.scratch_dir). This asks
-- what the node did with that: for every `tool.blocked` event that named a
-- scratch dir, classify the node's *next* tool call in the same run.
--
--   scratch    the next call used the scratch dir           -> the refusal worked
--   workspace  the next call went into the workspace        -> also fine
--   bash       the next call was Bash naming the refused    -> went around the check
--              path or /tmp (Bash is not path-checked)
--   retry      the same path again                          -> did not read the refusal
--   other      something unrelated
--   none       no further tool call in the run              -> gave up or was done
--
-- If `bash` + `retry` dominate, the refusal is the wrong channel and the
-- scratch dir belongs in the system prompt / tool description up front.
--
-- Run from the repo root:
--   docker compose exec -T postgres psql -U temper_ai -d temper_ai -f - < scripts/sql/scratch_take_rate.sql
-- (a temp view, so both result sets come from one classification).

create temp view scratch_refusals as
with blocked as (
    select
        e.id,
        e.execution_id,
        e.timestamp,
        e.data ->> 'tool_name'                                           as tool_name,
        e.data ->> 'scratch_dir'                                         as scratch_dir,
        e.data ->> 'workspace_root'                                      as workspace_root,
        substring(e.data ->> 'error' from 'Path ''([^'']+)'' escapes')   as refused_path
    from events e
    where e.type = 'tool.blocked'
      and e.data ->> 'reason' = 'workspace_violation'
      and e.data ->> 'scratch_dir' is not null
),
followed as (
    select
        b.*,
        n.timestamp                                   as next_at,
        n.data ->> 'tool_name'                        as next_tool,
        (n.data -> 'input_params')::text              as next_params
    from blocked b
    left join lateral (
        select timestamp, data
        from events
        where execution_id = b.execution_id
          and type = 'tool.call.started'
          and timestamp > b.timestamp
        order by timestamp
        limit 1
    ) n on true
),
classified as (
    select
        f.*,
        case
            when next_tool is null                                           then 'none'
            when next_params like '%' || scratch_dir || '%'                  then 'scratch'
            -- the exact path again (quoted: a corrected path that merely
            -- starts with the refused one is not a retry)
            when next_params like '%"' || refused_path || '"%'
                 and next_tool = tool_name                                   then 'retry'
            when next_tool = 'Bash'
                 and (next_params like '%' || refused_path || '%'
                      or next_params like '%/tmp/%')                         then 'bash'
            when next_params like '%' || workspace_root || '%'
                 or next_params ~ '"path": "[^/]'                            then 'workspace'
            else 'other'
        end as outcome
    from followed f
)
select * from classified;

select
    outcome,
    count(*)                                                  as refusals,
    count(distinct execution_id)                              as runs,
    round(100.0 * count(*) / sum(count(*)) over (), 1)        as pct,
    min(timestamp)::date                                      as first_seen,
    max(timestamp)::date                                      as last_seen
from scratch_refusals
group by outcome
order by refusals desc;

-- The individual refusals, newest first, for reading the "other"/"bash" rows.
select
    timestamp,
    left(execution_id, 8)                       as run,
    tool_name,
    refused_path,
    outcome,
    next_tool,
    left(next_params, 120)                      as next_params
from scratch_refusals
order by timestamp desc
limit 40;
