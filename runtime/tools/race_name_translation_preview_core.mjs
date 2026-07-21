import crypto from "node:crypto";

const HANDICAP_MARKER_RE =
  /让赛|讓賽|让步赛|讓步賽|\bHandicap\b|[（(]\s*H\s*[）)]|(?:^|[\s、，])H(?=$|[\s、，])/iu;
const IDENTITY_FIELDS = [
  "regionName",
  "sequence",
  "displayName",
  "yearsText",
  "annualEventCount",
  "seriesKey",
  "seriesId",
];
const HK_SURFACE_CORRECTION = Object.freeze({
  regionName: "中国香港",
  regionCode: "hong_kong",
  sourceSeriesId: 6019,
  sourceSeriesKey: "hong-kong-surface-bauhinia-sprint-trophy",
  targetSeriesId: 5963,
  targetSeriesKey: "hong-kong-bauhinia-sprint-trophy",
  year: 2012,
  originalName: "SURFACE Bauhinia Sprint Trophy(H)",
});
const AUTHORIZED_OUT_OF_SCOPE_NAME_CORRECTIONS = Object.freeze([
  Object.freeze({
    eventId: 96,
    year: 2026,
    seriesId: 6125,
    regionName: "日本",
    regionCode: "japan",
    originalName: "京成杯オータムH",
    beforeChineseName: "京成杯秋季让赛",
    afterChineseName: "京成杯秋季赛",
  }),
]);

function text(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function number(value, label) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) {
    throw new Error(`${label} must be an integer: ${value}`);
  }
  return parsed;
}

function increment(counter, key) {
  counter[key] = (counter[key] ?? 0) + 1;
}

function isTruthyLock(flags, keys) {
  if (!flags || typeof flags !== "object" || Array.isArray(flags)) return false;
  return keys.some((key) => Boolean(flags[key]));
}

function canonicalize(value) {
  if (typeof JSON.isRawJSON === "function" && JSON.isRawJSON(value)) {
    return value;
  }
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

export function stableJson(value) {
  return JSON.stringify(canonicalize(value));
}

export function sha256Json(value) {
  return crypto.createHash("sha256").update(stableJson(value)).digest("hex");
}

export function parseJsonPreservingNumericLexemes(source) {
  return JSON.parse(source, (key, value, context) => {
    if (
      typeof value === "number" &&
      context?.source &&
      context.source !== JSON.stringify(value)
    ) {
      return JSON.rawJSON(context.source);
    }
    return value;
  });
}

export function validateLosslessSnapshot(payload, losslessPayload) {
  const second = losslessPayload?.second;
  const content = second?.content;
  if (!content || typeof content !== "object") {
    throw new Error("lossless production snapshot content is missing");
  }
  for (const key of ["series", "events", "historicalTargets"]) {
    if (!Array.isArray(content[key])) {
      throw new Error(`lossless production snapshot ${key} must be an array`);
    }
    for (const row of content[key]) {
      if (
        !row?.fullRow ||
        sha256Json(row.fullRow.fields) !== row.fullRow.rowSha256
      ) {
        throw new Error(
          `lossless production snapshot row digest mismatch: ${key}/${row?.id}`,
        );
      }
    }
  }
  const aggregateSha256 = sha256Json(content);
  if (
    aggregateSha256 !== second.sha256 ||
    aggregateSha256 !== payload?.second?.sha256
  ) {
    throw new Error(
      `lossless production snapshot aggregate digest mismatch: local=${aggregateSha256}, server=${second.sha256}`,
    );
  }
  return content;
}

export function validateStableProductionMetadata(before, after) {
  if (stableJson(before) !== stableJson(after)) {
    throw new Error(
      `production runtime metadata drift: before=${stableJson(before)}, after=${stableJson(after)}`,
    );
  }
  return after;
}

export function reassembleSnapshotTransport(lines) {
  const prefix = "RACE_NAME_SNAPSHOT_CHUNK ";
  const chunks = lines
    .filter((line) => line.startsWith(prefix))
    .map((line) => {
      const match = line.match(
        /^RACE_NAME_SNAPSHOT_CHUNK (\d+)\/(\d+) ([A-Za-z0-9+/=]+)$/u,
      );
      if (!match) throw new Error("invalid production snapshot chunk");
      return {
        index: Number(match[1]),
        total: Number(match[2]),
        data: match[3],
      };
    });
  if (chunks.length === 0) {
    throw new Error("production snapshot chunks are missing");
  }
  const totals = new Set(chunks.map((chunk) => chunk.total));
  if (
    totals.size !== 1 ||
    chunks[0].total !== chunks.length ||
    chunks.some((chunk, index) => chunk.index !== index + 1)
  ) {
    throw new Error(
      `production snapshot chunks are incomplete: received=${chunks.length}`,
    );
  }
  return chunks.map((chunk) => chunk.data).join("");
}

export function validateAuthorizedWorkbookRevision(
  beforeRows,
  afterRows,
  {
    allowedRowIndex,
    allowedColumnIndex,
    expectedBefore,
    expectedAfter,
  },
) {
  const diffs = [];
  const rowCount = Math.max(beforeRows.length, afterRows.length);
  const columnCount = Math.max(
    0,
    ...beforeRows.map((row) => row.length),
    ...afterRows.map((row) => row.length),
  );
  for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
    for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
      const before = text(beforeRows[rowIndex]?.[columnIndex]);
      const after = text(afterRows[rowIndex]?.[columnIndex]);
      if (before !== after) {
        diffs.push({ rowIndex, columnIndex, before, after });
      }
    }
  }
  if (
    diffs.length !== 1 ||
    diffs[0].rowIndex !== allowedRowIndex ||
    diffs[0].columnIndex !== allowedColumnIndex ||
    diffs[0].before !== expectedBefore ||
    diffs[0].after !== expectedAfter
  ) {
    throw new Error(`workbook revision outside allowlist: ${stableJson(diffs)}`);
  }
  return diffs[0];
}

export function exactMatrixDiffs(before, after) {
  const diffs = [];
  const rowCount = Math.max(before.length, after.length);
  const columnCount = Math.max(
    0,
    ...before.map((row) => row.length),
    ...after.map((row) => row.length),
  );
  for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
    for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
      const beforeValue = before[rowIndex]?.[columnIndex] ?? null;
      const afterValue = after[rowIndex]?.[columnIndex] ?? null;
      if (stableJson(beforeValue) !== stableJson(afterValue)) {
        diffs.push({ rowIndex, columnIndex, before: beforeValue, after: afterValue });
      }
    }
  }
  return diffs;
}

function columnLettersToIndex(letters) {
  let index = 0;
  for (const letter of letters) {
    index = index * 26 + (letter.charCodeAt(0) - 64);
  }
  return index - 1;
}

function worksheetFullMatrix(worksheet) {
  const used = worksheet.getUsedRange();
  const address = typeof used?.address === "string" ? used.address : "A1:A1";
  const match = address.match(/^([A-Z]+)(\d+)/u);
  const startColumn = match ? columnLettersToIndex(match[1]) : 0;
  const startRow = match ? Number(match[2]) - 1 : 0;
  const rowEnd = startRow + Math.max(Number(used?.rowCount) || 1, 1);
  const columnEnd = startColumn + Math.max(Number(used?.columnCount) || 1, 1);
  const range = worksheet.getRangeByIndexes(0, 0, rowEnd, columnEnd);
  return { values: range.values, formulas: range.formulas };
}

// 全工作簿语义 diff：日本修订必须只在 allowlist 单元格有一处业务值
// 变化且公式零变化。此前只覆盖三个固定矩形，矩形外的值/公式变化会
// 穿过语义门禁；现在对全部 sheet 的完整已用范围逐一比对。
export function validateFullWorkbookRevision(
  beforeWorkbook,
  afterWorkbook,
  allowlist,
) {
  const beforeTranslationValues = beforeWorkbook.worksheets
    .getItem(allowlist.sheetName)
    .getRange(allowlist.range).values;
  const afterTranslationValues = afterWorkbook.worksheets
    .getItem(allowlist.sheetName)
    .getRange(allowlist.range).values;
  const authorizedDiff = validateAuthorizedWorkbookRevision(
    beforeTranslationValues,
    afterTranslationValues,
    allowlist,
  );
  const beforeSheets = beforeWorkbook.worksheets.items.map((sheet) => sheet.name);
  const afterSheets = afterWorkbook.worksheets.items.map((sheet) => sheet.name);
  if (stableJson(beforeSheets) !== stableJson(afterSheets)) {
    throw new Error(
      `workbook sheet set changed: before=${stableJson(beforeSheets)}, after=${stableJson(afterSheets)}`,
    );
  }
  const exactValueDiffs = [];
  const exactFormulaDiffs = [];
  for (const sheetName of beforeSheets) {
    const beforeMatrix = worksheetFullMatrix(
      beforeWorkbook.worksheets.getItem(sheetName),
    );
    const afterMatrix = worksheetFullMatrix(
      afterWorkbook.worksheets.getItem(sheetName),
    );
    exactValueDiffs.push(
      ...exactMatrixDiffs(beforeMatrix.values, afterMatrix.values).map((diff) => ({
        sheetName,
        ...diff,
      })),
    );
    exactFormulaDiffs.push(
      ...exactMatrixDiffs(beforeMatrix.formulas, afterMatrix.formulas).map(
        (diff) => ({ sheetName, ...diff }),
      ),
    );
  }
  if (
    exactValueDiffs.length !== 1 ||
    exactValueDiffs[0].sheetName !== allowlist.sheetName ||
    exactValueDiffs[0].rowIndex !== allowlist.allowedRowIndex ||
    exactValueDiffs[0].columnIndex !== allowlist.allowedColumnIndex ||
    exactFormulaDiffs.length !== 0
  ) {
    throw new Error(
      `workbook exact revision outside allowlist: ${stableJson({
        exactValueDiffs,
        exactFormulaDiffs,
      })}`,
    );
  }
  return {
    schemaVersion: "japan-workbook-authorized-revision.v1",
    ...allowlist,
    authorizedDiff,
    exactValueDiffCount: exactValueDiffs.length,
    exactFormulaDiffCount: exactFormulaDiffs.length,
  };
}

export function parseYears(value) {
  const source = text(value)
    .replaceAll("—", "–")
    .replaceAll("-", "–")
    .replaceAll("，", "、")
    .replaceAll(",", "、");
  if (!source) throw new Error("yearsText is blank");
  const years = new Set();
  for (const token of source.split("、").map((part) => part.trim()).filter(Boolean)) {
    const range = token.match(/^(\d{4})\s*–\s*(\d{4})$/u);
    if (range) {
      const start = Number(range[1]);
      const end = Number(range[2]);
      if (start > end) throw new Error(`invalid year range: ${token}`);
      for (let year = start; year <= end; year += 1) years.add(year);
      continue;
    }
    if (!/^\d{4}$/u.test(token)) throw new Error(`invalid year token: ${token}`);
    years.add(Number(token));
  }
  return [...years].sort((left, right) => left - right);
}

export function normalizeChineseDisplayName(value) {
  const reviewedChineseName = text(value);
  let chineseName = reviewedChineseName
    .replace(
      /[ \t]*[（(]\s*(?:让步赛|讓步賽|让赛|讓賽|Handicap|H)\s*[）)]/giu,
      "",
    )
    .replace(/让步赛|讓步賽|让赛|讓賽/gu, "")
    .replace(/[ \t]*\bHandicap\b/giu, "")
    .replace(/(^|[、，])[ \t]*H(?=$|[\s、，])(?!\s*\.)/giu, "$1")
    .replace(/[ \t]+H(?=$|[\s、，])(?!\s*\.)/giu, "");
  const adjusted = chineseName !== reviewedChineseName;
  if (!chineseName) {
    throw new Error(
      `Chinese name is empty after handicap normalization: ${reviewedChineseName}`,
    );
  }
  if (!/[\u3400-\u9fff]/u.test(chineseName)) {
    throw new Error(
      `Chinese name has no Chinese characters after handicap normalization: ${reviewedChineseName}`,
    );
  }
  if (HANDICAP_MARKER_RE.test(chineseName)) {
    throw new Error(
      `handicap marker remains after normalization: ${reviewedChineseName}`,
    );
  }
  return {
    reviewedChineseName,
    chineseName,
    adjusted,
    rule: adjusted ? "hide_handicap_marker" : "",
  };
}

export function validateReviewedRows(reviewedRows, baselineRows) {
  if (reviewedRows.length !== baselineRows.length) {
    throw new Error(
      `row count mismatch: reviewed=${reviewedRows.length}, baseline=${baselineRows.length}`,
    );
  }
  for (let index = 0; index < reviewedRows.length; index += 1) {
    const row = reviewedRows[index];
    const baseline = baselineRows[index];
    for (const field of IDENTITY_FIELDS) {
      if (text(row[field]) !== text(baseline[field])) {
        throw new Error(
          `identity mismatch at row ${index + 1} field ${field}: reviewed=${text(row[field])}, baseline=${text(baseline[field])}`,
        );
      }
    }
    if (text(row.status) !== "已确认") {
      throw new Error(`status must be 已确认 at row ${index + 1}`);
    }
    if (!text(row.chineseName)) {
      throw new Error(`Chinese name is blank at row ${index + 1}`);
    }
    if (!/[\u3400-\u9fff]/u.test(text(row.chineseName))) {
      throw new Error(`Chinese name has no Chinese characters at row ${index + 1}`);
    }
    if (HANDICAP_MARKER_RE.test(text(row.chineseName))) {
      throw new Error(
        `handicap marker is forbidden at ${row.regionName} row ${index + 1}: ${text(row.displayName)} -> ${text(row.chineseName)}`,
      );
    }
    if (!text(row.source)) {
      throw new Error(`source is blank at row ${index + 1}`);
    }
    const years = parseYears(row.yearsText);
    if (years.length !== number(row.annualEventCount, "annualEventCount")) {
      throw new Error(
        `annual event count mismatch at row ${index + 1}: years=${years.length}, declared=${row.annualEventCount}`,
      );
    }
  }
  return true;
}

function isHongKongCorrection(row) {
  return (
    row.regionName === HK_SURFACE_CORRECTION.regionName &&
    row.regionCode === HK_SURFACE_CORRECTION.regionCode &&
    Number(row.seriesId) === HK_SURFACE_CORRECTION.sourceSeriesId &&
    row.seriesKey === HK_SURFACE_CORRECTION.sourceSeriesKey &&
    row.displayName === HK_SURFACE_CORRECTION.originalName &&
    parseYears(row.yearsText).length === 1 &&
    parseYears(row.yearsText)[0] === HK_SURFACE_CORRECTION.year
  );
}

export function buildNormalizedManifest(
  rows,
  { expectedRowCount, expectedSeriesCount, expectedAnnualEventCount },
) {
  if (rows.length !== expectedRowCount) {
    throw new Error(
      `manifest row count mismatch: expected=${expectedRowCount}, actual=${rows.length}`,
    );
  }
  const sourceSeriesKeys = new Map();
  const targetSeriesTranslations = new Map();
  const groupActions = [];
  let annualEventCount = 0;
  let correctionCount = 0;

  for (const row of rows) {
    const sourceSeriesId = number(row.seriesId, "seriesId");
    const annualCount = number(row.annualEventCount, "annualEventCount");
    const years = parseYears(row.yearsText);
    annualEventCount += annualCount;
    const priorKey = sourceSeriesKeys.get(sourceSeriesId);
    if (priorKey && priorKey !== row.seriesKey) {
      throw new Error(`series ${sourceSeriesId} has multiple keys`);
    }
    sourceSeriesKeys.set(sourceSeriesId, row.seriesKey);

    const correction = isHongKongCorrection(row);
    if (correction) correctionCount += 1;
    const targetSeriesId = correction
      ? HK_SURFACE_CORRECTION.targetSeriesId
      : sourceSeriesId;
    const targetSeriesKey = correction
      ? HK_SURFACE_CORRECTION.targetSeriesKey
      : row.seriesKey;
    const targetKey = `${row.regionCode}:${targetSeriesId}:${targetSeriesKey}`;
    const translations = targetSeriesTranslations.get(targetKey) ?? new Set();
    translations.add(text(row.chineseName));
    targetSeriesTranslations.set(targetKey, translations);

    groupActions.push({
      regionName: row.regionName,
      regionCode: row.regionCode,
      sequence: number(row.sequence, "sequence"),
      displayName: text(row.displayName),
      proposedChineseName: text(row.chineseName),
      reviewedChineseName: text(row.reviewedChineseName || row.chineseName),
      translationRuleAdjustment: text(row.rule),
      source: text(row.source),
      sourceUrl: text(row.sourceUrl),
      sourceNote: text(row.sourceNote),
      years,
      annualEventCount: annualCount,
      sourceSeriesId,
      sourceSeriesKey: text(row.seriesKey),
      targetSeriesId,
      targetSeriesKey,
      actionType: correction ? "reassign_series_and_translate" : "translate",
      preserveOriginalName: correction,
    });
  }

  if (sourceSeriesKeys.size !== expectedSeriesCount) {
    throw new Error(
      `source series count mismatch: expected=${expectedSeriesCount}, actual=${sourceSeriesKeys.size}`,
    );
  }
  if (annualEventCount !== expectedAnnualEventCount) {
    throw new Error(
      `annual event count mismatch: expected=${expectedAnnualEventCount}, actual=${annualEventCount}`,
    );
  }
  if (correctionCount !== 1 && rows.some((row) => row.regionName === "中国香港")) {
    throw new Error(`Hong Kong SURFACE correction count must be 1, actual=${correctionCount}`);
  }

  const groupByTarget = new Map();
  for (const action of groupActions) {
    const key = `${action.regionCode}:${action.targetSeriesId}:${action.targetSeriesKey}`;
    const items = groupByTarget.get(key) ?? [];
    items.push(action);
    groupByTarget.set(key, items);
  }
  const seriesActions = [];
  for (const [key, actions] of groupByTarget.entries()) {
    const translations = targetSeriesTranslations.get(key);
    if (translations.size !== 1) {
      throw new Error(
        `series ${actions[0].targetSeriesId} has multiple Chinese names: ${[...translations].join(" | ")}`,
      );
    }
    seriesActions.push({
      regionName: actions[0].regionName,
      regionCode: actions[0].regionCode,
      seriesId: actions[0].targetSeriesId,
      seriesKey: actions[0].targetSeriesKey,
      proposedChineseName: [...translations][0],
      sourceRows: actions.map((action) => action.sequence).sort((a, b) => a - b),
    });
  }
  seriesActions.sort(
    (left, right) =>
      left.regionCode.localeCompare(right.regionCode) - right.regionCode.localeCompare(left.regionCode) ||
      left.seriesId - right.seriesId,
  );
  groupActions.sort(
    (left, right) =>
      left.regionName.localeCompare(right.regionName, "zh-CN") ||
      left.sequence - right.sequence,
  );

  const queriedSeriesIds = new Set(seriesActions.map((action) => action.seriesId));
  for (const action of groupActions) queriedSeriesIds.add(action.sourceSeriesId);

  return {
    schemaVersion: "race-name-translation-manifest.v1",
    sourceRowCount: rows.length,
    sourceSeriesCount: sourceSeriesKeys.size,
    targetSeriesCount: seriesActions.length,
    annualEventCount,
    seriesActions,
    groupActions,
    queriedSeriesIds: [...queriedSeriesIds].sort((a, b) => a - b),
    rules: {
      hideHandicapMarkers: true,
      preserveOriginalNameForHongKongCorrection: true,
      autoMergeSameChineseAcrossSeries: false,
    },
  };
}

function classifyCurrentChineseName(current, original, proposed) {
  if (current === proposed) return "already_applied";
  if (!current || current === original) return "would_update";
  return "conflict";
}

function emptyCounts() {
  return {
    would_update: 0,
    already_applied: 0,
    conflict: 0,
    locked: 0,
    missing: 0,
  };
}

export function classifyDryRun(
  manifest,
  snapshot,
  {
    authorizedOutOfScopeCorrections = AUTHORIZED_OUT_OF_SCOPE_NAME_CORRECTIONS,
  } = {},
) {
  const seriesById = new Map();
  for (const row of snapshot.series ?? []) {
    const list = seriesById.get(Number(row.id)) ?? [];
    list.push(row);
    seriesById.set(Number(row.id), list);
  }
  const events = snapshot.events ?? [];
  const historicalTargets = snapshot.historicalTargets ?? [];
  const seriesActions = [];
  const eventActions = [];
  const seriesCounts = emptyCounts();
  const eventCounts = emptyCounts();
  const identityCorrectionCounts = emptyCounts();
  const reviewedEventIds = new Set();

  for (const action of manifest.seriesActions) {
    const matches = seriesById.get(action.seriesId) ?? [];
    let classification;
    let before = matches[0] ?? null;
    if (matches.length !== 1) {
      classification = matches.length === 0 ? "missing" : "conflict";
    } else if (
      text(before.key) !== action.seriesKey ||
      text(before.countryRegion) !== action.regionCode
    ) {
      classification = "conflict";
    } else if (isTruthyLock(before.manualLockFlags, ["chinese_name"])) {
      classification = "locked";
    } else {
      classification =
        text(before.chineseName) === action.proposedChineseName
          ? "already_applied"
          : text(before.chineseName)
            ? "conflict"
            : "would_update";
    }
    increment(seriesCounts, classification);
    seriesActions.push({
      classification,
      seriesId: action.seriesId,
      seriesKey: action.seriesKey,
      regionCode: action.regionCode,
      proposedChineseName: action.proposedChineseName,
      before,
      after:
        classification === "would_update"
          ? { chineseName: action.proposedChineseName }
          : null,
    });
  }

  for (const group of manifest.groupActions) {
    for (const year of group.years) {
      const correction = group.actionType === "reassign_series_and_translate";
      const validSeriesIds = correction
        ? new Set([group.sourceSeriesId, group.targetSeriesId])
        : new Set([group.sourceSeriesId]);
      const matches = events.filter(
        (event) =>
          Number(event.year) === year &&
          validSeriesIds.has(Number(event.raceSeriesId)) &&
          text(event.originalName) === group.displayName,
      );
      let classification;
      let before = matches[0] ?? null;
      let historicalTargetBefore = null;
      let correctionClassification = null;
      if (matches.length !== 1) {
        classification = matches.length === 0 ? "missing" : "conflict";
      } else if (text(before.countryRegion) !== group.regionCode) {
        classification = "conflict";
      } else if (
        isTruthyLock(before.manualLockFlags, ["chinese_name"]) ||
        (correction &&
          isTruthyLock(before.manualLockFlags, [
            "race_series",
            "series_key",
            "identity",
          ]))
      ) {
        classification = "locked";
      } else if (
        !correction &&
        (Number(before.raceSeriesId) !== group.sourceSeriesId ||
          text(before.seriesKey) !== group.sourceSeriesKey)
      ) {
        classification = "conflict";
      } else if (correction) {
        const linkedTargets = historicalTargets.filter(
          (target) => Number(target.eventId) === Number(before.id),
        );
        const targetYearEvents = events.filter(
          (event) =>
            Number(event.year) === year &&
            Number(event.raceSeriesId) === group.targetSeriesId &&
            Number(event.id) !== Number(before.id),
        );
        historicalTargetBefore = linkedTargets[0] ?? null;
        const targetYearHistoricalTargets = historicalTargets.filter(
          (target) =>
            Number(target.year) === year &&
            Number(target.raceSeriesId) === group.targetSeriesId &&
            Number(target.id) !== Number(historicalTargetBefore?.id),
        );
        const linkedTargetIdentityMismatch =
          linkedTargets.length !== 1 ||
          Number(historicalTargetBefore?.year) !== year ||
          text(historicalTargetBefore?.countryRegion) !== group.regionCode ||
          Number(historicalTargetBefore?.raceSeriesId) !==
            Number(before.raceSeriesId);
        if (
          targetYearEvents.length > 0 ||
          targetYearHistoricalTargets.length > 0 ||
          linkedTargetIdentityMismatch
        ) {
          classification = "conflict";
          correctionClassification = "conflict";
        } else {
          const chineseNameClassification = classifyCurrentChineseName(
            text(before.chineseName),
            text(before.originalName),
            group.proposedChineseName,
          );
          const identityAlreadyApplied =
            Number(before.raceSeriesId) === group.targetSeriesId &&
            text(before.seriesKey) === group.targetSeriesKey &&
            Number(historicalTargetBefore.raceSeriesId) === group.targetSeriesId;
          if (chineseNameClassification === "conflict") {
            classification = "conflict";
            correctionClassification = "conflict";
          } else if (
            identityAlreadyApplied &&
            chineseNameClassification === "already_applied"
          ) {
            classification = "already_applied";
            correctionClassification = "already_applied";
          } else {
            classification = "would_update";
            correctionClassification = identityAlreadyApplied
              ? "already_applied"
              : "would_update";
          }
        }
      } else {
        classification = classifyCurrentChineseName(
          text(before.chineseName),
          text(before.originalName),
          group.proposedChineseName,
        );
      }

      increment(eventCounts, classification);
      if (correction) increment(identityCorrectionCounts, correctionClassification ?? classification);
      const after =
        classification === "would_update"
          ? {
              chineseName: group.proposedChineseName,
              ...(correction
                ? {
                    raceSeriesId: group.targetSeriesId,
                    seriesKey: group.targetSeriesKey,
                  }
                : {}),
            }
          : null;
      eventActions.push({
        classification,
        actionType: group.actionType,
        regionName: group.regionName,
        regionCode: group.regionCode,
        sourceSequence: group.sequence,
        year,
        displayName: group.displayName,
        reviewedChineseName: group.reviewedChineseName,
        proposedChineseName: group.proposedChineseName,
        translationRuleAdjustment: group.translationRuleAdjustment,
        eventId: before?.id ?? null,
        before,
        historicalTargetBefore,
        after,
      });
      if (before?.id !== null && before?.id !== undefined) {
        reviewedEventIds.add(Number(before.id));
      }
    }
  }

  const seriesActionById = new Map(
    manifest.seriesActions.map((action) => [Number(action.seriesId), action]),
  );
  let supplementalEventCount = 0;
  const classifiedAuthorizedCorrectionIds = new Set();
  for (const before of events) {
    if (reviewedEventIds.has(Number(before.id))) continue;
    const authorizedCorrection = authorizedOutOfScopeCorrections.find(
      (correction) => correction.eventId === Number(before.id),
    );
    const seriesAction = seriesActionById.get(
      authorizedCorrection?.seriesId ?? Number(before.raceSeriesId),
    );
    if (!seriesAction) continue;
    const currentChineseName = text(before.chineseName);
    const authorizedIdentityMatches =
      authorizedCorrection &&
      authorizedCorrection.year === Number(before.year) &&
      authorizedCorrection.seriesId === Number(before.raceSeriesId) &&
      seriesAction.seriesKey === text(before.seriesKey) &&
      authorizedCorrection.regionCode === text(before.countryRegion) &&
      authorizedCorrection.originalName === text(before.originalName) &&
      authorizedCorrection.afterChineseName ===
        seriesAction.proposedChineseName;
    const usesOriginalNameFallback =
      text(before.originalName) !== "" &&
      currentChineseName === text(before.originalName);
    if (!authorizedCorrection && !usesOriginalNameFallback) {
      continue;
    }

    let classification;
    if (
      text(before.countryRegion) !== seriesAction.regionCode ||
      Number(before.raceSeriesId) !== Number(seriesAction.seriesId) ||
      text(before.seriesKey) !== seriesAction.seriesKey ||
      (authorizedCorrection && !authorizedIdentityMatches)
    ) {
      classification = "conflict";
    } else if (isTruthyLock(before.manualLockFlags, ["chinese_name"])) {
      classification = "locked";
    } else if (
      authorizedCorrection &&
      currentChineseName === authorizedCorrection.afterChineseName
    ) {
      classification = "already_applied";
    } else if (
      authorizedCorrection &&
      currentChineseName !== authorizedCorrection.beforeChineseName
    ) {
      classification = "conflict";
    } else if (currentChineseName === seriesAction.proposedChineseName) {
      classification = "already_applied";
    } else {
      classification = "would_update";
    }
    increment(eventCounts, classification);
    supplementalEventCount += 1;
    eventActions.push({
      classification,
      actionType: authorizedCorrection
        ? "normalize_out_of_scope_handicap"
        : "translate_out_of_scope_fallback",
      regionName: seriesAction.regionName,
      regionCode: seriesAction.regionCode,
      sourceSequence: null,
      year: Number(before.year),
      displayName: text(before.originalName),
      reviewedChineseName: currentChineseName,
      proposedChineseName: seriesAction.proposedChineseName,
      translationRuleAdjustment: usesOriginalNameFallback
        ? "align_series_fallback"
        : "hide_handicap_marker",
      eventId: Number(before.id),
      before,
      historicalTargetBefore: null,
      after:
        classification === "would_update"
          ? { chineseName: seriesAction.proposedChineseName }
          : null,
    });
    if (authorizedCorrection) {
      classifiedAuthorizedCorrectionIds.add(authorizedCorrection.eventId);
    }
  }
  for (const correction of authorizedOutOfScopeCorrections) {
    if (classifiedAuthorizedCorrectionIds.has(correction.eventId)) {
      continue;
    }
    // allowlist 对象只要未被消费就必须显式 missing 阻断；即使其系列
    // 不在动作集中也不允许静默丢弃。
    const seriesAction = seriesActionById.get(correction.seriesId);
    increment(eventCounts, "missing");
    supplementalEventCount += 1;
    eventActions.push({
      classification: "missing",
      actionType: "normalize_out_of_scope_handicap",
      regionName:
        seriesAction?.regionName ?? correction.regionName ?? correction.regionCode,
      regionCode: correction.regionCode,
      sourceSequence: null,
      year: correction.year,
      displayName: correction.originalName,
      reviewedChineseName: correction.beforeChineseName,
      proposedChineseName: correction.afterChineseName,
      translationRuleAdjustment: "hide_handicap_marker",
      eventId: correction.eventId,
      before: null,
      historicalTargetBefore: null,
      after: null,
    });
  }

  const blockers =
    seriesCounts.conflict +
    seriesCounts.locked +
    seriesCounts.missing +
    eventCounts.conflict +
    eventCounts.locked +
    eventCounts.missing;
  const applyReady =
    blockers === 0 &&
    eventActions.length === manifest.annualEventCount + supplementalEventCount &&
    identityCorrectionCounts.conflict === 0 &&
    identityCorrectionCounts.locked === 0 &&
    identityCorrectionCounts.missing === 0;

  return {
    schemaVersion: "race-name-translation-dry-run.v1",
    applyReady,
    blockerCount: blockers,
    seriesCounts,
    eventCounts,
    identityCorrectionCounts,
    supplementalEventCount,
    seriesActions,
    eventActions,
  };
}

export { HK_SURFACE_CORRECTION };
