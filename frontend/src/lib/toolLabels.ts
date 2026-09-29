/**
 * What a tool step is called in the story: plain words built from the
 * tool's name and what it was given — "Read src/app.ts", "Run npm test",
 * "Search for TODO". No model, no cost, no ids.
 *
 * A tool the page does not know still gets a readable line: "Using <tool>".
 */

/** Longest a value is shown before it is cut short. */
const MAX = 56;

function shorten(value: unknown, max = MAX): string {
  const text = typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value);
  const oneLine = text.replace(/\s+/g, ' ').trim();
  if (oneLine.length <= max) return oneLine;
  return `${oneLine.slice(0, max - 1)}…`;
}

/** A path as a person reads it: the tail, not the whole machine path. */
function shortPath(value: unknown): string {
  const text = typeof value === 'string' ? value : '';
  if (!text) return '';
  const parts = text.split('/').filter(Boolean);
  const tail = parts.length > 3 ? `…/${parts.slice(-3).join('/')}` : text;
  return shorten(tail, 48);
}

function host(value: unknown): string {
  const text = typeof value === 'string' ? value : '';
  try {
    return new URL(text).host || shorten(text);
  } catch {
    return shorten(text);
  }
}

type Args = Record<string, unknown> | undefined;

function pick(args: Args, ...keys: string[]): unknown {
  if (!args) return undefined;
  for (const key of keys) {
    const value = args[key];
    if (value !== undefined && value !== null && value !== '') return value;
  }
  return undefined;
}

/** Tool name without the wrapping an MCP server adds (mcp__github__…). */
export function bareToolName(toolName: string): string {
  const parts = toolName.split('__').filter(Boolean);
  return (parts[parts.length - 1] ?? toolName).trim();
}

/** A tool's name in plain words, for when nothing better is known. */
function spelled(toolName: string): string {
  const bare = bareToolName(toolName).replace(/[_-]+/g, ' ').trim();
  return bare || toolName;
}

type Labeller = (args: Args, toolName: string) => string;

const LABELS: Record<string, Labeller> = {
  read: (a) => withTarget('Read', shortPath(pick(a, 'file_path', 'path', 'notebook_path'))),
  notebookread: (a) => withTarget('Read', shortPath(pick(a, 'notebook_path', 'file_path'))),
  write: (a) => withTarget('Write', shortPath(pick(a, 'file_path', 'path'))),
  edit: (a) => withTarget('Edit', shortPath(pick(a, 'file_path', 'path'))),
  multiedit: (a) => withTarget('Edit', shortPath(pick(a, 'file_path', 'path'))),
  notebookedit: (a) => withTarget('Edit', shortPath(pick(a, 'notebook_path', 'file_path'))),
  patch: (a) => withTarget('Patch', shortPath(pick(a, 'file_path', 'path'))),
  bash: (a) => withTarget('Run', shorten(pick(a, 'command', 'cmd', 'script'))),
  shell: (a) => withTarget('Run', shorten(pick(a, 'command', 'cmd'))),
  run_command: (a) => withTarget('Run', shorten(pick(a, 'command', 'cmd'))),
  bashoutput: () => 'Check a running command',
  killshell: () => 'Stop a running command',
  grep: (a) => withTarget('Search for', shorten(pick(a, 'pattern', 'query', 'regex'))),
  glob: (a) => withTarget('Find files', shorten(pick(a, 'pattern', 'glob'))),
  find: (a) => withTarget('Find files', shorten(pick(a, 'pattern', 'glob', 'query'))),
  ls: (a) => withTarget('List', shortPath(pick(a, 'path', 'dir_path')) || 'the folder'),
  webfetch: (a) => withTarget('Fetch', host(pick(a, 'url'))),
  fetch: (a) => withTarget('Fetch', host(pick(a, 'url'))),
  fetch_content: (a) => withTarget('Fetch', host(pick(a, 'url', 'urls'))),
  websearch: (a) => withTarget('Search the web for', shorten(pick(a, 'query', 'q'))),
  web_search: (a) => withTarget('Search the web for', shorten(pick(a, 'query', 'q'))),
  search: (a) => withTarget('Search for', shorten(pick(a, 'query', 'pattern', 'q'))),
  task: (a) => withTarget('Start a helper for', shorten(pick(a, 'description', 'task'))),
  todowrite: () => 'Update the task list',
  ask: (a) => withTarget('Ask you', shorten(pick(a, 'question', 'prompt'))),
  ask_user: (a) => withTarget('Ask you', shorten(pick(a, 'question', 'prompt'))),
  ask_user_question: (a) => withTarget('Ask you', shorten(pick(a, 'question', 'prompt'))),
  notify: (a) => withTarget('Send a notice', shorten(pick(a, 'message', 'text'))),
  send_notification: (a) => withTarget('Send a notice', shorten(pick(a, 'message', 'text'))),
  create_pull_request: (a) => withTarget('Open a pull request', shorten(pick(a, 'title'))),
  merge_pull_request: (a) => withTarget('Merge pull request', prNumber(a)),
  update_pull_request: (a) => withTarget('Update pull request', prNumber(a)),
  get_pull_request: (a) => withTarget('Read pull request', prNumber(a)),
  pull_request_read: (a) => withTarget('Read pull request', prNumber(a)),
  list_pull_requests: () => 'List pull requests',
  add_issue_comment: (a) => withTarget('Comment on', prNumber(a)),
  create_issue: (a) => withTarget('Open an issue', shorten(pick(a, 'title'))),
  issue_write: (a) => withTarget('Write an issue', shorten(pick(a, 'title'))),
  get_file_contents: (a) => withTarget('Read on GitHub', shortPath(pick(a, 'path'))),
};

/** Browser steps: what they do on the page. */
const BROWSER: Record<string, Labeller> = {
  navigate: (a) => withTarget('Open', host(pick(a, 'url'))),
  goto: (a) => withTarget('Open', host(pick(a, 'url'))),
  open: (a) => withTarget('Open', host(pick(a, 'url'))),
  click: (a) => withTarget('Click', shorten(pick(a, 'text', 'selector', 'ref', 'element'))),
  type: (a) => withTarget('Type into', shorten(pick(a, 'selector', 'ref', 'element'))),
  fill: (a) => withTarget('Fill in', shorten(pick(a, 'selector', 'ref', 'element'))),
  press: (a) => withTarget('Press', shorten(pick(a, 'key'))),
  scroll: () => 'Scroll the page',
  snapshot: () => 'Look at the page',
  screenshot: () => 'Take a screenshot',
  shot: () => 'Take a screenshot',
  read: (a) => withTarget('Read the page', shorten(pick(a, 'selector'))),
  wait: (a) => withTarget('Wait for', shorten(pick(a, 'text', 'selector'))),
  close: () => 'Close the tab',
  tabs: () => 'List the tabs',
  pages: () => 'List the pages',
};

function withTarget(verb: string, target: string): string {
  return target ? `${verb} ${target}` : verb;
}

function prNumber(args: Args): string {
  const n = pick(args, 'pullNumber', 'pull_number', 'issue_number', 'number');
  return n == null ? '' : `#${shorten(n, 12)}`;
}

/**
 * The line shown for one tool step.
 *
 * @param toolName the tool as the run recorded it (MCP wrapping and all)
 * @param args what it was given, when the page has it
 */
export function toolStepLabel(toolName: string, args?: Record<string, unknown>): string {
  const bare = bareToolName(toolName || '').toLowerCase();

  const browser = bare.startsWith('browser_') || bare.startsWith('browser-');
  if (browser) {
    const action = bare.replace(/^browser[_-]/, '');
    const label = BROWSER[action];
    if (label) return label(args, toolName);
    return withTarget('Browser:', spelled(action));
  }

  const label = LABELS[bare] ?? LABELS[bare.replace(/[_-]/g, '')];
  if (label) return label(args, toolName);

  // A tool nobody taught us: still readable, never an id.
  return `Using ${spelled(toolName)}`;
}
