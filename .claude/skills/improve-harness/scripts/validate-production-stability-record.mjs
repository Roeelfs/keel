import { pathToFileURL } from 'node:url';

export const REQUIRED_PRODUCTION_STABILITY_FIELDS = Object.freeze([
  'readiness_claim',
  'production_path',
  'harness_path',
  'path_gap',
  'earliest_unmockable_signal',
  'mutation_that_must_fail',
]);

const genericGap = /^(tests? (?:lacked|need(?:ed)?) coverage|insufficient testing|missing tests?)\.?$/i;
const failingEffect = /\b(fail|no[_ -]?go|red|reject|block)\b/i;

export function validateProductionStabilityRecord(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid('record_not_object');
  const keys = Object.keys(value).sort();
  const required = [...REQUIRED_PRODUCTION_STABILITY_FIELDS].sort();
  if (JSON.stringify(keys) !== JSON.stringify(required)) return invalid('record_keys_invalid');
  for (const field of REQUIRED_PRODUCTION_STABILITY_FIELDS) {
    const text = value[field];
    if (typeof text !== 'string' || text.trim().length < 20 || text.length > 2_000) return invalid(`${field}_invalid`);
  }
  if (genericGap.test(value.path_gap.trim())) return invalid('path_gap_generic');
  if (!failingEffect.test(value.mutation_that_must_fail)) return invalid('mutation_has_no_failing_effect');
  if (value.production_path.trim() === value.harness_path.trim()) return invalid('paths_not_distinguished');
  return { ok: true, record: value };
}

function invalid(code) {
  return { ok: false, code };
}

async function main() {
  let body = '';
  for await (const chunk of process.stdin) body += chunk;
  let value;
  try { value = JSON.parse(body); }
  catch { process.stderr.write('invalid_json\n'); process.exitCode = 1; return; }
  const result = validateProductionStabilityRecord(value);
  if (!result.ok) { process.stderr.write(`${result.code}\n`); process.exitCode = 1; return; }
  process.stdout.write('production_stability_record_valid\n');
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) await main();
