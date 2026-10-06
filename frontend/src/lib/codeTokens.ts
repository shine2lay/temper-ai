/**
 * A light code colouring, as data: one line in, coloured pieces out.
 *
 * SmartContent shows each piece as React text inside a span, so code from
 * content is never read as HTML. Three colours, as before: keywords, strings
 * and comments. At each position, in this order:
 *
 * - a string: a quote whose next quote character (any of " ' `) is the same
 *   quote, up to and including it;
 * - a comment: `//` or `#` outside a string, to the end of the line;
 * - a keyword at a word boundary;
 * - otherwise plain text.
 */

export type CodeTokenKind = 'plain' | 'keyword' | 'string' | 'comment';

export interface CodeToken {
  kind: CodeTokenKind;
  text: string;
}

/** The classes each colour has always used. */
export const CODE_TOKEN_CLASS: Record<Exclude<CodeTokenKind, 'plain'>, string> = {
  keyword: 'text-violet-400 font-medium',
  string: 'text-emerald-400',
  comment: 'text-temper-text-dim italic',
};

const KEYWORD =
  /(?:import|from|export|default|const|let|var|function|return|class|if|else|for|while|async|await|try|catch|def|self|None|True|False)\b/y;
const QUOTES = `"'\``;
const WORD = /\w/;

export function tokenizeCodeLine(line: string): CodeToken[] {
  const tokens: CodeToken[] = [];
  const push = (kind: CodeTokenKind, text: string) => {
    const last = tokens[tokens.length - 1];
    if (kind === 'plain' && last?.kind === 'plain') last.text += text;
    else tokens.push({ kind, text });
  };

  let i = 0;
  while (i < line.length) {
    const ch = line[i];

    if (QUOTES.includes(ch)) {
      let j = i + 1;
      while (j < line.length && !QUOTES.includes(line[j])) j++;
      if (j < line.length && line[j] === ch) {
        push('string', line.slice(i, j + 1));
        i = j + 1;
      } else {
        push('plain', ch);
        i++;
      }
      continue;
    }

    if (ch === '#' || (ch === '/' && line[i + 1] === '/')) {
      push('comment', line.slice(i));
      break;
    }

    if (i === 0 || !WORD.test(line[i - 1])) {
      KEYWORD.lastIndex = i;
      const match = KEYWORD.exec(line);
      if (match) {
        push('keyword', match[0]);
        i += match[0].length;
        continue;
      }
    }

    push('plain', ch);
    i++;
  }
  return tokens;
}
