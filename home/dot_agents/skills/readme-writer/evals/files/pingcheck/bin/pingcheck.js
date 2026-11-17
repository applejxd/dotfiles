#!/usr/bin/env node
import { check } from '../src/check.js';

const args = process.argv.slice(2);
if (args.length === 0 || args.includes('--help') || args.includes('-h')) {
  console.log('usage: pingcheck <url>... [--timeout MS] [--json]');
  console.log('env: PINGCHECK_TIMEOUT_MS (既定 5000)');
  process.exit(args.length === 0 ? 2 : 0);
}
const json = args.includes('--json');
const timeoutIndex = args.indexOf('--timeout');
const timeoutMs = timeoutIndex >= 0 ? Number(args[timeoutIndex + 1]) : Number(process.env.PINGCHECK_TIMEOUT_MS || 5000);
const urls = args.filter((a, i) => !a.startsWith('--') && i !== timeoutIndex + 1);
const results = await Promise.all(urls.map((u) => check(u, { timeoutMs })));
if (json) {
  console.log(JSON.stringify(results));
} else {
  for (const r of results) console.log(`${r.ok ? 'OK ' : 'NG '} ${r.url} ${r.status ?? r.error} ${r.ms}ms`);
}
process.exit(results.every((r) => r.ok) ? 0 : 1);
