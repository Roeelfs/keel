'use strict';

// NODE_OPTIONS runs this before package CLI imports, including pnpm/npm children.
// Worker counts are explicit CLI overrides, so a repository config cannot expand them.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const main = (process.argv[1] || '').replaceAll('\\', '/');
const name = path.basename(main);

// Turbo's strict environment drops KEEL_* but keeps NODE_OPTIONS, so this preload still runs.
// While the slot is held, the runner's policy is the budget. KEEL_HEAVY_NODE_ACCOUNT_HOME points
// tests at a fixture home; it grants nothing that KEEL_HEAVY_MAX_WORKERS does not.
function policyWorkers() {
  try {
    const keel = path.join(process.env.KEEL_HEAVY_NODE_ACCOUNT_HOME || os.userInfo().homedir, '.keel');
    const held = process.env.KEEL_HEAVY_LOCK_HELD === '1'
      || fs.readdirSync(path.join(keel, 'heavy.slots')).some((file) => /^lease\.\d+\.json$/.test(file));
    const value = held && JSON.parse(fs.readFileSync(path.join(keel, 'resource-policy.json'), 'utf8')).max_workers;
    return Number.isInteger(value) ? value : 2;
  } catch {
    return 2;
  }
}

function workers() {
  const value = 'KEEL_HEAVY_MAX_WORKERS' in process.env ? Number(process.env.KEEL_HEAVY_MAX_WORKERS) : policyWorkers();
  return Math.max(1, Math.min(8, value || 2));
}

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
  clamp(['--maxWorkers', '--max-workers', '--pool'], [`--maxWorkers=${workers()}`, '--pool=forks']);
} else if (/^jest(?:\.js)?$/.test(name) && !process.argv.includes('--runInBand')) {
  clamp(['--maxWorkers', '--max-workers', '-w'], [`--maxWorkers=${workers()}`]);
} else if (/^turbo(?:\.exe)?$/.test(name) || main.endsWith('/turbo/bin/turbo')) {
  clamp(['--concurrency'], ['--concurrency=1']);
}
