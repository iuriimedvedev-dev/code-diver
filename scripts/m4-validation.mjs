import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import assert from 'node:assert/strict';

const out = '.tmp/m4-qa';
mkdirSync(out, { recursive: true });
writeFileSync(`${out}/empty-graph.jsonl`, '');
const pier = '/Users/iurii.medvedev/Work/sre-support-pier/tmp/rust-pier';
const binary = 'native/code_diver_search_bin/target/release/code-diver';
async function run(label, catalog, graph, stress = false) {
  const started = performance.now();
  const args = ['mcp', '--catalog', catalog, '--root', process.cwd(), '--base-path', process.cwd(),
    '--qdrant-collection', 'code_diver_pier', '--embedding-url', 'http://127.0.0.1:8001/v1/embeddings',
    '--ce-url', 'http://127.0.0.1:18081/v1/rerank', '--qdrant-url', 'http://127.0.0.1:6333'];
  if (graph) args.push('--graph', graph);
  const child = spawn(binary, args, { stdio: ['pipe', 'pipe', 'pipe'] });
  const pending = new Map();
  const calls = [], samples = [], responses = [];
  let seq = 0, buffer = '', stderr = '', phase = 'idle', loadStart, loadMs, loadCompleteRss;
  function sample() {
    try {
      const rss = Number(execFileSync('/bin/ps', ['-o', 'rss=', '-p', String(child.pid)], { encoding: 'utf8' }).trim()) * 1024;
      samples.push({ ms: +(performance.now() - started).toFixed(3), phase, rss });
    } catch {}
  }
  const sampler = setInterval(sample, 100);
  child.stderr.on('data', b => {
    stderr += b;
    if (loadStart === undefined && stderr.includes('Loading catalog from:')) loadStart = performance.now();
    if (loadMs === undefined && /Loaded \d+ items/.test(stderr)) {
      loadMs = performance.now() - loadStart;
      sample(); loadCompleteRss = samples.at(-1)?.rss;
    }
  });
  child.stdout.on('data', b => {
    buffer += b;
    while (buffer.includes('\n')) {
      const i = buffer.indexOf('\n'), line = buffer.slice(0, i); buffer = buffer.slice(i + 1);
      const value = JSON.parse(line), p = pending.get(value.id);
      if (!p) continue;
      pending.delete(value.id); clearTimeout(p.timeout);
      calls.push({ name: p.name, ms: +(performance.now() - p.start).toFixed(3), bytes: Buffer.byteLength(line) + 1, isError: value.result?.isError ?? false, rpcError: value.error?.code });
      responses.push({ name: p.name, response: value }); p.resolve(value);
    }
  });
  function rpc(method, params = {}, name = method) {
    const id = ++seq;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error(`timeout: ${name}`)), 180000);
      pending.set(id, { resolve, start: performance.now(), name, timeout });
      child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  }
  const tool = (name, arguments_, tag = name) => rpc('tools/call', { name, arguments: arguments_ }, tag);
  try {
    const init = await rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'm4-qa', version: '1' } });
    assert.equal(init.result.serverInfo.version, '0.4.5');
    const readyMs = performance.now() - started;
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
    const list = await rpc('tools/list'); assert.equal(list.result.tools.length, 6);
    await rpc('ping'); await new Promise(r => setTimeout(r, 300)); sample();
    if (!stress) {
      for (const [name, args] of [
        ['read', { file: 'native/code_diver_search_bin/src/main.rs', lines: 5 }],
        ['grep', { pattern: 'fn main', path: 'native/code_diver_search_bin/src/main.rs', limit: 5 }],
        ['symbols', { path: 'native/code_diver_search_bin/src/main.rs', limit: 5 }],
        ['tree', { path: 'native/code_diver_search_bin/src', depth: 1, limit: 5 }], ['info', {}]]) {
        const v = await tool(`code_diver_${name}`, args); assert.equal(v.result.isError, false);
      }
      for (const [name, args] of [['read', { file: '../..' }], ['read', { file: '/etc/passwd' }],
        ['search', { query: '' }],
        ['grep', { pattern: '[', regex: true }], ['read', { file: 'README.md', lines: -1 }]]) {
        const v = await tool(`code_diver_${name}`, args, `hostile-${name}-${seq}`); assert.equal(v.result.isError, true);
      }
      const huge = await tool('code_diver_read', { file: 'README.md', lines: 1000000000 }, 'huge-lines');
      assert.equal(huge.result.isError, false);
    }
    phase = 'loading-and-first-search';
    const firstStart = performance.now();
    const search = tool('code_diver_search', { query: 'how to configure kubernetes deployment', limit: 5, preview_chars: 80 }, 'first-search');
    await new Promise(r => setTimeout(r, 20));
    const fast = await tool('code_diver_read', { file: 'README.md', lines: 3 }, 'concurrent-read');
    assert.equal(fast.result.isError, false);
    const first = await search; assert.equal(first.result.isError, false);
    assert.ok(JSON.parse(first.result.content[0].text).length > 0);
    const firstSearchMs = performance.now() - firstStart;
    phase = 'postsearch'; sample(); await new Promise(r => setTimeout(r, 300));
    if (!stress) {
      const above = await tool('code_diver_search', { query: 'test', limit: 35 }, 'hostile-limit'); assert.equal(above.result.isError, true);
      const warm = await tool('code_diver_search', { query: 'how to configure kubernetes deployment', limit: 5 }, 'warm-search'); assert.equal(warm.result.isError, false);
      const long = await tool('code_diver_search', { query: 'deployment '.repeat(1000).slice(0, 10000), limit: 3 }, '10000-char-search'); assert.equal(long.result.isError, false);
    }
    sample();
    writeFileSync(`${out}/${label}.json`, JSON.stringify({ label, catalog, readyMs, firstSearchMs, loadMs, loadCompleteRss, calls, samples, responses }, null, 2));
    console.log(JSON.stringify({ label, readyMs, firstSearchMs, loadMs, loadCompleteRss, calls, rssByPhase: Object.fromEntries(['idle', 'loading-and-first-search', 'postsearch'].map(p => [p, Math.max(0, ...samples.filter(s => s.phase === p).map(s => s.rss))])) }));
  } finally {
    writeFileSync(`${out}/${label}-raw.json`, JSON.stringify({ calls, samples, responses }, null, 2));
    clearInterval(sampler); child.stdin.end();
    await new Promise(resolve => child.on('close', resolve));
    writeFileSync(`${out}/${label}.stderr`, stderr);
  }
}
if (!process.argv.includes('--stress-only')) await run('pier', `${pier}/rust_catalog.jsonl`, `${pier}/rust_graph.jsonl`);
if (existsSync('.tmp/m2c-intellij.jsonl')) await run('intellij-stress', '.tmp/m2c-intellij.jsonl', `${out}/empty-graph.jsonl`, true);