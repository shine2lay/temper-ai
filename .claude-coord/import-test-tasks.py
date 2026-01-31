#!/usr/bin/env python3
"""Import test tasks from task-specs into coordination system."""

import json
import re
from pathlib import Path

def parse_task_spec(spec_file):
    """Parse a task spec markdown file and extract task info."""
    content = spec_file.read_text()

    # Extract task ID from filename
    task_id = spec_file.stem  # e.g., "test-agent-01"

    # Extract title (first line after #)
    title_match = re.search(r'^#\s+Task:\s+(\S+)\s+-\s+(.+)$', content, re.MULTILINE)
    if title_match:
        subject = title_match.group(2).strip()
    else:
        # Fallback to filename
        subject = task_id

    # Extract priority
    priority_match = re.search(r'^\*\*Priority:\*\*\s+(\w+)', content, re.MULTILINE | re.IGNORECASE)
    priority_map = {
        'CRITICAL': 1,
        'HIGH': 2,
        'NORMAL': 3,
        'MEDIUM': 3,
        'LOW': 4,
        'BACKLOG': 5
    }
    priority = 3  # default
    if priority_match:
        priority_str = priority_match.group(1).upper()
        priority = priority_map.get(priority_str, 3)

    # Extract summary
    summary_match = re.search(r'##\s+Summary\s*\n\s*(.+?)(?:\n##|\n---|\Z)', content, re.MULTILINE | re.DOTALL)
    description = summary_match.group(1).strip() if summary_match else subject

    # Extract dependencies (blocked by)
    deps = []
    deps_match = re.search(r'^\*\*Blocked by:\*\*\s+(.+)$', content, re.MULTILINE)
    if deps_match:
        deps_str = deps_match.group(1)
        if 'None' not in deps_str:
            # Extract task IDs from the dependencies string
            dep_ids = re.findall(r'(test-[\w-]+|m\d+[\w-]*|doc-[\w-]+|code-[\w-]+)', deps_str)
            deps = dep_ids

    # Map priority number back to string for import
    priority_map = {1: 'CRITICAL', 2: 'HIGH', 3: 'NORMAL', 4: 'LOW', 5: 'BACKLOG'}
    priority_str = priority_map.get(priority, 'NORMAL')

    task_data = {
        'id': task_id,
        'enabled': True,
        'title': subject,
        'priority': priority_str,
        'description': description
    }

    if deps:
        task_data['dependencies'] = {'blocked_by': deps}

    return task_data

def main():
    """Parse all test specs and generate import JSON."""
    spec_dir = Path('.claude-coord/task-specs')
    test_specs = sorted(spec_dir.glob('test-*.md'))

    tasks = []
    for spec_file in test_specs:
        try:
            task = parse_task_spec(spec_file)
            tasks.append(task)
            print(f"Parsed: {task['id']} - {task['title'][:50]}...")
        except Exception as e:
            print(f"Error parsing {spec_file}: {e}")

    # Write to JSON file with correct format
    output_file = Path('.claude-coord/test-tasks-import.json')
    with output_file.open('w') as f:
        json.dump({'tasks': tasks}, f, indent=2)

    print(f"\nGenerated {len(tasks)} tasks")
    print(f"Output: {output_file}")
    print(f"\nTo import, run:")
    print(f"  .claude-coord/claude-coord.sh task-import {output_file}")

if __name__ == '__main__':
    main()
