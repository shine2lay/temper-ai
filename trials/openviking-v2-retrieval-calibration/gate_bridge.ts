// External calibration harness: reuse the canonical gate, no Python reimplementation.
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
const modulePath = process.argv[2] ?? `${import.meta.dirname}/sources/candidate-gate.ts`;
const { candidateGate } = await import(pathToFileURL(modulePath).href);
const pairs = JSON.parse(fs.readFileSync(0, 'utf8'));
console.log(JSON.stringify(pairs.map((p: {a: string, b: string}) => candidateGate({headline: '', body: p.a}, {headline: '', body: p.b}))));
