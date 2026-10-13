#!/usr/bin/env node
/**
 * Checks the built dashboard's fonts against their licence manifests, and
 * that the licence texts ship with them. The fonts are under the SIL Open
 * Font License 1.1, which asks that the licence travel with the fonts, so
 * the build copies each licence text kept next to them (src/assets/fonts/*.txt)
 * unchanged to dist/licenses/<same name> (vite.config.ts), which the server
 * hands out at /app/licenses/<name>.
 *
 * It fails when:
 *  - a font file in dist/assets (Vite's -<hash> suffix stripped) is not listed
 *    in src/assets/fonts/licenses.json or symbols-licenses.json, or its sha256
 *    is not the listed one;
 *  - a listed font is not in dist/assets as a file (the build dropped it, or
 *    inlined it into the CSS, where nothing checks its bytes);
 *  - a licence text is missing from dist/licenses or differs from its source
 *    by a byte, or dist/licenses holds a file that has no source;
 *  - a licence file a manifest names is not in src/assets/fonts and
 *    dist/licenses, or its bytes are not the sha256 the manifest gives.
 *
 *   npm run build && node scripts/check-font-licenses.mjs [--dist DIR] [--json out.json]
 *
 * --dist checks another built dist instead of ./dist (a copy, for example).
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const fontsDir = path.join(root, 'src', 'assets', 'fonts');
const MANIFESTS = ['licenses.json', 'symbols-licenses.json'];
const FONT_FILE = /\.(woff2?|ttf|otf|eot)$/i;
// Vite names an emitted asset <name>-<8-character hash><extension>.
const HASHED = /^(.+)-[A-Za-z0-9_-]{8}(\.[A-Za-z0-9]+)$/;
const LICENCE_NAME = /[\w.-]+\.txt\b/g;

function option(flag) {
  const at = process.argv.indexOf(flag);
  return at > 0 ? process.argv[at + 1] : undefined;
}

const dist = path.resolve(option('--dist') ?? path.join(root, 'dist'));
const assets = path.join(dist, 'assets');
const licences = path.join(dist, 'licenses');
if (!fs.existsSync(assets)) {
  console.error(`No ${assets}: run the build first.`);
  process.exit(2);
}

const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
const results = [];
const record = (pass, kind, name, detail) => results.push({ pass, kind, name, detail });

// ---- what the manifests list ---------------------------------------------------

const listedFonts = new Map(); // font file -> { sha256, manifest }
const namedLicences = new Map(); // licence file -> { sha256 or null, manifest }
for (const manifest of MANIFESTS) {
  const data = JSON.parse(fs.readFileSync(path.join(fontsDir, manifest), 'utf8'));
  for (const font of data.installed_fonts ?? []) {
    listedFonts.set(font.file, { sha256: font.sha256, manifest });
    // "SIL Open Font License 1.1, Noto-OFL.txt; no Reserved Font Name, ..."
    for (const name of String(font.license ?? '').match(LICENCE_NAME) ?? []) {
      if (!namedLicences.has(name)) namedLicences.set(name, { sha256: null, manifest });
    }
  }
  for (const doc of data.license_documents ?? []) {
    namedLicences.set(doc.file, { sha256: doc.sha256 ?? null, manifest });
  }
}

// ---- fonts: every served font is a listed one, byte for byte ----------------------

const served = new Set();
for (const file of fs.readdirSync(assets).filter((f) => FONT_FILE.test(f)).sort()) {
  const hashed = HASHED.exec(file);
  const name = hashed ? hashed[1] + hashed[2] : file;
  const got = sha256(fs.readFileSync(path.join(assets, file)));
  const listed = listedFonts.get(name);
  served.add(name);
  if (!listed) {
    record(false, 'font', name, `dist/assets/${file} is not listed in ${MANIFESTS.join(' or ')}`);
  } else if (got !== listed.sha256) {
    record(false, 'font', name, `dist/assets/${file} sha256 ${got} is not ${listed.sha256} (${listed.manifest})`);
  } else {
    record(true, 'font', name, `dist/assets/${file} sha256 ${got} MATCH (${listed.manifest})`);
  }
}
for (const [name, listed] of listedFonts) {
  if (!served.has(name)) {
    record(false, 'font', name, `listed in ${listed.manifest}, but not in dist/assets as a file (dropped, or inlined into the CSS)`);
  }
}

// ---- licence texts: each source text ships unchanged, and nothing else ----------------

const texts = fs.readdirSync(fontsDir).filter((f) => f.endsWith('.txt')).sort();
if (texts.length === 0) record(false, 'text', '(none)', 'no licence text (*.txt) in src/assets/fonts');
for (const name of texts) {
  const source = fs.readFileSync(path.join(fontsDir, name));
  const copy = path.join(licences, name);
  if (!fs.existsSync(copy)) {
    record(false, 'text', name, `dist/licenses/${name} is missing`);
    continue;
  }
  const built = fs.readFileSync(copy);
  if (built.equals(source)) {
    record(true, 'text', name, `dist/licenses/${name} byte-equal to src/assets/fonts/${name} (${source.length} bytes, sha256 ${sha256(source)})`);
  } else {
    record(false, 'text', name, `dist/licenses/${name} differs from src/assets/fonts/${name} (sha256 ${sha256(built)}, source ${sha256(source)})`);
  }
}
const shipped = fs.existsSync(licences) ? fs.readdirSync(licences).sort() : [];
for (const name of shipped) {
  if (!texts.includes(name)) record(false, 'text', name, `dist/licenses/${name} has no source in src/assets/fonts`);
}

// ---- licence files the manifests name: present, shipped and the bytes they give -------

for (const [name, named] of [...namedLicences].sort(([a], [b]) => a.localeCompare(b))) {
  const source = path.join(fontsDir, name);
  const copy = path.join(licences, name);
  const where = [fs.existsSync(source) ? null : 'src/assets/fonts', fs.existsSync(copy) ? null : 'dist/licenses'].filter(Boolean);
  if (where.length) {
    record(false, 'named', name, `${named.manifest} names ${name}, which is not in ${where.join(' or ')}`);
    continue;
  }
  const got = sha256(fs.readFileSync(copy));
  if (named.sha256 && got !== named.sha256) {
    record(false, 'named', name, `dist/licenses/${name} sha256 ${got} is not ${named.sha256} (${named.manifest})`);
  } else {
    record(true, 'named', name, `${named.manifest} names ${name}: in src/assets/fonts and dist/licenses${named.sha256 ? `, sha256 MATCH` : ''}`);
  }
}

// ---- report ---------------------------------------------------------------------

const failed = results.filter((r) => !r.pass);
const count = (kind, pass) => results.filter((r) => r.kind === kind && (pass === undefined || r.pass === pass)).length;
console.log(`dist: ${dist}`);
for (const r of results) console.log(`${r.pass ? 'ok  ' : 'FAIL'} ${r.kind.padEnd(5)} ${r.name.padEnd(40)} ${r.detail}`);
console.log('');
console.log(`fonts: ${listedFonts.size} listed, ${served.size} served, ${count('font', true)} MATCH`);
console.log(`licence texts: ${texts.length} in src/assets/fonts, ${count('text', true)} byte-equal in dist/licenses`);
console.log(`licence files the manifests name: ${namedLicences.size}, ${count('named', true)} present and shipped`);
console.log(failed.length ? `check:fonts FAIL (${failed.length} problem${failed.length === 1 ? '' : 's'})` : 'check:fonts PASS');

const jsonOut = option('--json');
if (jsonOut) {
  fs.writeFileSync(
    jsonOut,
    JSON.stringify({ dist, listedFonts: listedFonts.size, servedFonts: served.size, texts, results, pass: failed.length === 0 }, null, 2) + '\n',
  );
}

process.exit(failed.length ? 1 : 0);
