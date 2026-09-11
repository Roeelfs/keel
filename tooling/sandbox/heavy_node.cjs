'use strict';

// NODE_OPTIONS runs this before package CLI imports, including pnpm/npm children.
// Worker counts are explicit CLI overrides, so a repository config cannot expand them.
const path = require('node:path');
const main = (process.argv[1] || '').replaceAll('\\', '/');
const name = path.basename(main);
const workers = Math.max(1, Math.min(2, Number(process.env.KEEL_HEAVY_MAX_WORKERS) || 2));

function clamp(flags, additions) {
  const args = process.argv.slice(2);
  const kept = [];
  for (let i = 0; i < args.length; i++) {
    const key = args[i].split('=')[0];
    if (flags.includes(key)) {
      if (!args[i].includes('=') && args[i + 1] && !args[i + 1].startsWith('-')) i++;
    } else {
      kept.push(args[i]);
    }
  }
  process.argv = [...process.argv.slice(0, 2), ...kept, ...additions];
}

if (/^vitest(?:\.m?js)?$/.test(name)) {
  clamp(['--maxWorkers', '--max-workers', '--pool'], [`--maxWorkers=${workers}`, '--pool=forks']);
} else if (/^jest(?:\.js)?$/.test(name) && !process.argv.includes('--runInBand')) {
  clamp(['--maxWorkers', '--max-workers', '-w'], [`--maxWorkers=${workers}`]);
} else if (/^turbo(?:\.exe)?$/.test(name) || main.endsWith('/turbo/bin/turbo')) {
  clamp(['--concurrency'], ['--concurrency=1']);
}
