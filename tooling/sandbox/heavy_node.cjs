'use strict';

// NODE_OPTIONS runs this before package CLI imports, including pnpm/npm children.
// Worker counts are explicit CLI overrides, so a repository config cannot expand them.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const main = (process.argv[1] || '').replaceAll('\\', '/');
const name = path.basename(main);

// Turbo's strict environment drops KEEL_* but keeps NODE_OPTIONS, so this preload still runs.
// While a slot is held, the runner's policy is the budget. KEEL_HEAVY_NODE_ACCOUNT_HOME points
// tests at a fixture home; it grants nothing that the KEEL_HEAVY_* variables do not.
function policyValue(key, fallback) {
  try {
    const keel = path.join(process.env.KEEL_HEAVY_NODE_ACCOUNT_HOME || os.userInfo().homedir, '.keel');
    const held = process.env.KEEL_HEAVY_LOCK_HELD === '1'
      || fs.readdirSync(path.join(keel, 'heavy.slots')).some((file) => /^lease\.\d+\.json$/.test(file));
    const value = held && JSON.parse(fs.readFileSync(path.join(keel, 'resource-policy.json'), 'utf8'))[key];
    return Number.isInteger(value) ? value : fallback;
  } catch {
    return fallback;
  }
}

function budget(variable, key, fallback, max) {
  const value = variable in process.env ? Number(process.env[variable]) : policyValue(key, fallback);
  return Math.max(1, Math.min(max, value || fallback));
}

const workers = () => budget('KEEL_HEAVY_MAX_WORKERS', 'max_workers', 2, 8);

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
  clamp(['--concurrency'], [`--concurrency=${budget('KEEL_HEAVY_TURBO_CONCURRENCY', 'turbo_concurrency', 1, 4)}`]);
}
