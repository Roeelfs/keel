import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { validateProductionStabilityRecord } from './validate-production-stability-record.mjs';

const valid = {
  readiness_claim: 'September pilot readiness passed because the matching simulation completed.',
  production_path: 'startNewCase → persisted cases.school_id → tenant resolver → authenticated registry read → rendered consult',
  harness_path: 'authored transcript → static expected.acceptableUnits → API-only tool transcript',
  path_gap: 'The harness never called startNewCase, read the persisted tenant, or rendered the consult route.',
  earliest_unmockable_signal: 'A claim-scoped SQL read of the inserted case school_id before matching.',
  mutation_that_must_fail: 'Restore actor.schoolId for a multi-school psychologist; the production_path plane must emit FAIL.',
};

describe('production stability record validator', () => {
  it('accepts a strict CareNet-shaped path-gap and mutation record', () => {
    assert.deepEqual(validateProductionStabilityRecord(valid), { ok: true, record: valid });
  });

  it('rejects generic coverage prose, missing fields, and unknown keys', () => {
    assert.equal(validateProductionStabilityRecord({ ...valid, path_gap: 'tests lacked coverage' }).ok, false);
    const { production_path: _removed, ...missing } = valid;
    assert.equal(validateProductionStabilityRecord(missing).ok, false);
    assert.equal(validateProductionStabilityRecord({ ...valid, confidence: 'high' }).ok, false);
  });

  it('requires the mutation to name a failing readiness effect', () => {
    assert.equal(validateProductionStabilityRecord({ ...valid, mutation_that_must_fail: 'Add a regression test.' }).ok, false);
  });
});
