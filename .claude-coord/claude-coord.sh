#!/bin/bash
# claude-coord.sh - Multi-agent coordination for Claude Code instances
# Handles agent registration, file locking, and task coordination

set -e

COORD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="$COORD_DIR/state.json"
LOCK_FILE="$COORD_DIR/.state.lock"
LOCK_TIMEOUT_SECONDS=1800  # 30 minutes - only cleanup truly dead processes, not agents waiting for user input
TASK_RETENTION_DAYS=7      # Auto-cleanup completed tasks older than this

# ============================================================
# HELPERS
# ============================================================

# Atomic file operations using flock
# IMPORTANT: For read-modify-write operations, use atomic_update() instead
atomic_read() {
    verify_lock_file
    if [ ! -f "$STATE_FILE" ]; then
        echo '{"agents":{},"locks":{},"tasks":{}}'
        return
    fi
    flock -s "$LOCK_FILE" cat "$STATE_FILE"
}

atomic_write() {
    verify_lock_file
    local new_state="$1"
    # Atomic write with verification using temp file
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        new_state="$1"
        temp_file="${STATE_FILE}.tmp.$$"

        # Write to temp file
        printf "%s\n" "$new_state" > "$temp_file" 2>/dev/null
        write_exit=$?

        if [ $write_exit -ne 0 ]; then
            echo "ERROR: Failed to write state file (disk full?)" >&2
            rm -f "$temp_file"
            exit 1
        fi

        # Verify it'\''s valid JSON
        if ! jq empty "$temp_file" >/dev/null 2>&1; then
            echo "ERROR: Wrote invalid JSON to state file" >&2
            rm -f "$temp_file"
            exit 1
        fi

        # Atomic move
        mv "$temp_file" "$STATE_FILE"
    ' _ "$new_state"
}

# Atomic read-modify-write: holds exclusive lock for entire operation
# Usage: atomic_update "jq_expression"
# Returns: the updated state
atomic_update() {
    verify_lock_file
    local jq_expr="$1"
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        if [ ! -f "$STATE_FILE" ]; then
            echo "{\"agents\":{},\"locks\":{},\"tasks\":{}}" > "$STATE_FILE"
        fi
        state=$(cat "$STATE_FILE")

        # Validate state is valid JSON, reinitialize if corrupted
        if [ -z "$state" ] || ! echo "$state" | jq empty >/dev/null 2>&1; then
            echo "WARNING: State file corrupted, reinitializing" >&2
            state="{\"agents\":{},\"locks\":{},\"tasks\":{}}"
            echo "$state" > "$STATE_FILE"
        fi

        # Execute jq transformation with error handling
        new_state=$(echo "$state" | jq "'"$jq_expr"'" 2>&1)
        jq_exit=$?

        if [ $jq_exit -ne 0 ] || [ -z "$new_state" ]; then
            echo "ERROR: jq command failed: $new_state" >&2
            exit 1
        fi

        # Atomic write with verification using temp file
        temp_file="${STATE_FILE}.tmp.$$"
        printf "%s\n" "$new_state" > "$temp_file" 2>/dev/null
        write_exit=$?

        if [ $write_exit -ne 0 ]; then
            echo "ERROR: Failed to write state file (disk full?)" >&2
            rm -f "$temp_file"
            exit 1
        fi

        # Verify it'\''s valid JSON
        if ! jq empty "$temp_file" >/dev/null 2>&1; then
            echo "ERROR: Wrote invalid JSON to state file" >&2
            rm -f "$temp_file"
            exit 1
        fi

        # Atomic move
        mv "$temp_file" "$STATE_FILE"
        echo "$new_state"
    '
}

# Verify filesystem compatibility
check_filesystem() {
    # Only check once per session
    if [ -f "$COORD_DIR/.fs_checked" ]; then
        return 0
    fi

    # Detect filesystem type
    local fs_type=""
    if command -v df >/dev/null 2>&1; then
        # Try df -T (GNU/Linux)
        fs_type=$(df -T "$COORD_DIR" 2>/dev/null | tail -1 | awk '{print $2}')

        # If that didn't work, try stat -f (BSD/macOS)
        if [ -z "$fs_type" ] || [ "$fs_type" = "-" ]; then
            fs_type=$(stat -f -c %T "$COORD_DIR" 2>/dev/null || stat -f "$COORD_DIR" 2>/dev/null | head -1 | awk '{print $1}')
        fi
    fi

    # Block known problematic filesystems
    if [[ "$fs_type" =~ nfs|cifs|smb|smbfs ]]; then
        echo "ERROR: Coordination system detected network filesystem: $fs_type" >&2
        echo "ERROR: flock-based locking does not work reliably on network filesystems" >&2
        echo "ERROR: Please use a local filesystem (ext4, xfs, apfs, etc.)" >&2
        exit 1
    fi

    # Create marker file to skip check on subsequent operations
    touch "$COORD_DIR/.fs_checked" 2>/dev/null || true
}

# Initialize state file if missing
init_state() {
    # Check filesystem compatibility first
    check_filesystem

    if [ ! -f "$STATE_FILE" ]; then
        echo '{"agents":{},"locks":{},"tasks":{},"prefix_priorities":{}}' > "$STATE_FILE"
    fi
    # Ensure prefix_priorities exists in existing state files
    if [ -f "$STATE_FILE" ]; then
        local state=$(cat "$STATE_FILE")
        if ! echo "$state" | jq -e '.prefix_priorities' >/dev/null 2>&1; then
            state=$(echo "$state" | jq '. + {prefix_priorities: {}}')
            printf "%s\n" "$state" > "$STATE_FILE"
        fi
    fi

    # Verify lock file exists
    if [ ! -f "$LOCK_FILE" ]; then
        touch "$LOCK_FILE"
    fi

    # Check state file size and warn if too large
    if [ -f "$STATE_FILE" ]; then
        local state_size=$(stat -c%s "$STATE_FILE" 2>/dev/null || stat -f%z "$STATE_FILE" 2>/dev/null || echo 0)
        if [ "$state_size" -gt 10485760 ]; then  # 10MB
            echo "WARNING: State file very large ($(($state_size / 1048576))MB)" >&2
            echo "WARNING: Consider running 'task-cleanup' or 'task-archive' to reduce size" >&2
        elif [ "$state_size" -gt 5242880 ]; then  # 5MB
            echo "NOTICE: State file size: $(($state_size / 1048576))MB (consider cleanup soon)" >&2
        fi
    fi
}

# Verify lock file integrity
verify_lock_file() {
    if [ ! -f "$LOCK_FILE" ]; then
        echo "CRITICAL: Lock file missing at $LOCK_FILE" >&2
        echo "CRITICAL: Coordination system integrity compromised - refusing operation" >&2
        exit 1
    fi
}

# Check if a PID is still running with multi-attempt verification
# This prevents false negatives when process is temporarily sleeping/swapped
is_pid_alive() {
    local pid="$1"
    [ -z "$pid" ] && return 1

    # Try 3 times with small delays
    for attempt in 1 2 3; do
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        # Small delay before retry (except on last attempt)
        [ $attempt -lt 3 ] && sleep 0.1
    done

    return 1
}

# Get current timestamp
now() {
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

# Log activity to activity.jsonl
log_activity() {
    local activity_file="$COORD_DIR/activity.jsonl"
    local timestamp=$(now)
    local action="$1"
    shift

    # Build JSON with all provided arguments
    local json_data="{\"timestamp\":\"$timestamp\",\"action\":\"$action\""

    # Parse key=value pairs
    while [ $# -gt 0 ]; do
        local key="${1%%=*}"
        local value="${1#*=}"
        # Add to JSON (quote strings, keep numbers as-is)
        if [[ "$value" =~ ^[0-9]+$ ]]; then
            json_data="$json_data,\"$key\":$value"
        else
            json_data="$json_data,\"$key\":\"$value\""
        fi
        shift
    done

    json_data="$json_data}"

    # Append to activity log (atomic append)
    echo "$json_data" >> "$activity_file"
}

# Clean up dead agents and their locks
# FIXED: Now holds exclusive lock for entire read-modify-write cycle
cleanup_dead_agents() {
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        LOCK_TIMEOUT_SECONDS='"$LOCK_TIMEOUT_SECONDS"'

        if [ ! -f "$STATE_FILE" ]; then
            echo "{\"agents\":{},\"locks\":{},\"tasks\":{}}"
            exit 0
        fi

        state=$(cat "$STATE_FILE")
        now_ts=$(date +%s)
        changed=false

        # Get all agent IDs
        agents=$(echo "$state" | jq -r ".agents | keys[]" 2>/dev/null || echo "")

        for agent_id in $agents; do
            pid=$(echo "$state" | jq -r ".agents[\"$agent_id\"].pid")
            heartbeat=$(echo "$state" | jq -r ".agents[\"$agent_id\"].heartbeat")
            hb_ts=$(date -d "$heartbeat" +%s 2>/dev/null || echo 0)
            age=$((now_ts - hb_ts))

            # Check if PID is still running
            pid_alive=false
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                pid_alive=true
            fi

            # Remove if PID dead AND heartbeat too old (require BOTH conditions)
            # This prevents cleanup during brief PID check failures
            if [ "$pid_alive" = false ] && [ "$age" -gt "$LOCK_TIMEOUT_SECONDS" ]; then
                state=$(echo "$state" | jq "del(.agents[\"$agent_id\"])")
                state=$(echo "$state" | jq ".locks |= with_entries(select(.value.owner != \"$agent_id\"))")
                changed=true
                echo "Cleaned up dead agent: $agent_id (pid: $pid, age: ${age}s)" >&2
            fi
        done

        if [ "$changed" = true ]; then
            printf "%s\n" "$state" > "$STATE_FILE"
        fi

        echo "$state"
    '
}

# ============================================================
# AGENT COMMANDS
# ============================================================

cmd_register() {
    local agent_id="$1"
    local pid="${2:-$PPID}"

    [ -z "$agent_id" ] && { echo "Usage: $0 register <agent_id> [pid]" >&2; exit 1; }

    init_state

    # Atomic read-modify-write with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        agent_id="'"$agent_id"'"
        pid="'"$pid"'"
        now_ts="'"$(now)"'"

        state=$(cat "$STATE_FILE")
        state=$(echo "$state" | jq \
            --arg id "$agent_id" \
            --argjson pid "$pid" \
            --arg ts "$now_ts" \
            ".agents[\$id] = {pid: \$pid, registered: \$ts, heartbeat: \$ts}")

        printf "%s\n" "$state" > "$STATE_FILE"
    '

    # Log activity (outside flock)
    log_activity "agent_register" agent_id="$agent_id" pid="$pid"

    echo "Registered agent: $agent_id (pid: $pid)"
}

cmd_unregister() {
    local agent_id="$1"
    local expected_pid="${2:-}"  # Optional: only unregister if PID matches

    [ -z "$agent_id" ] && { echo "Usage: $0 unregister <agent_id> [expected_pid]" >&2; exit 1; }

    # Atomic read-modify-write with exclusive lock
    local result=$(flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        agent_id="'"$agent_id"'"
        expected_pid="'"$expected_pid"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "NOT_FOUND"
            exit 0
        fi

        state=$(cat "$STATE_FILE")

        # Check if agent exists
        registered_pid=$(echo "$state" | jq -r --arg id "$agent_id" ".agents[\$id].pid // empty")

        if [ -z "$registered_pid" ]; then
            echo "NOT_FOUND"
            exit 0
        fi

        # If expected_pid provided, verify it matches
        if [ -n "$expected_pid" ] && [ "$registered_pid" != "$expected_pid" ]; then
            echo "PID_MISMATCH:$registered_pid"
            exit 0
        fi

        # Remove agent and their locks
        state=$(echo "$state" | jq "del(.agents[\"$agent_id\"])")
        state=$(echo "$state" | jq ".locks |= with_entries(select(.value.owner != \"$agent_id\"))")

        printf "%s\n" "$state" > "$STATE_FILE"
        echo "OK"
    ')

    case "$result" in
        OK)
            # Log activity (outside flock)
            log_activity "agent_unregister" agent_id="$agent_id"
            echo "Unregistered agent: $agent_id"
            ;;
        NOT_FOUND)
            echo "Agent $agent_id not found (already unregistered)"
            ;;
        PID_MISMATCH:*)
            local actual_pid="${result#PID_MISMATCH:}"
            echo "Refused to unregister $agent_id: PID mismatch (expected $expected_pid, actual $actual_pid)" >&2
            return 1
            ;;
    esac
}

cmd_heartbeat() {
    local agent_id="$1"

    [ -z "$agent_id" ] && { echo "Usage: $0 heartbeat <agent_id>" >&2; exit 1; }

    # Atomic read-modify-write with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        agent_id="'"$agent_id"'"
        now_ts="'"$(now)"'"

        if [ ! -f "$STATE_FILE" ]; then
            exit 0
        fi

        state=$(cat "$STATE_FILE")
        state=$(echo "$state" | jq \
            --arg id "$agent_id" \
            --arg ts "$now_ts" \
            "if .agents[\$id] then .agents[\$id].heartbeat = \$ts else . end")

        printf "%s\n" "$state" > "$STATE_FILE"
    '
}

# ============================================================
# LOCK COMMANDS
# ============================================================

cmd_lock() {
    local agent_id="$1"
    local file_path="$2"

    ([ -z "$agent_id" ] || [ -z "$file_path" ]) && {
        echo "Usage: $0 lock <agent_id> <file_path>" >&2
        exit 1
    }

    # Normalize path before entering lock
    file_path=$(realpath -m "$file_path" 2>/dev/null || echo "$file_path")

    # Atomic check-and-lock with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        agent_id="'"$agent_id"'"
        file_path="'"$file_path"'"
        now_ts="'"$(now)"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "{\"agents\":{},\"locks\":{},\"tasks\":{}}" > "$STATE_FILE"
        fi

        state=$(cat "$STATE_FILE")

        # Check if already locked by someone else
        current_owner=$(echo "$state" | jq -r --arg path "$file_path" ".locks[\$path].owner // empty")

        if [ -n "$current_owner" ] && [ "$current_owner" != "$agent_id" ]; then
            echo "FAILED: $file_path is locked by $current_owner" >&2
            exit 1
        fi

        # Acquire lock
        state=$(echo "$state" | jq \
            --arg path "$file_path" \
            --arg owner "$agent_id" \
            --arg ts "$now_ts" \
            ".locks[\$path] = {owner: \$owner, acquired: \$ts}")

        printf "%s\n" "$state" > "$STATE_FILE"
        echo "Locked: $file_path"
    '

    # Log activity (outside flock)
    log_activity "lock" agent_id="$agent_id" file_path="$file_path"
}

cmd_lock_all() {
    local agent_id="$1"
    shift
    local files=("$@")

    [ -z "$agent_id" ] || [ ${#files[@]} -eq 0 ] && {
        echo "Usage: $0 lock-all <agent_id> <file1> [file2] ..." >&2
        exit 1
    }

    # Normalize all paths before entering lock
    local normalized_files=()
    for file_path in "${files[@]}"; do
        normalized_files+=("$(realpath -m "$file_path" 2>/dev/null || echo "$file_path")")
    done

    # Convert array to newline-separated string for passing to subshell
    local files_str=$(printf '%s\n' "${normalized_files[@]}")
    local file_count=${#normalized_files[@]}

    # Atomic check-all-and-lock-all with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        agent_id="'"$agent_id"'"
        now_ts="'"$(now)"'"
        files_str="'"$files_str"'"
        file_count="'"$file_count"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "{\"agents\":{},\"locks\":{},\"tasks\":{}}" > "$STATE_FILE"
        fi

        state=$(cat "$STATE_FILE")

        # Check ALL files first
        blocked_by=""
        while IFS= read -r file_path; do
            [ -z "$file_path" ] && continue
            current_owner=$(echo "$state" | jq -r --arg path "$file_path" ".locks[\$path].owner // empty")

            if [ -n "$current_owner" ] && [ "$current_owner" != "$agent_id" ]; then
                blocked_by="$file_path (locked by $current_owner)"
                break
            fi
        done <<< "$files_str"

        if [ -n "$blocked_by" ]; then
            echo "FAILED: Cannot acquire all locks. Blocked by: $blocked_by" >&2
            exit 1
        fi

        # All clear - acquire all locks
        while IFS= read -r file_path; do
            [ -z "$file_path" ] && continue
            state=$(echo "$state" | jq \
                --arg path "$file_path" \
                --arg owner "$agent_id" \
                --arg ts "$now_ts" \
                ".locks[\$path] = {owner: \$owner, acquired: \$ts}")
        done <<< "$files_str"

        printf "%s\n" "$state" > "$STATE_FILE"
        echo "Locked $file_count files"
    '

    # Log activity (outside flock)
    log_activity "lock_all" agent_id="$agent_id" file_count="$file_count"
}

cmd_unlock() {
    local agent_id="$1"
    local file_path="$2"

    ([ -z "$agent_id" ] || [ -z "$file_path" ]) && {
        echo "Usage: $0 unlock <agent_id> <file_path>" >&2
        exit 1
    }

    file_path=$(realpath -m "$file_path" 2>/dev/null || echo "$file_path")

    # Atomic check-and-unlock with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        agent_id="'"$agent_id"'"
        file_path="'"$file_path"'"

        if [ ! -f "$STATE_FILE" ]; then
            exit 0
        fi

        state=$(cat "$STATE_FILE")
        current_owner=$(echo "$state" | jq -r --arg path "$file_path" ".locks[\$path].owner // empty")

        # Only owner can unlock (or if no owner)
        if [ -n "$current_owner" ] && [ "$current_owner" != "$agent_id" ]; then
            echo "FAILED: $file_path is locked by $current_owner, not $agent_id" >&2
            exit 1
        fi

        state=$(echo "$state" | jq --arg path "$file_path" "del(.locks[\$path])")

        # Auto-unblock tasks that were blocked on this file
        tasks_to_unblock=$(echo "$state" | jq -r --arg file "$file_path" ".tasks | to_entries[] | select(.value.blocked == true and .value.blocked_file == \$file) | .key")
        for task_id in $tasks_to_unblock; do
            state=$(echo "$state" | jq --arg id "$task_id" ".tasks[\$id].blocked = null | .tasks[\$id].blocked_by = null | .tasks[\$id].blocked_file = null | .tasks[\$id].blocked_at = null")
            echo "  Auto-unblocked task: $task_id"
        done

        printf "%s\n" "$state" > "$STATE_FILE"
        echo "Unlocked: $file_path"
    '

    # Log activity (outside flock)
    log_activity "unlock" agent_id="$agent_id" file_path="$file_path"
}

cmd_unlock_all() {
    local agent_id="$1"

    [ -z "$agent_id" ] && { echo "Usage: $0 unlock-all <agent_id>" >&2; exit 1; }

    # Atomic read-modify-write with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        agent_id="'"$agent_id"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "Released 0 locks"
            exit 0
        fi

        state=$(cat "$STATE_FILE")

        # Get files being unlocked (before removing them)
        unlocked_files=$(echo "$state" | jq -r --arg owner "$agent_id" ".locks | to_entries[] | select(.value.owner == \$owner) | .key")

        # Count and remove locks
        count=$(echo "$state" | jq --arg owner "$agent_id" "[.locks | to_entries[] | select(.value.owner == \$owner)] | length")
        state=$(echo "$state" | jq --arg owner "$agent_id" ".locks = (.locks | to_entries | map(select(.value.owner != \$owner)) | from_entries)")

        # Auto-unblock tasks that were blocked on these files
        unblocked_count=0
        for file in $unlocked_files; do
            # Find tasks blocked on this file and clear their blocked status
            tasks_to_unblock=$(echo "$state" | jq -r --arg file "$file" ".tasks | to_entries[] | select(.value.blocked == true and .value.blocked_file == \$file) | .key")
            for task_id in $tasks_to_unblock; do
                state=$(echo "$state" | jq --arg id "$task_id" ".tasks[\$id].blocked = null | .tasks[\$id].blocked_by = null | .tasks[\$id].blocked_file = null | .tasks[\$id].blocked_at = null")
                echo "  Auto-unblocked task: $task_id"
                unblocked_count=$((unblocked_count + 1))
            done
        done

        printf "%s\n" "$state" > "$STATE_FILE"
        echo "Released $count locks"
        if [ "$unblocked_count" -gt 0 ]; then
            echo "Unblocked $unblocked_count tasks"
        fi
    '

    # Log activity (outside flock)
    log_activity "unlock_all" agent_id="$agent_id"
}

cmd_check() {
    local agent_id="$1"
    local file_path="$2"

    [ -z "$file_path" ] && { echo "Usage: $0 check [agent_id] <file_path>" >&2; exit 1; }

    file_path=$(realpath -m "$file_path" 2>/dev/null || echo "$file_path")

    # Atomic cleanup + check with exclusive lock to prevent race
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        LOCK_TIMEOUT_SECONDS='"$LOCK_TIMEOUT_SECONDS"'
        agent_id="'"$agent_id"'"
        file_path="'"$file_path"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "UNLOCKED"
            exit 0
        fi

        state=$(cat "$STATE_FILE")
        now_ts=$(date +%s)
        changed=false

        # Cleanup dead agents inline
        agents=$(echo "$state" | jq -r ".agents | keys[]" 2>/dev/null || echo "")
        for aid in $agents; do
            pid=$(echo "$state" | jq -r ".agents[\"$aid\"].pid")
            heartbeat=$(echo "$state" | jq -r ".agents[\"$aid\"].heartbeat")
            hb_ts=$(date -d "$heartbeat" +%s 2>/dev/null || echo 0)
            age=$((now_ts - hb_ts))

            pid_alive=false
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                pid_alive=true
            fi

            if [ "$pid_alive" = false ] && [ "$age" -gt "$LOCK_TIMEOUT_SECONDS" ]; then
                state=$(echo "$state" | jq "del(.agents[\"$aid\"])")
                state=$(echo "$state" | jq ".locks |= with_entries(select(.value.owner != \"$aid\"))")
                changed=true
            fi
        done

        if [ "$changed" = true ]; then
            printf "%s\n" "$state" > "$STATE_FILE"
        fi

        # Now check the lock
        current_owner=$(echo "$state" | jq -r --arg path "$file_path" ".locks[\$path].owner // empty")

        if [ -z "$current_owner" ]; then
            echo "UNLOCKED"
            exit 0
        elif [ "$current_owner" = "$agent_id" ]; then
            echo "OWNED"
            exit 0
        else
            echo "LOCKED by $current_owner"
            exit 1
        fi
    '
}

# ============================================================
# TASK COMMANDS
# ============================================================

cmd_task_add() {
    local task_id="$1"
    local subject="$2"
    local description="${3:-}"
    local priority="${4:-3}"  # Default priority 3 (1=highest, 5=lowest)
    local created_by="${5:-}"  # Optional: agent who created the task
    local depends_on="${6:-}"  # Optional: comma-separated task IDs this depends on

    ([ -z "$task_id" ] || [ -z "$subject" ]) && {
        echo "Usage: $0 task-add <task_id> <subject> [description] [priority] [created_by] [depends_on]" >&2
        echo "  priority: 1=critical, 2=high, 3=normal (default), 4=low, 5=backlog" >&2
        echo "  depends_on: comma-separated task IDs (e.g., 'task-a,task-b')" >&2
        exit 1
    }

    # Validate priority is 1-5
    if ! [[ "$priority" =~ ^[1-5]$ ]]; then
        echo "ERROR: priority must be 1-5 (got: $priority)" >&2
        exit 1
    fi

    init_state

    # Convert comma-separated depends_on to JSON array
    local deps_json="null"
    if [ -n "$depends_on" ]; then
        deps_json=$(echo "$depends_on" | tr ',' '\n' | jq -R . | jq -s .)
    fi

    # Atomic read-modify-write with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        task_id="'"$task_id"'"
        subject="'"$subject"'"
        description="'"$description"'"
        priority="'"$priority"'"
        created_by="'"$created_by"'"
        deps_json='"'$deps_json'"'
        now_ts="'"$(now)"'"

        state=$(cat "$STATE_FILE")
        state=$(echo "$state" | jq \
            --arg id "$task_id" \
            --arg subj "$subject" \
            --arg desc "$description" \
            --argjson prio "$priority" \
            --arg ts "$now_ts" \
            --arg by "$created_by" \
            --argjson deps "$deps_json" \
            ".tasks[\$id] = {subject: \$subj, description: \$desc, priority: \$prio, status: \"pending\", owner: null, blocked: null, blocked_by: \$deps, blocked_file: null, created_at: \$ts, created_by: (if \$by == \"\" then null else \$by end), updated_at: \$ts, updated_by: (if \$by == \"\" then null else \$by end)}")

        printf "%s\n" "$state" > "$STATE_FILE"
    '

    # Log activity
    if [ -n "$created_by" ]; then
        log_activity "task_add" task_id="$task_id" priority="$priority" created_by="$created_by" depends_on="$depends_on"
    else
        log_activity "task_add" task_id="$task_id" priority="$priority" depends_on="$depends_on"
    fi

    if [ -n "$depends_on" ]; then
        echo "Added task: $task_id (priority: $priority, depends on: $depends_on)"
    else
        echo "Added task: $task_id (priority: $priority)"
    fi
}

cmd_task_claim() {
    local agent_id="$1"
    local task_id="$2"

    ([ -z "$agent_id" ] || [ -z "$task_id" ]) && {
        echo "Usage: $0 task-claim <agent_id> <task_id>" >&2
        exit 1
    }

    # Atomic check-and-claim with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        agent_id="'"$agent_id"'"
        task_id="'"$task_id"'"
        now_ts="'"$(now)"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "FAILED: Task $task_id does not exist" >&2
            exit 1
        fi

        state=$(cat "$STATE_FILE")
        current_owner=$(echo "$state" | jq -r --arg id "$task_id" ".tasks[\$id].owner // empty")
        status=$(echo "$state" | jq -r --arg id "$task_id" ".tasks[\$id].status // empty")

        if [ "$status" = "completed" ]; then
            echo "FAILED: Task $task_id is already completed" >&2
            exit 1
        fi

        if [ -n "$current_owner" ] && [ "$current_owner" != "null" ] && [ "$current_owner" != "$agent_id" ]; then
            echo "FAILED: Task $task_id is claimed by $current_owner" >&2
            exit 1
        fi

        # Check if agent already has a claimed task (one task per agent limit)
        existing_tasks=$(echo "$state" | jq --arg owner "$agent_id" \
            "[.tasks | to_entries[] | select(.value.owner == \$owner and .value.status == \"in_progress\")] | length")

        if [ -n "$existing_tasks" ] && [ "$existing_tasks" -gt 0 ]; then
            current_task=$(echo "$state" | jq -r --arg owner "$agent_id" \
                "[.tasks | to_entries[] | select(.value.owner == \$owner and .value.status == \"in_progress\")][0] | .key")
            echo "FAILED: Agent $agent_id already has a claimed task: $current_task" >&2
            echo "Release or complete $current_task before claiming a new task" >&2
            exit 1
        fi

        state=$(echo "$state" | jq \
            --arg id "$task_id" \
            --arg owner "$agent_id" \
            --arg ts "$now_ts" \
            ".tasks[\$id].owner = \$owner | .tasks[\$id].status = \"in_progress\" | .tasks[\$id].started_at = \$ts | .tasks[\$id].updated_at = \$ts | .tasks[\$id].updated_by = \$owner")

        printf "%s\n" "$state" > "$STATE_FILE"
        echo "Claimed task: $task_id"
    '

    # Log activity (outside flock)
    log_activity "task_claim" task_id="$task_id" agent_id="$agent_id"
}

cmd_task_complete() {
    local agent_id="$1"
    local task_id="$2"

    ([ -z "$agent_id" ] || [ -z "$task_id" ]) && {
        echo "Usage: $0 task-complete <agent_id> <task_id>" >&2
        exit 1
    }

    # Atomic read-modify-write with exclusive lock
    # Also performs inline cleanup of old completed tasks
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        task_id="'"$task_id"'"
        now_ts="'"$(now)"'"
        retention_days="'"$TASK_RETENTION_DAYS"'"

        if [ ! -f "$STATE_FILE" ]; then
            exit 0
        fi

        state=$(cat "$STATE_FILE")

        # Get the current owner to track who completed it
        completed_by=$(echo "$state" | jq -r --arg id "$task_id" ".tasks[\$id].owner // \"unknown\"")

        # Mark task as completed
        state=$(echo "$state" | jq \
            --arg id "$task_id" \
            --arg ts "$now_ts" \
            --arg by "$completed_by" \
            ".tasks[\$id].status = \"completed\" | .tasks[\$id].completed_at = \$ts | .tasks[\$id].completed_by = \$by | .tasks[\$id].updated_at = \$ts | .tasks[\$id].updated_by = \$by")

        # Auto-cleanup: remove completed tasks older than retention period
        cutoff_ts=$(date -u -d "$retention_days days ago" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || \
                    date -u -v-${retention_days}d +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "")

        if [ -n "$cutoff_ts" ]; then
            cleaned=$(echo "$state" | jq -r --arg cutoff "$cutoff_ts" \
                "[.tasks | to_entries[] | select(.value.status == \"completed\" and .value.completed != null and .value.completed < \$cutoff)] | length")

            if [ "$cleaned" -gt 0 ]; then
                state=$(echo "$state" | jq --arg cutoff "$cutoff_ts" \
                    ".tasks = (.tasks | to_entries | map(select(.value.status != \"completed\" or .value.completed_at == null or .value.completed_at >= \$cutoff)) | from_entries)")
                echo "  (auto-cleaned $cleaned old tasks)" >&2
            fi
        fi

        printf "%s\n" "$state" > "$STATE_FILE"
    '

    # Log activity (outside flock) - task completion
    log_activity "task_complete" task_id="$task_id" agent_id="$agent_id"

    echo "Completed task: $task_id"
}

cmd_task_release() {
    local agent_id="$1"
    local task_id="$2"

    ([ -z "$agent_id" ] || [ -z "$task_id" ]) && {
        echo "Usage: $0 task-release <agent_id> <task_id>" >&2
        exit 1
    }

    # Atomic read-modify-write with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        task_id="'"$task_id"'"
        agent_id="'"$agent_id"'"
        now_ts="'"$(now)"'"

        if [ ! -f "$STATE_FILE" ]; then
            exit 0
        fi

        state=$(cat "$STATE_FILE")
        state=$(echo "$state" | jq \
            --arg id "$task_id" \
            --arg ts "$now_ts" \
            --arg by "$agent_id" \
            ".tasks[\$id].owner = null | .tasks[\$id].status = \"pending\" | .tasks[\$id].updated_at = \$ts | .tasks[\$id].updated_by = \$by")

        printf "%s\n" "$state" > "$STATE_FILE"
    '

    # Log activity (outside flock) - task released/abandoned
    log_activity "task_release" task_id="$task_id" agent_id="$agent_id"

    echo "Released task: $task_id"
}

cmd_task_list() {
    local filter="${1:-all}"  # all, pending, available, blocked

    init_state
    # Read-only operation, shared lock is fine
    local state=$(atomic_read)

    # Priority labels for display
    # P1=critical, P2=high, P3=normal, P4=low, P5=backlog

    case "$filter" in
        pending)
            local tasks=$(echo "$state" | jq -r '[.tasks | to_entries[] | select(.value.status == "pending")] | sort_by(.value.priority // 3) | .[] | "P\(.value.priority // 3) \(.key) [pending] \(.value.owner // "unassigned"): \(.value.subject)"')
            ;;
        available)
            # Pending tasks that are not blocked and have no owner
            local tasks=$(echo "$state" | jq -r '[.tasks | to_entries[] | select(.value.status == "pending" and (.value.blocked == null or .value.blocked == false) and (.value.owner == null))] | sort_by(.value.priority // 3) | .[] | "P\(.value.priority // 3) \(.key): \(.value.subject)"')
            ;;
        blocked)
            local tasks=$(echo "$state" | jq -r '[.tasks | to_entries[] | select(.value.blocked == true)] | sort_by(.value.priority // 3) | .[] | "P\(.value.priority // 3) \(.key) [blocked by \(.value.blocked_by // "unknown")]: \(.value.subject)"')
            ;;
        *)
            local tasks=$(echo "$state" | jq -r '[.tasks | to_entries[]] | sort_by(.value.priority // 3) | .[] | "P\(.value.priority // 3) \(.key) [\(.value.status)]\(if .value.blocked == true then " BLOCKED" else "" end): \(.value.subject)"')
            ;;
    esac

    if [ -z "$tasks" ]; then
        echo "(no tasks)"
    else
        echo "$tasks"
    fi
}

cmd_task_search() {
    local keyword="$1"
    local status_filter="${2:-all}"  # all, pending, completed

    [ -z "$keyword" ] && {
        echo "Usage: $0 task-search <keyword> [status]" >&2
        echo "  Searches task IDs, subjects, and descriptions (case-insensitive)" >&2
        echo "  status: all (default), pending, completed" >&2
        exit 1
    }

    init_state
    local state=$(atomic_read)

    # Search in task id, subject, and description (case-insensitive)
    local keyword_lower=$(echo "$keyword" | tr '[:upper:]' '[:lower:]')

    case "$status_filter" in
        pending)
            local tasks=$(echo "$state" | jq -r --arg kw "$keyword_lower" \
                '[.tasks | to_entries[] | select(.value.status == "pending") | select((.key | ascii_downcase | contains($kw)) or (.value.subject | ascii_downcase | contains($kw)) or ((.value.description // "") | ascii_downcase | contains($kw)))] | sort_by(.value.priority // 3) | .[] | "P\(.value.priority // 3) \(.key) [\(.value.status)]: \(.value.subject)"')
            ;;
        completed)
            local tasks=$(echo "$state" | jq -r --arg kw "$keyword_lower" \
                '[.tasks | to_entries[] | select(.value.status == "completed") | select((.key | ascii_downcase | contains($kw)) or (.value.subject | ascii_downcase | contains($kw)) or ((.value.description // "") | ascii_downcase | contains($kw)))] | .[] | "\(.key) [completed]: \(.value.subject)"')
            ;;
        *)
            local tasks=$(echo "$state" | jq -r --arg kw "$keyword_lower" \
                '[.tasks | to_entries[] | select((.key | ascii_downcase | contains($kw)) or (.value.subject | ascii_downcase | contains($kw)) or ((.value.description // "") | ascii_downcase | contains($kw)))] | sort_by(.value.priority // 3) | .[] | "P\(.value.priority // 3) \(.key) [\(.value.status)]: \(.value.subject)"')
            ;;
    esac

    if [ -z "$tasks" ]; then
        echo "(no matching tasks)"
        exit 1
    else
        echo "$tasks"
        exit 0
    fi
}

cmd_task_stats() {
    init_state
    local state=$(atomic_read)

    local pending=$(echo "$state" | jq '[.tasks | to_entries[] | select(.value.status == "pending")] | length')
    local in_progress=$(echo "$state" | jq '[.tasks | to_entries[] | select(.value.status == "in_progress")] | length')
    local completed=$(echo "$state" | jq '[.tasks | to_entries[] | select(.value.status == "completed")] | length')
    local blocked=$(echo "$state" | jq '[.tasks | to_entries[] | select(.value.blocked == true)] | length')
    local total=$(echo "$state" | jq '.tasks | length')

    echo "Task Statistics:"
    echo "  Pending:     $pending"
    echo "  In Progress: $in_progress"
    echo "  Completed:   $completed"
    echo "  Blocked:     $blocked"
    echo "  ─────────────────"
    echo "  Total:       $total"
}

cmd_task_metrics() {
    local filter_prefix="${1:-}"  # Optional prefix filter (e.g., "m1", "test-crit")
    local metrics_file="$COORD_DIR/metrics.jsonl"

    # Create metrics file if doesn't exist
    [ ! -f "$metrics_file" ] && touch "$metrics_file"

    # Check if metrics file is empty
    if [ ! -s "$metrics_file" ]; then
        echo "No completed tasks yet (metrics file empty)"
        echo ""
        echo "Metrics will be tracked as you complete tasks using:"
        echo "  $0 task-done <agent> <task-id>"
        return 0
    fi

    echo "=========================================="
    echo "TASK PROGRESS METRICS"
    if [ -n "$filter_prefix" ]; then
        echo "Filter: $filter_prefix*"
    fi
    echo "=========================================="
    echo ""

    # Apply filter if specified
    local filter_jq='.'
    if [ -n "$filter_prefix" ]; then
        filter_jq="select(.task_id | startswith(\"$filter_prefix\"))"
    fi

    # === Overall Progress ===
    echo "=== OVERALL PROGRESS ==="
    echo ""

    local completed_count=$(jq -r "$filter_jq | .task_id" "$metrics_file" 2>/dev/null | wc -l)
    local state=$(atomic_read)
    local total_tasks=$(echo "$state" | jq '.tasks | length')
    local pending_tasks=$(echo "$state" | jq '[.tasks | to_entries[] | select(.value.status == "pending")] | length')
    local in_progress_tasks=$(echo "$state" | jq '[.tasks | to_entries[] | select(.value.status == "in_progress")] | length')

    if [ $total_tasks -gt 0 ]; then
        local pct=$((completed_count * 100 / (completed_count + total_tasks)))
        echo "✅ Completed: $completed_count"
        echo "📋 Pending: $pending_tasks"
        echo "🔄 In Progress: $in_progress_tasks"
        echo "Progress: $pct%"
    else
        echo "✅ Completed: $completed_count tasks"
    fi
    echo ""

    # === By Priority ===
    echo "=== BY PRIORITY ==="
    echo ""
    jq -r "$filter_jq | \"P\(.priority)\"" "$metrics_file" 2>/dev/null | sort | uniq -c | sort -k2 -n | while read count priority; do
        printf "  %s: %3d tasks\n" "$priority" "$count"
    done
    echo ""

    # === By Prefix (Top 10) ===
    echo "=== BY PREFIX (Top 10) ==="
    echo ""
    jq -r "$filter_jq | .prefix" "$metrics_file" 2>/dev/null | sort | uniq -c | sort -rn | head -10 | while read count prefix; do
        printf "  %-15s %3d tasks\n" "$prefix:" "$count"
    done
    echo ""

    # === Velocity (Last 7 Days) ===
    echo "=== VELOCITY (Last 7 days) ==="
    echo ""
    local seven_days_ago=$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-7d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)
    local recent_count=$(jq -r "$filter_jq | select(.timestamp >= \"$seven_days_ago\") | .task_id" "$metrics_file" 2>/dev/null | wc -l)

    if [ $recent_count -gt 0 ]; then
        local avg_per_day=$(echo "scale=1; $recent_count / 7" | bc 2>/dev/null || echo "~$((recent_count / 7))")
        echo "Tasks completed: $recent_count"
        echo "Avg per day: $avg_per_day"

        if [ $pending_tasks -gt 0 ] && [ $(echo "$avg_per_day > 0" | bc 2>/dev/null || echo 0) -eq 1 ]; then
            local eta_days=$(echo "scale=0; $pending_tasks / $avg_per_day" | bc 2>/dev/null || echo "N/A")
            echo "ETA at current rate: ~$eta_days days"
        fi
    else
        echo "No tasks completed in last 7 days"
    fi
    echo ""

    # === Recent Completions ===
    echo "=== RECENT COMPLETIONS (Last 5) ==="
    echo ""
    jq -r "$filter_jq | \"\(.timestamp | split(\"T\")[0]) \(.task_id) (P\(.priority))\"" "$metrics_file" 2>/dev/null | tail -5
    echo ""

    # === Average Duration ===
    echo "=== TASK DURATION ==="
    echo ""
    local avg_duration=$(jq -r "$filter_jq | select(.duration_seconds > 0) | .duration_seconds" "$metrics_file" 2>/dev/null | awk '{sum+=$1; count++} END {if(count>0) print int(sum/count); else print 0}')

    if [ "$avg_duration" -gt 0 ]; then
        local avg_hours=$((avg_duration / 3600))
        local avg_mins=$(( (avg_duration % 3600) / 60 ))
        echo "Average time per task: ${avg_hours}h ${avg_mins}m"
    else
        echo "Duration data not available"
    fi
    echo ""
}

cmd_task_insights() {
    local activity_file="$COORD_DIR/activity.jsonl"

    # Create activity file if doesn't exist
    [ ! -f "$activity_file" ] && touch "$activity_file"

    # Check if activity file is empty
    if [ ! -s "$activity_file" ]; then
        echo "No activity logged yet (activity file empty)"
        echo ""
        echo "Activity will be tracked automatically as you use coordination commands"
        return 0
    fi

    echo "=========================================="
    echo "TASK INSIGHTS & PERFORMANCE METRICS"
    echo "=========================================="
    echo ""

    # === 1. Task Completion Times ===
    echo "=== TASK COMPLETION TIMES ==="
    echo ""

    # Build a map of task_id -> {claimed_at, completed_at}
    local task_times=$(mktemp)
    grep '"action":"task_claim"' "$activity_file" | jq -r '[.timestamp, .task_id] | @tsv' > "$task_times.claims"
    grep '"action":"task_complete"' "$activity_file" | jq -r '[.timestamp, .task_id] | @tsv' > "$task_times.completes"

    local total_duration=0
    local task_count=0
    local min_duration=999999
    local max_duration=0

    while IFS=$'\t' read -r complete_ts task_id; do
        # Find corresponding claim
        claim_ts=$(grep -F "$task_id" "$task_times.claims" | head -1 | cut -f1)

        if [ -n "$claim_ts" ]; then
            # Calculate duration in seconds
            claim_epoch=$(date -d "$claim_ts" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$claim_ts" +%s 2>/dev/null)
            complete_epoch=$(date -d "$complete_ts" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$complete_ts" +%s 2>/dev/null)
            duration=$((complete_epoch - claim_epoch))

            if [ $duration -ge 0 ]; then
                total_duration=$((total_duration + duration))
                task_count=$((task_count + 1))

                [ $duration -lt $min_duration ] && min_duration=$duration
                [ $duration -gt $max_duration ] && max_duration=$duration
            fi
        fi
    done < "$task_times.completes"

    if [ $task_count -gt 0 ]; then
        local avg_duration=$((total_duration / task_count))
        local avg_minutes=$((avg_duration / 60))
        local avg_hours=$((avg_minutes / 60))
        local avg_mins=$((avg_minutes % 60))
        local min_minutes=$((min_duration / 60))
        local max_minutes=$((max_duration / 60))

        echo "Completed tasks: $task_count"
        echo "Average time: ${avg_hours}h ${avg_mins}m (${avg_duration}s)"
        echo "Fastest: ${min_minutes}m (${min_duration}s)"
        echo "Slowest: ${max_minutes}m (${max_duration}s)"
    else
        echo "No completed tasks with timing data"
    fi

    rm -f "$task_times" "$task_times.claims" "$task_times.completes"
    echo ""

    # === 2. Orphaned Tasks ===
    echo "=== ORPHANED TASKS (Claimed but never completed/released) ==="
    echo ""

    local claimed_tasks=$(mktemp)
    local completed_tasks=$(mktemp)
    local released_tasks=$(mktemp)

    grep '"action":"task_claim"' "$activity_file" | jq -r '.task_id' | sort -u > "$claimed_tasks"
    grep '"action":"task_complete"' "$activity_file" | jq -r '.task_id' | sort -u > "$completed_tasks"
    grep '"action":"task_release"' "$activity_file" | jq -r '.task_id' | sort -u > "$released_tasks"

    # Find claimed tasks that were never completed or released
    local orphaned=$(comm -23 <(sort "$claimed_tasks") <(cat "$completed_tasks" "$released_tasks" | sort -u))
    local orphaned_count=0
    if [ -n "$orphaned" ]; then
        orphaned_count=$(echo "$orphaned" | wc -l | tr -d ' ')
    fi

    if [ "$orphaned_count" -gt 0 ] 2>/dev/null; then
        echo "⚠️  Orphaned tasks: $orphaned_count"
        echo "$orphaned" | head -10 | while read task_id; do
            echo "  - $task_id"
        done
        [ "$orphaned_count" -gt 10 ] && echo "  ... and $((orphaned_count - 10)) more"
    else
        echo "✅ No orphaned tasks"
    fi

    rm -f "$claimed_tasks" "$completed_tasks" "$released_tasks"
    echo ""

    # === 3. Blocked Tasks Analysis ===
    echo "=== BLOCKED TASKS (Never unblocked) ==="
    echo ""

    local blocked_tasks=$(mktemp)
    local unblocked_tasks=$(mktemp)

    grep '"action":"task_block"' "$activity_file" | jq -r '.task_id' | sort -u > "$blocked_tasks"
    grep '"action":"task_unblock"' "$activity_file" | jq -r '.task_id' | sort -u > "$unblocked_tasks"

    # Find blocked tasks that were never unblocked
    local stuck_blocked=$(comm -23 <(sort "$blocked_tasks") <(sort "$unblocked_tasks"))
    local stuck_count=0
    if [ -n "$stuck_blocked" ]; then
        stuck_count=$(echo "$stuck_blocked" | wc -l | tr -d ' ')
    fi

    if [ "$stuck_count" -gt 0 ] 2>/dev/null; then
        echo "⚠️  Permanently blocked: $stuck_count tasks"
        echo "$stuck_blocked" | head -10 | while read task_id; do
            # Find what blocked it
            blocker=$(grep "\"task_id\":\"$task_id\"" "$activity_file" | grep '"action":"task_block"' | tail -1 | jq -r '.blocked_by')
            echo "  - $task_id (blocked by: $blocker)"
        done
        [ "$stuck_count" -gt 10 ] && echo "  ... and $((stuck_count - 10)) more"
    else
        echo "✅ No permanently blocked tasks"
    fi

    rm -f "$blocked_tasks" "$unblocked_tasks"
    echo ""

    # === 4. Velocity (Tasks completed per day) ===
    echo "=== VELOCITY (Last 7 days) ==="
    echo ""

    local seven_days_ago=$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-7d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)
    local recent_completions=$(grep '"action":"task_complete"' "$activity_file" | jq -r --arg cutoff "$seven_days_ago" 'select(.timestamp >= $cutoff) | .task_id' | wc -l)

    if [ $recent_completions -gt 0 ]; then
        local avg_per_day=$(echo "scale=1; $recent_completions / 7" | bc 2>/dev/null || echo "~$((recent_completions / 7))")
        echo "Tasks completed: $recent_completions"
        echo "Average per day: $avg_per_day"
    else
        echo "No tasks completed in last 7 days"
    fi
    echo ""

    # === 5. Concurrency Analysis ===
    echo "=== CONCURRENCY ANALYSIS ==="
    echo ""

    # Count max concurrent agents
    local max_concurrent=0
    local peak_time=""
    local agent_activity=$(mktemp)

    # Get all agent register/unregister events with timestamps
    grep -E '"action":"(agent_register|agent_unregister)"' "$activity_file" | \
        jq -r '[.timestamp, .action, .agent_id] | @tsv' | \
        sort -k1 > "$agent_activity"

    # Track agents over time using associative array simulation
    local active_count=0
    declare -A active_map
    while IFS=$'\t' read -r ts action agent_id; do
        if [ "$action" = "agent_register" ]; then
            active_map["$agent_id"]=1
        else
            unset active_map["$agent_id"]
        fi

        # Count active agents
        active_count=${#active_map[@]}
        if [ $active_count -gt $max_concurrent ]; then
            max_concurrent=$active_count
            peak_time="$ts"
        fi
    done < "$agent_activity"

    echo "Max concurrent agents: $max_concurrent"
    if [ $max_concurrent -gt 0 ] && [ -n "$peak_time" ]; then
        echo "Peak time: $peak_time"
    fi

    rm -f "$agent_activity"
    echo ""

    # === 6. Performance Impact Analysis ===
    if [ $task_count -gt 5 ]; then
        echo "=== PERFORMANCE IMPACT (Concurrency vs Speed) ==="
        echo ""

        echo "📊 To analyze performance impact of concurrency:"
        echo "   1. Tasks completed: $task_count"
        echo "   2. Average duration: ${avg_duration}s"
        echo "   3. Max concurrent agents: $max_concurrent"
        echo ""
        echo "   Compare these metrics before and after running more agents"
        echo "   to determine optimal concurrency level."
        echo ""
    fi

    echo "=========================================="
    echo ""
    echo "📁 Activity log: $activity_file"
    echo "   $(wc -l < "$activity_file") total events logged"
}

cmd_task_cleanup() {
    local days="${1:-7}"  # Default: remove tasks completed more than 7 days ago
    local dry_run="${2:-}"

    # Validate days is a number
    if ! [[ "$days" =~ ^[0-9]+$ ]]; then
        echo "Usage: $0 task-cleanup [days] [--dry-run]" >&2
        echo "  Removes completed tasks older than <days> (default: 7)" >&2
        echo "  --dry-run: Show what would be removed without removing" >&2
        exit 1
    fi

    init_state

    # Calculate cutoff timestamp
    local cutoff_ts=$(date -u -d "$days days ago" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || \
                      date -u -v-${days}d +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null)

    if [ -z "$cutoff_ts" ]; then
        echo "ERROR: Could not calculate cutoff date" >&2
        exit 1
    fi

    echo "Cleaning up tasks completed before: $cutoff_ts"
    echo ""

    if [ "$dry_run" = "--dry-run" ]; then
        # Dry run - just show what would be removed
        local state=$(atomic_read)
        local old_tasks=$(echo "$state" | jq -r --arg cutoff "$cutoff_ts" \
            '.tasks | to_entries[] | select(.value.status == "completed" and .value.completed_at != null and .value.completed_at < $cutoff) | "\(.key): \(.value.subject) (completed: \(.value.completed_at))"')

        if [ -z "$old_tasks" ]; then
            echo "(no tasks to clean up)"
        else
            echo "Would remove:"
            echo "$old_tasks"
        fi
    else
        # Actually remove old tasks
        flock -x "$LOCK_FILE" bash -c '
            STATE_FILE="'"$STATE_FILE"'"
            cutoff_ts="'"$cutoff_ts"'"

            if [ ! -f "$STATE_FILE" ]; then
                echo "No state file"
                exit 0
            fi

            state=$(cat "$STATE_FILE")

            # Count tasks to remove
            count=$(echo "$state" | jq --arg cutoff "$cutoff_ts" \
                "[.tasks | to_entries[] | select(.value.status == \"completed\" and .value.completed != null and .value.completed < \$cutoff)] | length")

            # Show what we are removing
            echo "$state" | jq -r --arg cutoff "$cutoff_ts" \
                ".tasks | to_entries[] | select(.value.status == \"completed\" and .value.completed != null and .value.completed < \$cutoff) | \"  Removed: \(.key)\""

            # Remove old completed tasks
            state=$(echo "$state" | jq --arg cutoff "$cutoff_ts" \
                ".tasks = (.tasks | to_entries | map(select(.value.status != \"completed\" or .value.completed_at == null or .value.completed_at >= \$cutoff)) | from_entries)")

            printf "%s\n" "$state" > "$STATE_FILE"
            echo ""
            echo "Cleaned up $count completed tasks"
        '
    fi
}

cmd_task_archive() {
    local output_file="${1:-tasks-archive-$(date +%Y%m%d).json}"

    init_state
    local state=$(atomic_read)

    # Export completed tasks to file
    echo "$state" | jq '.tasks | to_entries | map(select(.value.status == "completed")) | from_entries' > "$output_file"

    local count=$(jq 'length' "$output_file")
    echo "Archived $count completed tasks to: $output_file"
}

cmd_task_get() {
    local task_id="$1"

    [ -z "$task_id" ] && {
        echo "Usage: $0 task-get <task_id>" >&2
        exit 1
    }

    init_state
    local state=$(atomic_read)
    local task=$(echo "$state" | jq -r --arg id "$task_id" '.tasks[$id] // empty')

    if [ -z "$task" ] || [ "$task" = "null" ]; then
        echo "Task not found: $task_id" >&2
        exit 1
    fi

    echo "$task" | jq .
}

cmd_task_block() {
    local task_id="$1"
    local blocked_by="$2"
    local blocked_file="$3"

    ([ -z "$task_id" ] || [ -z "$blocked_by" ]) && {
        echo "Usage: $0 task-block <task_id> <blocked_by_agent> [blocked_file]" >&2
        exit 1
    }

    # Normalize blocked_file path (same as lock command)
    if [ -n "$blocked_file" ]; then
        blocked_file=$(realpath -m "$blocked_file" 2>/dev/null || echo "$blocked_file")
    fi

    # Atomic read-modify-write with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        task_id="'"$task_id"'"
        blocked_by="'"$blocked_by"'"
        blocked_file="'"$blocked_file"'"
        now_ts="'"$(now)"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "FAILED: State file does not exist" >&2
            exit 1
        fi

        state=$(cat "$STATE_FILE")

        # Validate state is valid JSON
        if [ -z "$state" ] || ! echo "$state" | jq empty >/dev/null 2>&1; then
            echo "FAILED: State file is corrupted or empty" >&2
            exit 1
        fi

        # Check task exists
        exists=$(echo "$state" | jq -r --arg id "$task_id" ".tasks[\$id] // empty")
        if [ -z "$exists" ] || [ "$exists" = "null" ]; then
            echo "FAILED: Task $task_id does not exist" >&2
            exit 1
        fi

        # Execute jq transformation with error handling
        new_state=$(echo "$state" | jq \
            --arg id "$task_id" \
            --arg by "$blocked_by" \
            --arg file "$blocked_file" \
            --arg ts "$now_ts" \
            ".tasks[\$id].blocked = true | .tasks[\$id].blocked_by = \$by | .tasks[\$id].blocked_file = \$file | .tasks[\$id].blocked_at = \$ts | .tasks[\$id].status = \"pending\" | .tasks[\$id].owner = null | .tasks[\$id].updated_at = \$ts | .tasks[\$id].updated_by = \$by" 2>&1)
        jq_exit=$?

        if [ $jq_exit -ne 0 ] || [ -z "$new_state" ]; then
            echo "FAILED: jq transformation failed: $new_state" >&2
            exit 1
        fi

        # Atomic write with verification using temp file
        temp_file="${STATE_FILE}.tmp.$$"
        printf "%s\n" "$new_state" > "$temp_file" 2>/dev/null
        if [ $? -ne 0 ] || ! jq empty "$temp_file" >/dev/null 2>&1; then
            echo "FAILED: Could not write state file (disk full or invalid JSON)" >&2
            rm -f "$temp_file"
            exit 1
        fi
        mv "$temp_file" "$STATE_FILE"

        echo "Blocked task: $task_id (by $blocked_by on $blocked_file)"
    '

    # Log activity (outside flock)
    if [ -n "$blocked_file" ]; then
        log_activity "task_block" task_id="$task_id" blocked_by="$blocked_by" blocked_file="$blocked_file"
    else
        log_activity "task_block" task_id="$task_id" blocked_by="$blocked_by"
    fi
}

cmd_task_unblock() {
    local task_id="$1"
    local unblocked_by="${2:-}"  # Optional: agent who unblocked

    [ -z "$task_id" ] && {
        echo "Usage: $0 task-unblock <task_id> [agent_id]" >&2
        exit 1
    }

    # Atomic read-modify-write with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        task_id="'"$task_id"'"
        unblocked_by="'"$unblocked_by"'"
        now_ts="'"$(now)"'"

        if [ ! -f "$STATE_FILE" ]; then
            exit 0
        fi

        state=$(cat "$STATE_FILE")

        # Validate state is valid JSON
        if [ -z "$state" ] || ! echo "$state" | jq empty >/dev/null 2>&1; then
            echo "FAILED: State file is corrupted or empty" >&2
            exit 1
        fi

        # Execute jq transformation with error handling
        new_state=$(echo "$state" | jq \
            --arg id "$task_id" \
            --arg ts "$now_ts" \
            --arg by "$unblocked_by" \
            ".tasks[\$id].blocked = null | .tasks[\$id].blocked_by = null | .tasks[\$id].blocked_file = null | .tasks[\$id].blocked_at = null | .tasks[\$id].updated_at = \$ts | .tasks[\$id].updated_by = (if \$by == \"\" then null else \$by end)" 2>&1)
        jq_exit=$?

        if [ $jq_exit -ne 0 ] || [ -z "$new_state" ]; then
            echo "FAILED: jq transformation failed: $new_state" >&2
            exit 1
        fi

        # Atomic write with verification using temp file
        temp_file="${STATE_FILE}.tmp.$$"
        printf "%s\n" "$new_state" > "$temp_file" 2>/dev/null
        if [ $? -ne 0 ] || ! jq empty "$temp_file" >/dev/null 2>&1; then
            echo "FAILED: Could not write state file (disk full or invalid JSON)" >&2
            rm -f "$temp_file"
            exit 1
        fi
        mv "$temp_file" "$STATE_FILE"

        echo "Unblocked task: $task_id"
    '

    # Log activity (outside flock)
    if [ -n "$unblocked_by" ]; then
        log_activity "task_unblock" task_id="$task_id" unblocked_by="$unblocked_by"
    else
        log_activity "task_unblock" task_id="$task_id"
    fi
}

cmd_task_priority() {
    local task_id="$1"
    local priority="$2"
    local updated_by="${3:-}"  # Optional: agent who changed priority

    ([ -z "$task_id" ] || [ -z "$priority" ]) && {
        echo "Usage: $0 task-priority <task_id> <priority> [agent_id]" >&2
        echo "  priority: 1=critical, 2=high, 3=normal, 4=low, 5=backlog" >&2
        exit 1
    }

    # Validate priority is 1-5
    if ! [[ "$priority" =~ ^[1-5]$ ]]; then
        echo "ERROR: priority must be 1-5 (got: $priority)" >&2
        exit 1
    fi

    # Atomic read-modify-write with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        task_id="'"$task_id"'"
        priority="'"$priority"'"
        updated_by="'"$updated_by"'"
        now_ts="'"$(now)"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "FAILED: Task $task_id does not exist" >&2
            exit 1
        fi

        state=$(cat "$STATE_FILE")

        # Check task exists
        exists=$(echo "$state" | jq -r --arg id "$task_id" ".tasks[\$id] // empty")
        if [ -z "$exists" ] || [ "$exists" = "null" ]; then
            echo "FAILED: Task $task_id does not exist" >&2
            exit 1
        fi

        state=$(echo "$state" | jq \
            --arg id "$task_id" \
            --argjson prio "$priority" \
            --arg ts "$now_ts" \
            --arg by "$updated_by" \
            ".tasks[\$id].priority = \$prio | .tasks[\$id].updated_at = \$ts | .tasks[\$id].updated_by = (if \$by == \"\" then null else \$by end)")

        printf "%s\n" "$state" > "$STATE_FILE"
        echo "Set priority: $task_id → P$priority"
    '

    # Log activity (outside flock)
    if [ -n "$updated_by" ]; then
        log_activity "task_priority" task_id="$task_id" priority="$priority" updated_by="$updated_by"
    else
        log_activity "task_priority" task_id="$task_id" priority="$priority"
    fi
}

cmd_task_prefix_set() {
    local prefix="$1"
    local priority="$2"

    ([ -z "$prefix" ] || [ -z "$priority" ]) && {
        echo "Usage: $0 task-prefix-set <prefix> <priority>" >&2
        echo "  Set priority for task prefix (lower number = higher priority)" >&2
        echo "  Example: task-prefix-set m3 1  (m3 tasks before others)" >&2
        echo "           task-prefix-set m4 2  (m4 tasks after m3)" >&2
        exit 1
    }

    # Validate priority is a number
    if ! [[ "$priority" =~ ^[0-9]+$ ]]; then
        echo "Error: Priority must be a number" >&2
        exit 1
    fi

    init_state

    # Use --arg to properly handle special characters in prefix names
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        prefix="'"$prefix"'"
        priority='"$priority"'

        if [ ! -f "$STATE_FILE" ]; then
            echo "{\"agents\":{},\"locks\":{},\"tasks\":{},\"prefix_priorities\":{}}" > "$STATE_FILE"
        fi

        state=$(cat "$STATE_FILE")

        # Validate state is valid JSON
        if [ -z "$state" ] || ! echo "$state" | jq empty >/dev/null 2>&1; then
            echo "WARNING: State file corrupted, reinitializing" >&2
            state="{\"agents\":{},\"locks\":{},\"tasks\":{},\"prefix_priorities\":{}}"
            echo "$state" > "$STATE_FILE"
        fi

        # Use --arg for safe prefix handling (dots, hyphens, etc.)
        new_state=$(echo "$state" | jq --arg pfx "$prefix" --argjson prio "$priority" ".prefix_priorities[\$pfx] = \$prio" 2>&1)
        jq_exit=$?

        if [ $jq_exit -ne 0 ] || [ -z "$new_state" ]; then
            echo "ERROR: jq transformation failed: $new_state" >&2
            exit 1
        fi

        # Atomic write with verification using temp file
        temp_file="${STATE_FILE}.tmp.$$"
        printf "%s\n" "$new_state" > "$temp_file" 2>/dev/null
        if [ $? -ne 0 ] || ! jq empty "$temp_file" >/dev/null 2>&1; then
            echo "FAILED: Could not write state file (disk full or invalid JSON)" >&2
            rm -f "$temp_file"
            exit 1
        fi
        mv "$temp_file" "$STATE_FILE"
    ' >/dev/null

    echo "Set prefix priority: $prefix = $priority"
}

cmd_task_prefix_list() {
    init_state
    local state=$(atomic_read)

    local prefixes=$(echo "$state" | jq -r '.prefix_priorities // {} | to_entries | sort_by(.value) | .[] | "Priority \(.value): \(.key)"')

    if [ -z "$prefixes" ]; then
        echo "(no prefix priorities configured)"
    else
        echo "Prefix Priorities (lower = higher priority):"
        echo "$prefixes"
    fi
}

cmd_task_prefix_clear() {
    local prefix="$1"

    [ -z "$prefix" ] && {
        echo "Usage: $0 task-prefix-clear <prefix>" >&2
        echo "  Remove priority configuration for prefix" >&2
        exit 1
    }

    init_state

    # Use --arg to properly handle special characters in prefix names
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        prefix="'"$prefix"'"

        if [ ! -f "$STATE_FILE" ]; then
            exit 0
        fi

        state=$(cat "$STATE_FILE")

        # Validate state is valid JSON
        if [ -z "$state" ] || ! echo "$state" | jq empty >/dev/null 2>&1; then
            echo "WARNING: State file corrupted" >&2
            exit 1
        fi

        # Use --arg for safe prefix handling
        new_state=$(echo "$state" | jq --arg pfx "$prefix" "del(.prefix_priorities[\$pfx])" 2>&1)
        jq_exit=$?

        if [ $jq_exit -ne 0 ] || [ -z "$new_state" ]; then
            echo "ERROR: jq transformation failed: $new_state" >&2
            exit 1
        fi

        # Atomic write with verification using temp file
        temp_file="${STATE_FILE}.tmp.$$"
        printf "%s\n" "$new_state" > "$temp_file" 2>/dev/null
        if [ $? -ne 0 ] || ! jq empty "$temp_file" >/dev/null 2>&1; then
            echo "FAILED: Could not write state file" >&2
            rm -f "$temp_file"
            exit 1
        fi
        mv "$temp_file" "$STATE_FILE"
    ' >/dev/null

    echo "Cleared prefix priority for: $prefix"
}

cmd_task_depends() {
    local task_id="$1"
    shift
    local blocking_tasks="$@"

    [ -z "$task_id" ] && {
        echo "Usage: $0 task-depends <task_id> <blocking_task_ids...>" >&2
        echo "  Set task dependencies (task_id depends on blocking_task_ids)" >&2
        echo "  Example: task-depends m4-001 m3-001 m3-002" >&2
        echo "           (m4-001 cannot start until m3-001 and m3-002 are complete)" >&2
        exit 1
    }

    [ -z "$blocking_tasks" ] && {
        echo "Error: Must specify at least one blocking task" >&2
        exit 1
    }

    init_state

    # Convert space-separated list to JSON array
    local deps_json=$(printf '%s\n' $blocking_tasks | jq -R . | jq -s .)

    # Check for cycles before setting dependency
    local state=$(atomic_read)

    # Simple cycle detection: check immediate dependencies only (depth 1-2)
    # Full transitive cycle detection is complex in jq; this catches most common cases
    for blocking_task in $blocking_tasks; do
        # Direct cycle: blocking_task depends on task_id
        local blocking_deps=$(echo "$state" | jq -r --arg id "$blocking_task" '.tasks[$id].blocked_by // [] | .[]' 2>/dev/null)

        for dep in $blocking_deps; do
            if [ "$dep" = "$task_id" ]; then
                echo "ERROR: Cannot add dependency - would create cycle" >&2
                echo "ERROR: $task_id -> $blocking_task -> $task_id" >&2
                exit 1
            fi

            # Check one level deeper (2-hop cycles)
            local second_level=$(echo "$state" | jq -r --arg id "$dep" '.tasks[$id].blocked_by // [] | .[]' 2>/dev/null)
            for dep2 in $second_level; do
                if [ "$dep2" = "$task_id" ]; then
                    echo "ERROR: Cannot add dependency - would create cycle" >&2
                    echo "ERROR: $task_id -> $blocking_task -> $dep -> $task_id" >&2
                    exit 1
                fi
            done
        done
    done

    # Use jq --argjson to properly pass JSON array and --arg for task_id
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        task_id="'"$task_id"'"
        deps_json='"'$deps_json'"'

        if [ ! -f "$STATE_FILE" ]; then
            echo "{\"agents\":{},\"locks\":{},\"tasks\":{}}" > "$STATE_FILE"
        fi

        state=$(cat "$STATE_FILE")

        # Validate state is valid JSON
        if [ -z "$state" ] || ! echo "$state" | jq empty >/dev/null 2>&1; then
            echo "WARNING: State file corrupted, reinitializing" >&2
            state="{\"agents\":{},\"locks\":{},\"tasks\":{}}"
            echo "$state" > "$STATE_FILE"
        fi

        # Execute jq transformation with proper argument passing
        new_state=$(echo "$state" | jq --arg id "$task_id" --argjson deps "$deps_json" ".tasks[\$id].blocked_by = \$deps" 2>&1)
        jq_exit=$?

        if [ $jq_exit -ne 0 ] || [ -z "$new_state" ]; then
            echo "ERROR: jq transformation failed: $new_state" >&2
            exit 1
        fi

        printf "%s\n" "$new_state" > "$STATE_FILE"
    ' >/dev/null

    # Log activity (outside flock)
    log_activity "task_depends" task_id="$task_id" blocked_by="$blocking_tasks"

    echo "Set dependencies for $task_id:"
    echo "  Blocked by: $blocking_tasks"
}

cmd_task_depends_clear() {
    local task_id="$1"

    [ -z "$task_id" ] && {
        echo "Usage: $0 task-depends-clear <task_id>" >&2
        echo "  Remove all dependencies from a task" >&2
        exit 1
    }

    init_state

    # Use jq --arg to properly escape task_id
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        task_id="'"$task_id"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "{\"agents\":{},\"locks\":{},\"tasks\":{}}" > "$STATE_FILE"
        fi

        state=$(cat "$STATE_FILE")

        # Validate state is valid JSON
        if [ -z "$state" ] || ! echo "$state" | jq empty >/dev/null 2>&1; then
            echo "WARNING: State file corrupted, reinitializing" >&2
            state="{\"agents\":{},\"locks\":{},\"tasks\":{}}"
            echo "$state" > "$STATE_FILE"
        fi

        # Execute jq transformation with proper argument passing
        new_state=$(echo "$state" | jq --arg id "$task_id" ".tasks[\$id].blocked_by = null" 2>&1)
        jq_exit=$?

        if [ $jq_exit -ne 0 ] || [ -z "$new_state" ]; then
            echo "ERROR: jq transformation failed: $new_state" >&2
            exit 1
        fi

        printf "%s\n" "$new_state" > "$STATE_FILE"
    ' >/dev/null

    echo "Cleared dependencies for: $task_id"
}

cmd_task_import() {
    local json_file="$1"
    local dry_run="${2:-}"

    [ -z "$json_file" ] && {
        echo "Usage: $0 task-import <json_file> [--dry-run]" >&2
        echo "  Import tasks from JSON file" >&2
        echo "  --dry-run: Show what would be imported without creating" >&2
        echo "" >&2
        echo "JSON format:" >&2
        echo '  {' >&2
        echo '    "tasks": [' >&2
        echo '      {' >&2
        echo '        "id": "task-001",' >&2
        echo '        "enabled": true,' >&2
        echo '        "title": "Task title",' >&2
        echo '        "priority": "HIGH",' >&2
        echo '        "description": "Task description",' >&2
        echo '        "dependencies": {' >&2
        echo '          "blocked_by": ["other-task-id"]' >&2
        echo '        }' >&2
        echo '      }' >&2
        echo '    ]' >&2
        echo '  }' >&2
        exit 1
    }

    if [ ! -f "$json_file" ]; then
        echo "Error: File not found: $json_file" >&2
        exit 1
    fi

    # Validate JSON
    if ! jq empty "$json_file" 2>/dev/null; then
        echo "Error: Invalid JSON file" >&2
        exit 1
    fi

    init_state

    # Map priority strings to numbers
    map_priority() {
        case "$1" in
            "CRITICAL") echo "1" ;;
            "HIGH") echo "2" ;;
            "MEDIUM"|"NORMAL") echo "3" ;;
            "LOW") echo "4" ;;
            "BACKLOG") echo "5" ;;
            [1-5]) echo "$1" ;;
            *) echo "3" ;;
        esac
    }

    local created=0
    local skipped=0
    local total=$(jq '[.tasks[] | select(.enabled == true or .enabled == null)] | length' "$json_file")

    if [ "$dry_run" = "--dry-run" ]; then
        echo "DRY RUN: Would import $total tasks from $json_file"
        echo ""
    else
        echo "Importing $total tasks from $json_file..."
        echo ""
    fi

    # Read state once to check existing tasks
    local state=$(atomic_read)

    # Get all task JSON objects into an array
    local tasks_json=$(jq -c '.tasks[] | select(.enabled == true or .enabled == null)' "$json_file")

    # Process each enabled task
    while IFS= read -r task; do
        [ -z "$task" ] && continue

        local task_id=$(echo "$task" | jq -r '.id')
        local title=$(echo "$task" | jq -r '.title')
        local description=$(echo "$task" | jq -r '.description // ""')
        local priority_str=$(echo "$task" | jq -r '.priority // "NORMAL"')
        local priority=$(map_priority "$priority_str")
        local deps=$(echo "$task" | jq -r '.dependencies.blocked_by // [] | join(",")')

        # Check if task already exists
        if echo "$state" | jq -e ".tasks.\"$task_id\"" >/dev/null 2>&1; then
            echo "⏭️  Skipping $task_id (already exists)"
            skipped=$((skipped + 1))
            continue
        fi

        if [ "$dry_run" = "--dry-run" ]; then
            echo "Would create: $task_id - $title (priority: $priority_str=$priority)"
            if [ -n "$deps" ]; then
                echo "  Dependencies: $deps"
            fi
        else
            echo "➕ Creating: $task_id - $title"
            cmd_task_add "$task_id" "$title" "$description" "$priority" "task-import" "$deps" >/dev/null 2>&1
            if [ $? -eq 0 ]; then
                created=$((created + 1))
            fi
        fi
    done <<< "$tasks_json"

    echo ""
    if [ "$dry_run" = "--dry-run" ]; then
        echo "DRY RUN COMPLETE"
        echo "  Would create: $total tasks"
    else
        echo "✅ IMPORT COMPLETE"
        echo "  Created: $created tasks"
        echo "  Skipped: $skipped tasks (already existed)"
    fi
}

cmd_task_next() {
    local agent_id="$1"

    [ -z "$agent_id" ] && {
        echo "Usage: $0 task-next <agent_id>" >&2
        echo "Returns the next available task for the agent to claim" >&2
        exit 1
    }

    init_state
    local state=$(atomic_read)

    # Priority order:
    # 1. Prefix priority (if configured) - all m3-* before m4-*, etc.
    # 2. Task dependencies (blocked_by) - don't return tasks that depend on incomplete tasks
    # 3. Previously blocked tasks where the blocking file is now free
    # 4. Unblocked pending tasks with no owner
    # 5. Still-blocked tasks (attempt anyway)
    # Within each level, sort by task priority (1-5)

    # Get prefix priorities (lower number = higher priority)
    local prefix_priorities=$(echo "$state" | jq -r '.prefix_priorities // {}')

    # Get all locks to check which files are free
    local locked_files=$(echo "$state" | jq -r '.locks | keys[]')

    # Helper function to get next task with prefix and dependency awareness
    local next_task=$(echo "$state" | jq -r --argjson locked "$(echo "$state" | jq '.locks | keys')" '
        # Get prefix priorities
        .prefix_priorities as $prefix_prio |

        # Get all completed task IDs for dependency checking
        ([.tasks | to_entries[] | select(.value.status == "completed") | .key]) as $completed |

        # Function to extract prefix from task ID (everything before first number or dash-number)
        def get_prefix:
            . as $id |
            if ($id | test("^[a-z]+-[0-9]")) then
                ($id | split("-")[0])
            else
                ($id | split("-")[0])
            end;

        # Function to check if task dependencies are met
        def deps_met:
            .value.blocked_by as $deps |
            if ($deps == null or $deps == [] or $deps == "") then
                true
            else
                # Check if all blocking tasks are completed
                if ($deps | type == "array") then
                    ($deps | all(. as $dep | $completed | index($dep) != null))
                else
                    ($completed | index($deps) != null)
                end
            end;

        # Get tasks sorted by prefix priority, then task priority
        [.tasks | to_entries[] |
            select(.value.status == "pending" and
                   (.value.blocked == null or .value.blocked == false) and
                   .value.owner == null and
                   deps_met) |
            . + {
                prefix: (.key | get_prefix),
                prefix_prio: ($prefix_prio[.key | get_prefix] // 999),
                task_prio: (.value.priority // 3)
            }
        ] |
        sort_by([.prefix_prio, .task_prio]) |
        .[0].key // empty
    ')

    if [ -n "$next_task" ]; then
        echo "$next_task"
        exit 0
    fi

    # Fallback: try previously blocked tasks where blocking file is now free
    local unblocked_task=$(echo "$state" | jq -r --argjson locked "$(echo "$state" | jq '.locks | keys')" \
        '[.tasks | to_entries[] | select(.value.status == "pending" and .value.blocked == true and (.value.blocked_file as $f | ($locked | index($f)) == null))] | sort_by(.value.priority // 3) | .[0].key // empty')

    if [ -n "$unblocked_task" ]; then
        echo "$unblocked_task"
        exit 0
    fi

    # Last resort: still-blocked tasks
    local blocked_task=$(echo "$state" | jq -r \
        '[.tasks | to_entries[] | select(.value.status == "pending" and .value.blocked == true)] | sort_by(.value.priority // 3) | .[0].key // empty')

    if [ -n "$blocked_task" ]; then
        echo "$blocked_task"
        exit 0
    fi

    echo "(no tasks available)"
    exit 1
}

# ============================================================
# WORKFLOW HELPER COMMANDS
# ============================================================

cmd_task_work() {
    local agent_id="$1"
    local task_id="$2"

    [ -z "$agent_id" ] || [ -z "$task_id" ] && {
        echo "Usage: $0 task-work <agent_id> <task_id>" >&2
        echo "  Atomic operation: claim task + lock files + show spec" >&2
        echo "  Files are auto-locked based on task spec (## Files to Modify section)" >&2
        exit 1
    }

    # Step 1: Claim the task
    echo "→ Claiming task $task_id..."
    if ! "$0" task-claim "$agent_id" "$task_id" 2>&1; then
        echo "ERROR: Failed to claim task $task_id" >&2
        exit 1
    fi
    echo "✓ Task claimed"
    echo ""

    # Step 2: Lock files from task spec (if spec exists)
    local spec_file="$COORD_DIR/task-specs/${task_id}.md"
    if [ -f "$spec_file" ]; then
        echo "→ Locking files from task spec..."

        # Extract files from "## Files to Modify" and "## Files to Create" sections
        local files=$(awk '
            /^## Files to (Modify|Create)/ { in_section=1; next }
            /^## / { in_section=0 }
            in_section && /^- `[^`]+`/ {
                match($0, /`([^`]+)`/, arr);
                print arr[1]
            }
        ' "$spec_file")

        if [ -n "$files" ]; then
            local locked_count=0
            while IFS= read -r file; do
                [ -z "$file" ] && continue
                if "$0" lock "$agent_id" "$file" 2>&1; then
                    echo "  ✓ Locked: $file"
                    locked_count=$((locked_count + 1))
                else
                    echo "  ⚠ Could not lock: $file (already locked or doesn't exist)"
                fi
            done <<< "$files"
            echo "✓ Locked $locked_count file(s)"
        else
            echo "  (No files specified in spec)"
        fi
        echo ""
    else
        echo "→ No detailed spec found"
        echo "  (Lock files manually if needed: $0 lock $agent_id <file>)"
        echo ""
    fi

    # Step 3: Display task information
    echo "=========================================="
    if [ -f "$spec_file" ]; then
        echo "TASK SPECIFICATION: $task_id"
    else
        echo "TASK: $task_id"
    fi
    echo "=========================================="
    echo ""

    if [ -f "$spec_file" ]; then
        # Use task-spec-helpers if available
        if [ -f "$COORD_DIR/task-spec-helpers.sh" ]; then
            "$COORD_DIR/task-spec-helpers.sh" task-spec "$task_id"
        else
            cat "$spec_file"
        fi
    else
        # Fallback to basic task info (JSON)
        echo "Note: No detailed specification found"
        echo "Showing basic task info:"
        echo ""
        "$0" task-get "$task_id"
    fi

    echo ""
    echo "=========================================="
    echo "Ready to work on: $task_id"
    echo "=========================================="
}

cmd_task_done() {
    local agent_id="$1"
    local task_id="$2"

    [ -z "$agent_id" ] || [ -z "$task_id" ] && {
        echo "Usage: $0 task-done <agent_id> <task_id>" >&2
        echo "  Atomic operation: unlock all + complete task + show next" >&2
        exit 1
    }

    # Step 1: Unlock all files
    echo "→ Unlocking all files..."
    "$0" unlock-all "$agent_id"
    echo "✓ All files unlocked"
    echo ""

    # Step 2: Mark task complete
    echo "→ Marking task $task_id complete..."
    if ! "$0" task-complete "$agent_id" "$task_id" 2>&1; then
        echo "ERROR: Failed to complete task $task_id" >&2
        exit 1
    fi
    echo "✓ Task completed"
    echo ""

    # Step 2.5: Log metrics (for historical tracking)
    local metrics_file="$COORD_DIR/metrics.jsonl"
    local completed_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    # Get task details for metrics
    local task_data=$("$0" task-get "$task_id" 2>/dev/null)
    if [ -n "$task_data" ]; then
        local priority=$(echo "$task_data" | jq -r '.priority // 3')
        local started_at=$(echo "$task_data" | jq -r '.started_at // empty')
        local prefix=$(echo "$task_id" | sed 's/-[0-9].*//')

        # Calculate duration if started_at exists
        local duration=0
        if [ -n "$started_at" ] && [ "$started_at" != "null" ]; then
            local started_ts=$(date -d "$started_at" +%s 2>/dev/null || echo 0)
            local completed_ts_epoch=$(date +%s)
            duration=$((completed_ts_epoch - started_ts))
        fi

        # Append metrics (one line per completion)
        echo "{\"timestamp\":\"$completed_ts\",\"task_id\":\"$task_id\",\"prefix\":\"$prefix\",\"priority\":$priority,\"duration_seconds\":$duration,\"agent_id\":\"$agent_id\"}" >> "$metrics_file"
    fi

    # Step 3: Show next available task
    echo "=========================================="
    echo "NEXT AVAILABLE TASK"
    echo "=========================================="
    echo ""

    local next_task=$("$0" task-next "$agent_id" 2>&1)
    if [ "$next_task" = "(no tasks available)" ]; then
        echo "🎉 No more tasks available!"
        echo ""
        echo "Task stats:"
        "$0" task-stats
    else
        echo "Next task: $next_task"
        echo ""
        echo "To start working on it:"
        echo "  $0 task-work $agent_id $next_task"
    fi
}

# ============================================================
# CLEANUP COMMAND
# ============================================================

cmd_cleanup_dead() {
    init_state

    echo "Checking for dead agents..."

    # Atomic cleanup with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        now_ts="'"$(now)"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "No state file found"
            exit 0
        fi

        state=$(cat "$STATE_FILE")
        cleaned=0
        tasks_released=0

        # Get all agent IDs
        agents=$(echo "$state" | jq -r ".agents | keys[]" 2>/dev/null || echo "")

        for agent_id in $agents; do
            pid=$(echo "$state" | jq -r ".agents[\"$agent_id\"].pid")

            # Check if PID is still running
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                echo "  $agent_id (pid=$pid): alive"
            else
                echo "  $agent_id (pid=$pid): DEAD - removing"
                state=$(echo "$state" | jq "del(.agents[\"$agent_id\"])")

                # Remove their locks
                lock_count=$(echo "$state" | jq --arg owner "$agent_id" "[.locks | to_entries[] | select(.value.owner == \$owner)] | length")
                state=$(echo "$state" | jq --arg owner "$agent_id" ".locks = (.locks | to_entries | map(select(.value.owner != \$owner)) | from_entries)")
                echo "    Released $lock_count locks"

                # Release their in_progress tasks back to pending
                task_count=$(echo "$state" | jq --arg owner "$agent_id" "[.tasks | to_entries[] | select(.value.owner == \$owner and .value.status == \"in_progress\")] | length")
                state=$(echo "$state" | jq --arg owner "$agent_id" --arg ts "$now_ts" \
                    ".tasks |= with_entries(if .value.owner == \$owner and .value.status == \"in_progress\" then .value.status = \"pending\" | .value.owner = null | .value.updated_at = \$ts | .value.updated_by = \"cleanup-dead\" else . end)")
                echo "    Released $task_count tasks"
                tasks_released=$((tasks_released + task_count))

                cleaned=$((cleaned + 1))
            fi
        done

        printf "%s\n" "$state" > "$STATE_FILE"
        echo ""
        echo "Cleaned up $cleaned dead agents, released $tasks_released tasks"
    '
}

cmd_task_recover() {
    local dry_run="${1:-}"

    init_state

    echo "Scanning for orphaned tasks (owned by dead/unregistered agents)..."
    echo ""

    # Atomic check/recovery with exclusive lock
    flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        dry_run="'"$dry_run"'"
        now_ts="'"$(now)"'"

        if [ ! -f "$STATE_FILE" ]; then
            echo "No state file found"
            exit 0
        fi

        state=$(cat "$STATE_FILE")
        orphaned_count=0
        recovered_count=0

        # Get all in_progress tasks with owners
        tasks_with_owners=$(echo "$state" | jq -r ".tasks | to_entries[] | select(.value.status == \"in_progress\" and .value.owner != null) | \"\(.key)|\(.value.owner)|\(.value.subject)\"" 2>/dev/null || echo "")

        if [ -z "$tasks_with_owners" ]; then
            echo "No in_progress tasks with owners found."
            exit 0
        fi

        echo "Checking task owners..."
        echo ""

        while IFS="|" read -r task_id owner subject; do
            [ -z "$task_id" ] && continue

            # Check if owner is a registered agent
            agent_exists=$(echo "$state" | jq -r --arg owner "$owner" ".agents[\$owner] // empty")

            if [ -n "$agent_exists" ] && [ "$agent_exists" != "null" ]; then
                # Agent exists, check if PID is alive
                pid=$(echo "$state" | jq -r --arg owner "$owner" ".agents[\$owner].pid")
                if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                    echo "  $task_id: owner $owner is ALIVE"
                else
                    echo "  $task_id: owner $owner has DEAD PID ($pid) - ORPHANED"
                    orphaned_count=$((orphaned_count + 1))

                    if [ "$dry_run" != "--dry-run" ]; then
                        state=$(echo "$state" | jq --arg id "$task_id" --arg ts "$now_ts" \
                            ".tasks[\$id].status = \"pending\" | .tasks[\$id].owner = null | .tasks[\$id].updated_at = \$ts | .tasks[\$id].updated_by = \"task-recover\"")
                        echo "    → Released back to pending"
                        recovered_count=$((recovered_count + 1))
                    fi
                fi
            else
                echo "  $task_id: owner $owner is UNREGISTERED - ORPHANED"
                orphaned_count=$((orphaned_count + 1))

                if [ "$dry_run" != "--dry-run" ]; then
                    state=$(echo "$state" | jq --arg id "$task_id" --arg ts "$now_ts" \
                        ".tasks[\$id].status = \"pending\" | .tasks[\$id].owner = null | .tasks[\$id].updated_at = \$ts | .tasks[\$id].updated_by = \"task-recover\"")
                    echo "    → Released back to pending"
                    recovered_count=$((recovered_count + 1))
                fi
            fi
        done <<< "$tasks_with_owners"

        if [ "$dry_run" = "--dry-run" ]; then
            echo ""
            echo "Found $orphaned_count orphaned tasks (dry-run, no changes made)"
        else
            printf "%s\n" "$state" > "$STATE_FILE"
            echo ""
            echo "Recovered $recovered_count orphaned tasks"
        fi
    '
}

# ============================================================
# STATUS COMMAND
# ============================================================

cmd_status() {
    init_state

    # Atomic cleanup + read with exclusive lock
    local state=$(flock -x "$LOCK_FILE" bash -c '
        STATE_FILE="'"$STATE_FILE"'"
        LOCK_TIMEOUT_SECONDS='"$LOCK_TIMEOUT_SECONDS"'

        if [ ! -f "$STATE_FILE" ]; then
            echo "{\"agents\":{},\"locks\":{},\"tasks\":{}}"
            exit 0
        fi

        state=$(cat "$STATE_FILE")
        now_ts=$(date +%s)
        changed=false

        # Cleanup dead agents inline
        agents=$(echo "$state" | jq -r ".agents | keys[]" 2>/dev/null || echo "")
        for aid in $agents; do
            pid=$(echo "$state" | jq -r ".agents[\"$aid\"].pid")
            heartbeat=$(echo "$state" | jq -r ".agents[\"$aid\"].heartbeat")
            hb_ts=$(date -d "$heartbeat" +%s 2>/dev/null || echo 0)
            age=$((now_ts - hb_ts))

            pid_alive=false
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                pid_alive=true
            fi

            if [ "$pid_alive" = false ] && [ "$age" -gt "$LOCK_TIMEOUT_SECONDS" ]; then
                state=$(echo "$state" | jq "del(.agents[\"$aid\"])")
                state=$(echo "$state" | jq ".locks |= with_entries(select(.value.owner != \"$aid\"))")
                changed=true
                echo "Cleaned up dead agent: $aid" >&2
            fi
        done

        if [ "$changed" = true ]; then
            printf "%s\n" "$state" > "$STATE_FILE"
        fi

        echo "$state"
    ')

    echo "=== AGENTS ==="
    local agents=$(echo "$state" | jq -r '.agents | to_entries[] | "\(.key): pid=\(.value.pid) heartbeat=\(.value.heartbeat)"')
    if [ -z "$agents" ]; then
        echo "(none)"
    else
        echo "$agents"
    fi

    echo ""
    echo "=== LOCKS ==="
    local locks=$(echo "$state" | jq -r '.locks | to_entries[] | "\(.value.owner) -> \(.key)"')
    if [ -z "$locks" ]; then
        echo "(none)"
    else
        echo "$locks"
    fi

    echo ""
    echo "=== TASKS ==="
    local tasks=$(echo "$state" | jq -r '.tasks | to_entries[] | "\(.key) [\(.value.status)] \(.value.owner // "unassigned"): \(.value.subject)"')
    if [ -z "$tasks" ]; then
        echo "(none)"
    else
        echo "$tasks"
    fi
}

# ============================================================
# MY LOCKS COMMAND (for current agent)
# ============================================================

cmd_my_locks() {
    local agent_id="$1"

    [ -z "$agent_id" ] && { echo "Usage: $0 my-locks <agent_id>" >&2; exit 1; }

    local state=$(atomic_read)
    local locks=$(echo "$state" | jq -r --arg owner "$agent_id" '.locks | to_entries[] | select(.value.owner == $owner) | .key')

    if [ -z "$locks" ]; then
        echo "(no locks held)"
    else
        echo "$locks"
    fi
}

# ============================================================
# MAIN
# ============================================================

case "${1:-}" in
    register)    cmd_register "$2" "$3" ;;
    unregister)  cmd_unregister "$2" "$3" ;;
    heartbeat)   cmd_heartbeat "$2" ;;
    lock)        cmd_lock "$2" "$3" ;;
    lock-all)    shift; cmd_lock_all "$@" ;;
    unlock)      cmd_unlock "$2" "$3" ;;
    unlock-all)  cmd_unlock_all "$2" ;;
    check)       cmd_check "$2" "$3" ;;
    my-locks)    cmd_my_locks "$2" ;;
    status)      cmd_status ;;
    cleanup-dead) cmd_cleanup_dead ;;
    task-add)    cmd_task_add "$2" "$3" "$4" "$5" "$6" "$7" ;;
    task-get)    cmd_task_get "$2" ;;
    task-claim)  cmd_task_claim "$2" "$3" ;;
    task-complete) cmd_task_complete "$2" "$3" ;;
    task-release) cmd_task_release "$2" "$3" ;;
    task-block)  cmd_task_block "$2" "$3" "$4" ;;
    task-unblock) cmd_task_unblock "$2" "$3" ;;
    task-priority) cmd_task_priority "$2" "$3" "$4" ;;
    task-next)   cmd_task_next "$2" ;;
    task-work)   cmd_task_work "$2" "$3" ;;
    task-done)   cmd_task_done "$2" "$3" ;;
    task-list)   cmd_task_list "$2" ;;
    task-search) cmd_task_search "$2" "$3" ;;
    task-stats)  cmd_task_stats ;;
    task-metrics) cmd_task_metrics "$2" ;;
    task-insights) cmd_task_insights ;;
    task-cleanup) cmd_task_cleanup "$2" "$3" ;;
    task-archive) cmd_task_archive "$2" ;;
    task-recover) cmd_task_recover "$2" ;;
    task-prefix-set) cmd_task_prefix_set "$2" "$3" ;;
    task-prefix-list) cmd_task_prefix_list ;;
    task-prefix-clear) cmd_task_prefix_clear "$2" ;;
    task-depends) shift; cmd_task_depends "$@" ;;
    task-depends-clear) cmd_task_depends_clear "$2" ;;
    task-import) cmd_task_import "$2" "$3" ;;
    *)
        echo "Claude Multi-Agent Coordination"
        echo ""
        echo "Usage: $0 <command> [args]"
        echo ""
        echo "Agent commands:"
        echo "  register <agent_id> [pid]   Register an agent"
        echo "  unregister <agent_id>       Unregister and release locks"
        echo "  heartbeat <agent_id>        Update heartbeat"
        echo ""
        echo "Lock commands:"
        echo "  lock <agent_id> <path>      Acquire lock on file"
        echo "  lock-all <agent_id> <paths...>  Acquire multiple locks (all or nothing)"
        echo "  unlock <agent_id> <path>    Release lock"
        echo "  unlock-all <agent_id>       Release all locks"
        echo "  check [agent_id] <path>     Check if file is locked"
        echo "  my-locks <agent_id>         List locks held by agent"
        echo ""
        echo "Task commands:"
        echo "  task-add <id> <subj> [desc] [pri] [by] [deps]  Add task (deps: comma-separated IDs)"
        echo "  task-get <id>                      Get full task details (JSON)"
        echo "  task-claim <agent> <id>            Claim a task (one per agent limit)"
        echo "  task-complete <agent> <id>         Mark task complete"
        echo "  task-release <agent> <id>          Release task back to queue"
        echo "  task-block <id> <agent> [file]     Mark task as blocked"
        echo "  task-unblock <id> [agent]          Clear blocked status"
        echo "  task-priority <id> <1-5> [agent]   Set task priority"
        echo "  task-next <agent>                  Get next (prefix+dependency+priority aware)"
        echo "  task-list [filter]                 List tasks (all|pending|available|blocked)"
        echo "  task-search <keyword> [status]     Search tasks (check for duplicates)"
        echo "  task-stats                         Show task counts by status"
        echo "  task-metrics [prefix]              Show progress metrics & velocity (from metrics.jsonl)"
        echo ""
        echo "Workflow helpers (shortcuts):"
        echo "  task-work <agent> <id>             Claim + lock files + show spec"
        echo "  task-done <agent> <id>             Unlock all + complete + show next"
        echo "  task-cleanup [days] [--dry-run]    Remove completed tasks older than N days"
        echo "  task-archive [file]                Export completed tasks to JSON file"
        echo "  task-recover [--dry-run]           Release orphaned tasks (dead/unregistered owners)"
        echo ""
        echo "Prefix priority (for ordering task groups like m3 before m4):"
        echo "  task-prefix-set <prefix> <pri>     Set prefix priority (lower=first)"
        echo "  task-prefix-list                   List all prefix priorities"
        echo "  task-prefix-clear <prefix>         Remove prefix priority"
        echo ""
        echo "Task dependencies:"
        echo "  task-depends <id> <blocking...>    Set dependencies (id waits for blocking)"
        echo "  task-depends-clear <id>            Remove all dependencies"
        echo ""
        echo "Batch operations:"
        echo "  task-import <json> [--dry-run]     Import tasks from JSON file"
        echo ""
        echo "Priority levels: 1=critical, 2=high, 3=normal, 4=low, 5=backlog"
        echo ""
        echo "Status & Maintenance:"
        echo "  status                      Show all agents, locks, tasks"
        echo "  cleanup-dead                Remove dead agents, release their locks and tasks"
        echo "  task-cleanup [days] [dry]   Remove completed tasks older than N days (default: 7)"
        echo "  task-archive [file]         Archive completed tasks to file and remove from state"
        exit 1
        ;;
esac

cmd_task_cleanup() {
    local retention_days="${1:-7}"  # Default: 7 days
    local dry_run="${2:-false}"     # Set to "true" for preview

    echo "Cleaning up completed tasks older than $retention_days days..."
    echo ""

    local now_ts=$(date +%s)
    local cutoff_ts=$((now_ts - retention_days * 86400))

    # Read current state
    local state=$(atomic_read)
    local tasks=$(echo "$state" | jq -r '.tasks | keys[]')

    local removed_count=0
    local kept_count=0
    local removed_ids=()

    for task_id in $tasks; do
        local status=$(echo "$state" | jq -r ".tasks[\"$task_id\"].status")
        local completed_at=$(echo "$state" | jq -r ".tasks[\"$task_id\"].completed_at // empty")

        if [ "$status" = "completed" ] && [ -n "$completed_at" ]; then
            local completed_ts=$(date -d "$completed_at" +%s 2>/dev/null || echo 0)

            if [ "$completed_ts" -lt "$cutoff_ts" ] || [ "$completed_ts" -eq 0 ]; then
                local subject=$(echo "$state" | jq -r ".tasks[\"$task_id\"].subject")
                echo "  [REMOVE] $task_id: $subject (completed: $completed_at)"
                removed_ids+=("$task_id")
                ((removed_count++))
            else
                ((kept_count++))
            fi
        else
            ((kept_count++))
        fi
    done

    echo ""
    echo "Summary: $removed_count to remove, $kept_count to keep"

    if [ "$dry_run" = "true" ]; then
        echo ""
        echo "DRY RUN - No changes made"
        echo "Run without 'true' flag to actually remove tasks"
        return 0
    fi

    if [ "$removed_count" -eq 0 ]; then
        echo "No tasks to clean up"
        return 0
    fi

    # Remove tasks
    echo ""
    echo "Removing tasks..."

    for task_id in "${removed_ids[@]}"; do
        state=$(echo "$state" | jq "del(.tasks[\"$task_id\"])")
    done

    atomic_write "$state"

    echo "✓ Cleaned up $removed_count completed tasks"
}

cmd_task_archive() {
    local archive_file="${1:-.claude-coord/archive/$(date +%Y-%m).json}"

    mkdir -p "$(dirname "$archive_file")"

    echo "Archiving all completed tasks to: $archive_file"

    local state=$(atomic_read)
    local completed_tasks=$(echo "$state" | jq '{tasks: (.tasks | with_entries(select(.value.status == "completed")))}')

    # Save to archive
    echo "$completed_tasks" > "$archive_file"

    local count=$(echo "$completed_tasks" | jq '.tasks | length')
    echo "✓ Archived $count completed tasks"

    # Now remove them from state
    state=$(echo "$state" | jq '.tasks |= with_entries(select(.value.status != "completed"))')
    atomic_write "$state"

    echo "✓ Removed archived tasks from active state"
    echo ""
    echo "Archive location: $archive_file"
}

