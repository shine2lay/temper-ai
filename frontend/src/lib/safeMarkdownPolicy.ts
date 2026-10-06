/**
 * What markdown from content may become, for SafeMarkdown.
 *
 * Kept apart from the component so tests can read the lists and so the
 * component file exports components only.
 *
 * - ALLOWED_ELEMENTS: text structure only. Nothing on it loads anything:
 *   no img, picture, media, frame, object, embed, link, style or script.
 * - remarkInertImages: every markdown image becomes words before any HTML
 *   element exists: "Image: <alt> (<host>)", a deliberate link when its
 *   address passes the navigation policy, plain text otherwise.
 * - remarkSoftBreaks: single newlines become line breaks (SmartContent's
 *   markdown always showed them that way).
 */
import type { Root, Nodes, Parent, PhrasingContent, Definition } from 'mdast';
import { addressHost, safeUrl } from '@/lib/safeUrl';

export const ALLOWED_ELEMENTS = [
  'a',
  'blockquote',
  'br',
  'code',
  'del',
  'em',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'hr',
  'input',
  'li',
  'ol',
  'p',
  'pre',
  'section',
  'strong',
  'sup',
  'table',
  'tbody',
  'td',
  'th',
  'thead',
  'tr',
  'ul',
] as const;

/** Elements that fetch something, or can: none may ever come from content. */
export const LOADING_ELEMENTS = [
  'img',
  'picture',
  'source',
  'video',
  'audio',
  'track',
  'iframe',
  'frame',
  'frameset',
  'object',
  'embed',
  'link',
  'style',
  'script',
  'svg',
  'image',
  'use',
  'math',
  'form',
  'meta',
  'base',
] as const;

/** The hast property that marks a link we made for an image (content can't set it: raw HTML stays text). */
export const IMAGE_PLACEHOLDER_PROP = 'dataImagePlaceholder';

/** The words an image shows instead of itself. */
export function imagePlaceholderText(alt: string | null | undefined, url: string): string {
  const name = alt && alt.trim() !== '' ? alt : 'untitled';
  return `Image: ${name} (${addressHost(url)})`;
}

function isParent(node: Nodes): node is Nodes & Parent {
  return Array.isArray((node as Parent).children);
}

function collectDefinitions(node: Nodes, found: Map<string, Definition>) {
  if (node.type === 'definition') {
    const id = String(node.identifier).toUpperCase();
    if (!found.has(id)) found.set(id, node);
    return;
  }
  if (isParent(node)) for (const child of node.children) collectDefinitions(child as Nodes, found);
}

function placeholder(alt: string | null | undefined, url: string, insideLink: boolean): PhrasingContent {
  const text = { type: 'text', value: imagePlaceholderText(alt, url) } as const;
  const target = safeUrl(url);
  if (insideLink || !target || target.kind === 'fragment') return text;
  return {
    type: 'link',
    url,
    children: [text],
    data: { hProperties: { [IMAGE_PLACEHOLDER_PROP]: 'true' } },
  };
}

function replaceImages(node: Nodes, definitions: Map<string, Definition>, insideLink: boolean) {
  if (!isParent(node)) return;
  const inLink = insideLink || node.type === 'link' || node.type === 'linkReference';
  const children = node.children as Nodes[];
  for (let i = 0; i < children.length; i++) {
    const child = children[i];
    if (child.type === 'image') {
      children[i] = placeholder(child.alt, child.url, inLink);
    } else if (child.type === 'imageReference') {
      const definition = definitions.get(String(child.identifier).toUpperCase());
      // No definition: mdast-util-to-hast shows the reference as its own text.
      if (definition) children[i] = placeholder(child.alt, definition.url, inLink);
    } else {
      replaceImages(child, definitions, inLink);
    }
  }
}

/** Remark step: markdown images become inert placeholder words (a deliberate link at most). */
export function remarkInertImages() {
  return (tree: Root) => {
    const definitions = new Map<string, Definition>();
    collectDefinitions(tree, definitions);
    replaceImages(tree, definitions, false);
  };
}

function splitSoftBreaks(node: Nodes) {
  if (!isParent(node)) return;
  const out: Nodes[] = [];
  for (const child of node.children as Nodes[]) {
    if (child.type === 'text' && child.value.includes('\n')) {
      child.value.split(/\r?\n/).forEach((part, i) => {
        if (i > 0) out.push({ type: 'break' });
        if (part !== '') out.push({ type: 'text', value: part });
      });
    } else {
      splitSoftBreaks(child);
      out.push(child);
    }
  }
  (node as Parent).children = out as Parent['children'];
}

/** Remark step: a single newline inside a paragraph is a line break. */
export function remarkSoftBreaks() {
  return (tree: Root) => {
    splitSoftBreaks(tree);
  };
}
