import assert from "node:assert/strict";
import test from "node:test";

import {
  buildNormalizedManifest,
  classifyDryRun,
  normalizeChineseDisplayName,
  parseJsonPreservingNumericLexemes,
  parseYears,
  reassembleSnapshotTransport,
  sha256Json,
  stableJson,
  validateAuthorizedWorkbookRevision,
  validateFullWorkbookRevision,
  validateLosslessSnapshot,
  validateReviewedRows,
  validateStableProductionMetadata,
} from "./race_name_translation_preview_core.mjs";

const baselineRows = [
  {
    regionName: "中国香港",
    regionCode: "hong_kong",
    sequence: 1,
    displayName: "Bauhinia Sprint Trophy (H)",
    chineseName: "",
    status: "",
    yearsText: "2013、2017–2019",
    annualEventCount: 4,
    seriesKey: "hong-kong-bauhinia-sprint-trophy",
    seriesId: 5963,
    source: "",
    sourceUrl: "",
    sourceNote: "",
  },
  {
    regionName: "中国香港",
    regionCode: "hong_kong",
    sequence: 2,
    displayName: "SURFACE Bauhinia Sprint Trophy(H)",
    chineseName: "",
    status: "",
    yearsText: "2012",
    annualEventCount: 1,
    seriesKey: "hong-kong-surface-bauhinia-sprint-trophy",
    seriesId: 6019,
    source: "",
    sourceUrl: "",
    sourceNote: "",
  },
];

const reviewedRows = baselineRows.map((row) => ({
  ...row,
  chineseName: "洋紫荆短途锦标",
  status: "已确认",
  source: "HKJC",
  sourceUrl: "https://example.test/source",
}));

test("parseYears expands single years, separators, and closed ranges", () => {
  assert.deepEqual(parseYears("2013、2017–2019"), [2013, 2017, 2018, 2019]);
  assert.deepEqual(parseYears("2023, 2025"), [2023, 2025]);
  assert.deepEqual(parseYears("2024"), [2024]);
});

test("Japan workbook revision allows only the authorized translation cell", () => {
  const before = [[64, "Keisei Hai Autumn H", "京成杯秋季让赛", "已确认"]];
  const after = structuredClone(before);
  after[0][2] = "京成杯秋季赛";
  assert.deepEqual(
    validateAuthorizedWorkbookRevision(before, after, {
      allowedRowIndex: 0,
      allowedColumnIndex: 2,
      expectedBefore: "京成杯秋季让赛",
      expectedAfter: "京成杯秋季赛",
    }),
    {
      rowIndex: 0,
      columnIndex: 2,
      before: "京成杯秋季让赛",
      after: "京成杯秋季赛",
    },
  );
  const tampered = structuredClone(after);
  tampered[0][3] = "待审核";
  assert.throws(
    () =>
      validateAuthorizedWorkbookRevision(before, tampered, {
        allowedRowIndex: 0,
        allowedColumnIndex: 2,
        expectedBefore: "京成杯秋季让赛",
        expectedAfter: "京成杯秋季赛",
      }),
    /outside allowlist/i,
  );
});

test("reviewed identity columns must match the locked baseline", () => {
  assert.doesNotThrow(() => validateReviewedRows(reviewedRows, baselineRows));
  const changed = structuredClone(reviewedRows);
  changed[0].seriesId = 9999;
  assert.throws(
    () => validateReviewedRows(changed, baselineRows),
    /identity mismatch.*seriesId/i,
  );
});

test("handicap wording is removed explicitly before final validation", () => {
  const handicap = structuredClone(reviewedRows);
  handicap[0].chineseName = "洋紫荆短途让赛";
  const adjustment = normalizeChineseDisplayName(handicap[0].chineseName);
  assert.deepEqual(adjustment, {
    reviewedChineseName: "洋紫荆短途让赛",
    chineseName: "洋紫荆短途",
    adjusted: true,
    rule: "hide_handicap_marker",
  });
  handicap[0] = { ...handicap[0], ...adjustment };
  assert.doesNotThrow(() => validateReviewedRows(handicap, baselineRows));

  const pending = structuredClone(reviewedRows);
  pending[0].status = "待审核";
  assert.throws(() => validateReviewedRows(pending, baselineRows), /status/i);
});

test("handicap normalization preserves unrelated whitespace and punctuation", () => {
  assert.deepEqual(normalizeChineseDisplayName("前缀  名称（让赛）、"), {
    reviewedChineseName: "前缀  名称（让赛）、",
    chineseName: "前缀  名称、",
    adjusted: true,
    rule: "hide_handicap_marker",
  });
  assert.deepEqual(normalizeChineseDisplayName("前缀  名称、"), {
    reviewedChineseName: "前缀  名称、",
    chineseName: "前缀  名称、",
    adjusted: false,
    rule: "",
  });
  assert.deepEqual(normalizeChineseDisplayName("维多利亚 Handicap"), {
    reviewedChineseName: "维多利亚 Handicap",
    chineseName: "维多利亚",
    adjusted: true,
    rule: "hide_handicap_marker",
  });
  assert.deepEqual(normalizeChineseDisplayName("维多利亚（Handicap）"), {
    reviewedChineseName: "维多利亚（Handicap）",
    chineseName: "维多利亚",
    adjusted: true,
    rule: "hide_handicap_marker",
  });
  assert.deepEqual(normalizeChineseDisplayName("维多利亚(Handicap)"), {
    reviewedChineseName: "维多利亚(Handicap)",
    chineseName: "维多利亚",
    adjusted: true,
    rule: "hide_handicap_marker",
  });
  assert.deepEqual(normalizeChineseDisplayName("维多利亚 （H）"), {
    reviewedChineseName: "维多利亚 （H）",
    chineseName: "维多利亚",
    adjusted: true,
    rule: "hide_handicap_marker",
  });
  assert.deepEqual(normalizeChineseDisplayName("维多利亚 H"), {
    reviewedChineseName: "维多利亚 H",
    chineseName: "维多利亚",
    adjusted: true,
    rule: "hide_handicap_marker",
  });
  assert.deepEqual(normalizeChineseDisplayName("H. Allen 纪念赛"), {
    reviewedChineseName: "H. Allen 纪念赛",
    chineseName: "H. Allen 纪念赛",
    adjusted: false,
    rule: "",
  });
});

test("canonical JSON preserves numeric lexemes used by server-side row hashes", () => {
  const source = '{"fields":{"weight":1.0,"distance":1600},"rowSha256":"x"}';
  const parsed = parseJsonPreservingNumericLexemes(source);
  assert.equal(
    stableJson(parsed),
    '{"fields":{"distance":1600,"weight":1.0},"rowSha256":"x"}',
  );
  assert.equal(
    sha256Json(parsed.fields),
    "69623ee908317172027cb20705ad7c972e37d54eae956dc14bc535a5f428ea07",
  );
});

test("snapshot transport requires a complete ordered chunk set", () => {
  assert.equal(
    reassembleSnapshotTransport([
      "ignored framework output",
      "RACE_NAME_SNAPSHOT_CHUNK 1/2 YW",
      "RACE_NAME_SNAPSHOT_CHUNK 2/2 Jj",
    ]),
    "YWJj",
  );
  assert.throws(
    () =>
      reassembleSnapshotTransport([
        "RACE_NAME_SNAPSHOT_CHUNK 1/3 YW",
        "RACE_NAME_SNAPSHOT_CHUNK 3/3 Jj",
      ]),
    /incomplete/i,
  );
});

test("manifest aggregates one Chinese name per series and expands event years", () => {
  const manifest = buildNormalizedManifest(reviewedRows, {
    expectedRowCount: 2,
    expectedSeriesCount: 2,
    expectedAnnualEventCount: 5,
  });
  assert.equal(manifest.sourceSeriesCount, 2);
  assert.equal(manifest.seriesActions.length, 1);
  assert.equal(manifest.groupActions.length, 2);
  assert.equal(manifest.groupActions[0].years.length, 4);
  assert.equal(manifest.groupActions[1].actionType, "reassign_series_and_translate");
  assert.equal(manifest.groupActions[1].targetSeriesId, 5963);
  assert.equal(manifest.groupActions[1].preserveOriginalName, true);
});

test("manifest fails when one series has multiple reviewed Chinese names", () => {
  const inconsistent = [
    reviewedRows[0],
    reviewedRows[1],
    {
      ...reviewedRows[0],
      sequence: 3,
      displayName: "Bauhinia Sprint Trophy [Sponsor] (H)",
      yearsText: "2020",
      annualEventCount: 1,
      chineseName: "洋紫荆短途大赛",
    },
  ];
  assert.throws(
    () =>
      buildNormalizedManifest(inconsistent, {
        expectedRowCount: 3,
        expectedSeriesCount: 2,
        expectedAnnualEventCount: 6,
      }),
    /multiple Chinese names/i,
  );
});

test("dry-run classifies updates, existing values, locks, and Hong Kong conflict", () => {
  const manifest = buildNormalizedManifest(reviewedRows, {
    expectedRowCount: 2,
    expectedSeriesCount: 2,
    expectedAnnualEventCount: 5,
  });
  const snapshot = {
    series: [
      {
        id: 5963,
        key: "hong-kong-bauhinia-sprint-trophy",
        countryRegion: "hong_kong",
        chineseName: "",
        manualLockFlags: {},
        updatedAt: "2026-07-20T00:00:00Z",
      },
      {
        id: 6019,
        key: "hong-kong-surface-bauhinia-sprint-trophy",
        countryRegion: "hong_kong",
        chineseName: "",
        manualLockFlags: {},
        updatedAt: "2026-07-20T00:00:00Z",
      },
    ],
    events: [
      ...[2013, 2017, 2018, 2019].map((year, index) => ({
        id: 100 + index,
        year,
        raceSeriesId: 5963,
        seriesKey: "hong-kong-bauhinia-sprint-trophy",
        countryRegion: "hong_kong",
        originalName: "Bauhinia Sprint Trophy (H)",
        chineseName: "Bauhinia Sprint Trophy (H)",
        manualLockFlags: {},
        updatedAt: "2026-07-20T00:00:00Z",
      })),
      {
        id: 200,
        year: 2012,
        raceSeriesId: 6019,
        seriesKey: "hong-kong-surface-bauhinia-sprint-trophy",
        countryRegion: "hong_kong",
        originalName: "SURFACE Bauhinia Sprint Trophy(H)",
        chineseName: "SURFACE Bauhinia Sprint Trophy(H)",
        manualLockFlags: {},
        updatedAt: "2026-07-20T00:00:00Z",
      },
    ],
    historicalTargets: [
      {
        id: 400,
        eventId: 200,
        year: 2012,
        raceSeriesId: 6019,
        countryRegion: "hong_kong",
        fullRow: {
          fields: { id: 400, event_id: 200, race_series_id: 6019, year: 2012 },
          rowSha256: "target-before",
        },
      },
    ],
  };

  const result = classifyDryRun(manifest, snapshot, {
    authorizedOutOfScopeCorrections: [],
  });
  assert.equal(result.applyReady, true);
  assert.equal(result.eventCounts.would_update, 5);
  assert.equal(result.identityCorrectionCounts.would_update, 1);
  assert.equal(result.eventActions.find((row) => row.eventId === 200).after.raceSeriesId, 5963);
  assert.equal(
    result.eventActions.find((row) => row.eventId === 200).after.originalName,
    undefined,
  );
  assert.equal(
    result.eventActions.find((row) => row.eventId === 200)
      .historicalTargetBefore.id,
    400,
  );

  const locked = structuredClone(snapshot);
  locked.events[0].manualLockFlags = { chinese_name: true };
  const lockedResult = classifyDryRun(manifest, locked, {
    authorizedOutOfScopeCorrections: [],
  });
  assert.equal(lockedResult.applyReady, false);
  assert.equal(lockedResult.eventCounts.locked, 1);

  const targetYearCollision = structuredClone(snapshot);
  targetYearCollision.events.push({
    ...targetYearCollision.events[0],
    id: 300,
    year: 2012,
    raceSeriesId: 5963,
  });
  const collisionResult = classifyDryRun(manifest, targetYearCollision, {
    authorizedOutOfScopeCorrections: [],
  });
  assert.equal(collisionResult.applyReady, false);
  assert.equal(collisionResult.identityCorrectionCounts.conflict, 1);

  const targetCollision = structuredClone(snapshot);
  targetCollision.historicalTargets.push({
    ...targetCollision.historicalTargets[0],
    id: 401,
    eventId: null,
    raceSeriesId: 5963,
  });
  const targetCollisionResult = classifyDryRun(manifest, targetCollision, {
    authorizedOutOfScopeCorrections: [],
  });
  assert.equal(targetCollisionResult.applyReady, false);
  assert.equal(targetCollisionResult.identityCorrectionCounts.conflict, 1);
});

test("Hong Kong correction remains an update when only the Chinese name is already applied", () => {
  const manifest = buildNormalizedManifest(reviewedRows, {
    expectedRowCount: 2,
    expectedSeriesCount: 2,
    expectedAnnualEventCount: 5,
  });
  const snapshot = {
    series: [
      {
        id: 5963,
        key: "hong-kong-bauhinia-sprint-trophy",
        countryRegion: "hong_kong",
        chineseName: "洋紫荆短途锦标",
        manualLockFlags: {},
      },
    ],
    events: [
      ...[2013, 2017, 2018, 2019].map((year, index) => ({
        id: 100 + index,
        year,
        raceSeriesId: 5963,
        seriesKey: "hong-kong-bauhinia-sprint-trophy",
        countryRegion: "hong_kong",
        originalName: "Bauhinia Sprint Trophy (H)",
        chineseName: "洋紫荆短途锦标",
        manualLockFlags: {},
      })),
      {
        id: 200,
        year: 2012,
        raceSeriesId: 6019,
        seriesKey: "hong-kong-surface-bauhinia-sprint-trophy",
        countryRegion: "hong_kong",
        originalName: "SURFACE Bauhinia Sprint Trophy(H)",
        chineseName: "洋紫荆短途锦标",
        manualLockFlags: {},
      },
    ],
    historicalTargets: [
      {
        id: 400,
        eventId: 200,
        year: 2012,
        raceSeriesId: 6019,
        countryRegion: "hong_kong",
        fullRow: {
          fields: { id: 400, event_id: 200, race_series_id: 6019, year: 2012 },
          rowSha256: "target-before",
        },
      },
    ],
  };

  const result = classifyDryRun(manifest, snapshot, {
    authorizedOutOfScopeCorrections: [],
  });
  const correction = result.eventActions.find((row) => row.eventId === 200);
  assert.equal(result.applyReady, true);
  assert.equal(correction.classification, "would_update");
  assert.deepEqual(correction.after, {
    chineseName: "洋紫荆短途锦标",
    raceSeriesId: 5963,
    seriesKey: "hong-kong-bauhinia-sprint-trophy",
  });
  assert.equal(result.identityCorrectionCounts.would_update, 1);
});

test("dry-run includes an out-of-workbook same-series handicap correction", () => {
  const japanRow = {
    regionName: "日本",
    regionCode: "japan",
    sequence: 64,
    displayName: "京成杯オータムH",
    chineseName: "京成杯秋季赛",
    reviewedChineseName: "京成杯秋季赛",
    status: "已确认",
    yearsText: "2025",
    annualEventCount: 1,
    seriesKey: "japan-keisei-hai-autumn-handicap",
    seriesId: 6125,
    source: "JRA",
    sourceUrl: "https://example.test/jra",
    sourceNote: "",
  };
  const manifest = buildNormalizedManifest([japanRow], {
    expectedRowCount: 1,
    expectedSeriesCount: 1,
    expectedAnnualEventCount: 1,
  });
  const snapshot = {
    series: [
      {
        id: 6125,
        key: "japan-keisei-hai-autumn-handicap",
        countryRegion: "japan",
        chineseName: "",
        manualLockFlags: {},
      },
    ],
    events: [
      {
        id: 100,
        year: 2025,
        raceSeriesId: 6125,
        seriesKey: "japan-keisei-hai-autumn-handicap",
        countryRegion: "japan",
        originalName: "京成杯オータムH",
        chineseName: "京成杯オータムH",
        manualLockFlags: {},
      },
      {
        id: 96,
        year: 2026,
        raceSeriesId: 6125,
        seriesKey: "japan-keisei-hai-autumn-handicap",
        countryRegion: "japan",
        originalName: "京成杯オータムH",
        chineseName: "京成杯秋季让赛",
        manualLockFlags: {},
      },
    ],
    historicalTargets: [],
  };
  const result = classifyDryRun(manifest, snapshot);
  const supplemental = result.eventActions.find((row) => row.eventId === 96);
  assert.equal(result.applyReady, true);
  assert.equal(result.supplementalEventCount, 1);
  assert.equal(supplemental.actionType, "normalize_out_of_scope_handicap");
  assert.deepEqual(supplemental.after, { chineseName: "京成杯秋季赛" });
});

test("authorized out-of-workbook correction is always classified", () => {
  const japanRow = {
    regionName: "日本",
    regionCode: "japan",
    sequence: 64,
    displayName: "京成杯オータムH",
    chineseName: "京成杯秋季赛",
    reviewedChineseName: "京成杯秋季赛",
    status: "已确认",
    yearsText: "2025",
    annualEventCount: 1,
    seriesKey: "japan-keisei-hai-autumn-handicap",
    seriesId: 6125,
    source: "JRA",
    sourceUrl: "https://example.test/jra",
    sourceNote: "",
  };
  const manifest = buildNormalizedManifest([japanRow], {
    expectedRowCount: 1,
    expectedSeriesCount: 1,
    expectedAnnualEventCount: 1,
  });
  const baseSnapshot = {
    series: [
      {
        id: 6125,
        key: "japan-keisei-hai-autumn-handicap",
        countryRegion: "japan",
        chineseName: "",
        manualLockFlags: {},
      },
    ],
    events: [
      {
        id: 100,
        year: 2025,
        raceSeriesId: 6125,
        seriesKey: "japan-keisei-hai-autumn-handicap",
        countryRegion: "japan",
        originalName: "京成杯オータムH",
        chineseName: "京成杯オータムH",
        manualLockFlags: {},
      },
    ],
    historicalTargets: [],
  };
  const correctionEvent = {
    id: 96,
    year: 2026,
    raceSeriesId: 6125,
    seriesKey: "japan-keisei-hai-autumn-handicap",
    countryRegion: "japan",
    originalName: "京成杯オータムH",
    chineseName: "京成杯秋季赛",
    manualLockFlags: {},
  };

  const alreadyApplied = classifyDryRun(manifest, {
    ...baseSnapshot,
    events: [...baseSnapshot.events, correctionEvent],
  });
  const alreadyAppliedAction = alreadyApplied.eventActions.find(
    (row) => row.eventId === 96,
  );
  assert.equal(alreadyApplied.applyReady, true);
  assert.equal(alreadyApplied.supplementalEventCount, 1);
  assert.equal(alreadyAppliedAction.classification, "already_applied");
  assert.equal(alreadyAppliedAction.after, null);

  for (const chineseName of ["京成杯秋季", "京成杯オータムH"]) {
    const conflict = classifyDryRun(manifest, {
      ...baseSnapshot,
      events: [...baseSnapshot.events, { ...correctionEvent, chineseName }],
    });
    const action = conflict.eventActions.find((row) => row.eventId === 96);
    assert.equal(conflict.applyReady, false);
    assert.equal(action.classification, "conflict");
  }

  const identityDrift = classifyDryRun(manifest, {
    ...baseSnapshot,
    events: [
      ...baseSnapshot.events,
      { ...correctionEvent, chineseName: "京成杯秋季让赛", year: 2027 },
    ],
  });
  assert.equal(identityDrift.applyReady, false);
  assert.equal(
    identityDrift.eventActions.find((row) => row.eventId === 96).classification,
    "conflict",
  );

  const seriesKeyDrift = classifyDryRun(manifest, {
    ...baseSnapshot,
    events: [
      ...baseSnapshot.events,
      {
        ...correctionEvent,
        chineseName: "京成杯秋季让赛",
        seriesKey: "japan-stale-series-key",
      },
    ],
  });
  assert.equal(seriesKeyDrift.applyReady, false);
  assert.equal(
    seriesKeyDrift.eventActions.find((row) => row.eventId === 96).classification,
    "conflict",
  );

  const missing = classifyDryRun(manifest, baseSnapshot);
  const missingAction = missing.eventActions.find((row) => row.eventId === 96);
  assert.equal(missing.applyReady, false);
  assert.equal(missing.supplementalEventCount, 1);
  assert.equal(missingAction.classification, "missing");
});

test("out-of-workbook original-name fallback follows its translated series", () => {
  const row = {
    regionName: "美国",
    regionCode: "united_states",
    sequence: 1,
    displayName: "Test Stakes",
    chineseName: "测试锦标",
    reviewedChineseName: "测试锦标",
    status: "已确认",
    yearsText: "2025",
    annualEventCount: 1,
    seriesKey: "united-states-test-stakes",
    seriesId: 7000,
    source: "TEST",
    sourceUrl: "https://example.test",
    sourceNote: "",
  };
  const manifest = buildNormalizedManifest([row], {
    expectedRowCount: 1,
    expectedSeriesCount: 1,
    expectedAnnualEventCount: 1,
  });
  const baseSnapshot = {
    series: [
      {
        id: 7000,
        key: "united-states-test-stakes",
        countryRegion: "united_states",
        chineseName: "",
        manualLockFlags: {},
      },
    ],
    events: [
      {
        id: 7001,
        year: 2025,
        raceSeriesId: 7000,
        seriesKey: "united-states-test-stakes",
        countryRegion: "united_states",
        originalName: "Test Stakes",
        chineseName: "Test Stakes",
        manualLockFlags: {},
      },
      {
        id: 7002,
        year: 2026,
        raceSeriesId: 7000,
        seriesKey: "united-states-test-stakes",
        countryRegion: "united_states",
        originalName: "Test Stakes",
        chineseName: "Test Stakes",
        manualLockFlags: {},
      },
    ],
    historicalTargets: [],
  };

  const result = classifyDryRun(manifest, baseSnapshot, {
    authorizedOutOfScopeCorrections: [],
  });
  const supplemental = result.eventActions.find((item) => item.eventId === 7002);
  assert.equal(result.applyReady, true);
  assert.equal(result.supplementalEventCount, 1);
  assert.equal(supplemental.classification, "would_update");
  assert.equal(supplemental.actionType, "translate_out_of_scope_fallback");
  assert.equal(
    supplemental.translationRuleAdjustment,
    "align_series_fallback",
  );
  assert.deepEqual(supplemental.after, { chineseName: "测试锦标" });

  const locked = classifyDryRun(
    manifest,
    {
      ...baseSnapshot,
      events: baseSnapshot.events.map((event) =>
        event.id === 7002
          ? { ...event, manualLockFlags: { chinese_name: true } }
          : event,
      ),
    },
    { authorizedOutOfScopeCorrections: [] },
  );
  assert.equal(locked.applyReady, false);
  assert.equal(
    locked.eventActions.find((item) => item.eventId === 7002).classification,
    "locked",
  );

  const wrongRegion = classifyDryRun(
    manifest,
    {
      ...baseSnapshot,
      events: baseSnapshot.events.map((event) =>
        event.id === 7002
          ? { ...event, countryRegion: "france" }
          : event,
      ),
    },
    { authorizedOutOfScopeCorrections: [] },
  );
  assert.equal(wrongRegion.applyReady, false);
  assert.equal(
    wrongRegion.eventActions.find((item) => item.eventId === 7002)
      .classification,
    "conflict",
  );

  const wrongSeriesKey = classifyDryRun(
    manifest,
    {
      ...baseSnapshot,
      events: baseSnapshot.events.map((event) =>
        event.id === 7002
          ? { ...event, seriesKey: "united-states-stale-series-key" }
          : event,
      ),
    },
    { authorizedOutOfScopeCorrections: [] },
  );
  assert.equal(wrongSeriesKey.applyReady, false);
  assert.equal(
    wrongSeriesKey.eventActions.find((item) => item.eventId === 7002)
      .classification,
    "conflict",
  );

  const independentHandicapName = classifyDryRun(
    manifest,
    {
      ...baseSnapshot,
      events: [
        ...baseSnapshot.events,
        {
          ...baseSnapshot.events[1],
          id: 7003,
          chineseName: "人工独立让赛",
        },
      ],
    },
    { authorizedOutOfScopeCorrections: [] },
  );
  assert.equal(independentHandicapName.applyReady, true);
  assert.equal(independentHandicapName.supplementalEventCount, 1);
  assert.equal(
    independentHandicapName.eventActions.some((item) => item.eventId === 7003),
    false,
  );
});

test("lossless snapshot validates every row and aggregate digest", () => {
  const content = {
    series: [
      {
        id: 1,
        fullRow: {
          fields: { id: 1, weight: "55.00" },
          rowSha256: sha256Json({ id: 1, weight: "55.00" }),
        },
      },
    ],
    events: [],
    historicalTargets: [],
  };
  const sha256 = sha256Json(content);
  const payload = { second: { sha256 } };
  const lossless = { second: { content, sha256 } };
  assert.equal(validateLosslessSnapshot(payload, lossless), content);

  assert.throws(
    () =>
      validateLosslessSnapshot(payload, {
        second: {
          content: {
            ...content,
            series: [
              {
                ...content.series[0],
                fullRow: {
                  ...content.series[0].fullRow,
                  fields: { id: 1, weight: "55.0" },
                },
              },
            ],
          },
          sha256,
        },
      }),
    /row digest mismatch/u,
  );
  assert.throws(
    () =>
      validateLosslessSnapshot(
        { second: { sha256: "0".repeat(64) } },
        lossless,
      ),
    /aggregate digest mismatch/u,
  );
});

test("production runtime metadata must remain identical around snapshot", () => {
  const metadata = {
    gitHead: "a".repeat(40),
    imageId: "sha256:test",
    containerStartedAt: "2026-07-20T00:00:00Z",
  };
  assert.deepEqual(
    validateStableProductionMetadata(metadata, { ...metadata }),
    metadata,
  );
  assert.throws(
    () =>
      validateStableProductionMetadata(metadata, {
        ...metadata,
        imageId: "sha256:replacement",
      }),
    /runtime metadata drift/u,
  );
});

test("supplemental fallback requires a non-empty original name", () => {
  const row = {
    regionName: "美国",
    regionCode: "united_states",
    sequence: 1,
    displayName: "Test Stakes",
    chineseName: "测试锦标",
    reviewedChineseName: "测试锦标",
    status: "已确认",
    yearsText: "2025",
    annualEventCount: 1,
    seriesKey: "united-states-test-stakes",
    seriesId: 7000,
    source: "TEST",
    sourceUrl: "https://example.test",
    sourceNote: "",
  };
  const manifest = buildNormalizedManifest([row], {
    expectedRowCount: 1,
    expectedSeriesCount: 1,
    expectedAnnualEventCount: 1,
  });
  const snapshot = {
    series: [
      {
        id: 7000,
        key: "united-states-test-stakes",
        countryRegion: "united_states",
        chineseName: "",
        manualLockFlags: {},
      },
    ],
    events: [
      {
        id: 7001,
        year: 2025,
        raceSeriesId: 7000,
        seriesKey: "united-states-test-stakes",
        countryRegion: "united_states",
        originalName: "Test Stakes",
        chineseName: "Test Stakes",
        manualLockFlags: {},
      },
      {
        id: 7002,
        year: 2024,
        raceSeriesId: 7000,
        seriesKey: "united-states-test-stakes",
        countryRegion: "united_states",
        originalName: "",
        chineseName: "",
        manualLockFlags: {},
      },
    ],
    historicalTargets: [],
  };
  const result = classifyDryRun(manifest, snapshot, {
    authorizedOutOfScopeCorrections: [],
  });
  assert.equal(result.supplementalEventCount, 0);
  assert.equal(
    result.eventActions.some((action) => action.eventId === 7002),
    false,
  );
});

test("unconsumed authorized correction is always a missing blocker", () => {
  const row = {
    regionName: "日本",
    regionCode: "japan",
    sequence: 1,
    displayName: "Some Other Stakes",
    chineseName: "其他锦标",
    reviewedChineseName: "其他锦标",
    status: "已确认",
    yearsText: "2025",
    annualEventCount: 1,
    seriesKey: "japan-some-other-stakes",
    seriesId: 9999,
    source: "TEST",
    sourceUrl: "https://example.test",
    sourceNote: "",
  };
  const manifest = buildNormalizedManifest([row], {
    expectedRowCount: 1,
    expectedSeriesCount: 1,
    expectedAnnualEventCount: 1,
  });
  const snapshot = {
    series: [
      {
        id: 9999,
        key: "japan-some-other-stakes",
        countryRegion: "japan",
        chineseName: "",
        manualLockFlags: {},
      },
    ],
    events: [
      {
        id: 9998,
        year: 2025,
        raceSeriesId: 9999,
        seriesKey: "japan-some-other-stakes",
        countryRegion: "japan",
        originalName: "Some Other Stakes",
        chineseName: "Some Other Stakes",
        manualLockFlags: {},
      },
      {
        id: 96,
        year: 2026,
        raceSeriesId: 6125,
        seriesKey: "japan-keisei-hai-autumn-h",
        countryRegion: "japan",
        originalName: "京成杯オータムH",
        chineseName: "京成杯秋季让赛",
        manualLockFlags: {},
      },
    ],
    historicalTargets: [],
  };
  const result = classifyDryRun(manifest, snapshot);
  const correction = result.eventActions.find((action) => action.eventId === 96);
  assert.equal(result.applyReady, false);
  assert.ok(result.blockerCount > 0);
  assert.equal(correction.classification, "missing");
  assert.equal(correction.actionType, "normalize_out_of_scope_handicap");
});

function mockRevisionWorkbook(sheets) {
  return {
    worksheets: {
      items: sheets.map((sheet) => ({ name: sheet.name })),
      getItem(name) {
        const sheet = sheets.find((candidate) => candidate.name === name);
        if (!sheet) throw new Error(`sheet not found: ${name}`);
        const blankFormulas = sheet.values.map((row) => row.map(() => ""));
        return {
          name,
          getRange() {
            return { values: sheet.values };
          },
          getUsedRange() {
            return {
              address: sheet.address,
              rowCount: sheet.values.length,
              columnCount: Math.max(0, ...sheet.values.map((row) => row.length)),
            };
          },
          getRangeByIndexes(rowIndex, columnIndex, rowCount, columnCount) {
            const build = (matrix) =>
              Array.from({ length: rowCount }, (_, r) =>
                Array.from(
                  { length: columnCount },
                  (_, c) => matrix?.[r]?.[c] ?? null,
                ),
              );
            return {
              values: build(sheet.values),
              formulas: build(sheet.formulas ?? blankFormulas),
            };
          },
        };
      },
    },
  };
}

const revisionAllowlist = Object.freeze({
  sheetName: "翻译清单",
  range: "A1:L180",
  allowedRowIndex: 1,
  allowedColumnIndex: 2,
  allowedAddress: "C2",
  expectedBefore: "京成杯秋季让赛",
  expectedAfter: "京成杯秋季赛",
});

function revisionSheets(overrides = {}) {
  return [
    {
      name: "使用说明",
      address: "A1:H40",
      values: [
        ["说明", null, null],
        [null, "文本", null],
      ],
      ...overrides.instructions,
    },
    {
      name: "翻译清单",
      address: "A1:L180",
      values: [
        ["序号", "展示名", "建议中文名"],
        [1, "Keisei Hai Autumn H", "京成杯秋季让赛"],
      ],
      ...overrides.list,
    },
  ];
}

test("full-workbook revision gate allows only the authorized cell", () => {
  const before = mockRevisionWorkbook(revisionSheets());
  const after = mockRevisionWorkbook(
    revisionSheets({
      list: {
        values: [
          ["序号", "展示名", "建议中文名"],
          [1, "Keisei Hai Autumn H", "京成杯秋季赛"],
        ],
      },
    }),
  );
  const result = validateFullWorkbookRevision(before, after, revisionAllowlist);
  assert.equal(result.exactValueDiffCount, 1);
  assert.equal(result.exactFormulaDiffCount, 0);
  assert.equal(result.authorizedDiff.after, "京成杯秋季赛");
});

test("full-workbook revision gate blocks changes outside the legacy rectangles", () => {
  const before = mockRevisionWorkbook(revisionSheets());
  const tamperedCell = mockRevisionWorkbook(
    revisionSheets({
      instructions: {
        values: [
          ["说明", null, null],
          [null, "被篡改", null],
        ],
      },
      list: {
        values: [
          ["序号", "展示名", "建议中文名"],
          [1, "Keisei Hai Autumn H", "京成杯秋季赛"],
        ],
      },
    }),
  );
  assert.throws(
    () => validateFullWorkbookRevision(before, tamperedCell, revisionAllowlist),
    /outside allowlist/u,
  );

  const formulaChange = mockRevisionWorkbook(
    revisionSheets({
      instructions: { formulas: [["=1+1", null], [null, null]] },
      list: {
        values: [
          ["序号", "展示名", "建议中文名"],
          [1, "Keisei Hai Autumn H", "京成杯秋季赛"],
        ],
      },
    }),
  );
  assert.throws(
    () => validateFullWorkbookRevision(before, formulaChange, revisionAllowlist),
    /outside allowlist/u,
  );

  const sheetAdded = mockRevisionWorkbook([
    ...revisionSheets({
      list: {
        values: [
          ["序号", "展示名", "建议中文名"],
          [1, "Keisei Hai Autumn H", "京成杯秋季赛"],
        ],
      },
    }),
    { name: "额外", address: "A1:A1", values: [["x"]] },
  ]);
  assert.throws(
    () => validateFullWorkbookRevision(before, sheetAdded, revisionAllowlist),
    /sheet set changed/u,
  );
});
