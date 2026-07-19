import assert from "node:assert/strict";

import {
  actualStartLabelFromStatuses,
  buildSourceResearchRows,
  careerConclusionRows,
  careerCountDifferenceStatement,
  careerStatusLabel,
  conflictCandidateValue,
  japanBatchConclusion,
  normalizedResultValue,
  pedigreeConflictCount,
  pedigreeCompletionStatement,
  regionNextRoute,
  regionPedigreeStatement,
  regionSourcePolicy,
  regionSummaryConclusion,
  unitedStatesCareerStatement,
  workbookBatchMetadata,
} from "./p0_horse_workbook_summary.mjs";

assert.equal(
  actualStartLabelFromStatuses({
    startStatus: "unconfirmed",
    resultStatus: "unknown",
    resultEvidenceStatus: "requires_authoritative_supplement",
  }),
  "待确认",
);
assert.equal(
  actualStartLabelFromStatuses({
    startStatus: "started",
    resultStatus: "unknown",
    resultEvidenceStatus: "requires_authoritative_supplement",
  }),
  "实际出赛（结果待补）",
);
assert.equal(
  actualStartLabelFromStatuses({
    startStatus: "did_not_start",
    resultStatus: "unknown",
    resultEvidenceStatus: "not_applicable_nonstart_verified",
  }),
  "未实际出赛",
);
assert.equal(
  normalizedResultValue(
    { normalized: { value: null, status: "not_applicable" } },
    "unknown",
  ),
  "",
);
assert.equal(
  normalizedResultValue(
    { normalized: { value: "placed", status: "mapped" } },
    "unknown",
  ),
  "placed",
);
assert.equal(
  normalizedResultValue(
    { normalized: { value: null, status: "not_applied" } },
    "unplaced",
  ),
  "unplaced",
);
assert.equal(
  normalizedResultValue(
    { normalized: { value: "finished", status: "mapped" } },
    "unknown",
  ),
  "unplaced",
);
assert.equal(normalizedResultValue({}, "unknown"), "unknown");
assert.equal(
  conflictCandidateValue({
    status: "manual_source_verified",
    direct_raw_value: "FR",
  }),
  "",
);
assert.equal(
  conflictCandidateValue({
    status: "conflict",
    source_value: "Different Dam Dam",
  }),
  "Different Dam Dam",
);

const completeHorse = {
  pedigree: {
    sire: "Sire",
    dam: "Dam",
    sire_sire: "Sire Sire",
    sire_dam: "Sire Dam",
    dam_sire: "Dam Sire",
    dam_dam: "Dam Dam",
  },
  pedigree_field_evidence: [],
};
const conflictHorse = {
  ...completeHorse,
  pedigree_field_evidence: [
    {
      field_name: "dam_dam",
      status: "conflict",
      source_value: "Different Dam Dam",
    },
  ],
};
const missingHorse = {
  pedigree: {
    sire: "Sire",
    dam: "Dam",
    sire_sire: "Sire Sire",
    sire_dam: "Sire Dam",
    dam_sire: "Dam Sire",
  },
  pedigree_field_evidence: [],
};

assert.equal(pedigreeConflictCount([completeHorse]), 0);
assert.equal(pedigreeConflictCount([conflictHorse]), 1);
assert.equal(pedigreeCompletionStatement([]), "当前输入无样本");
assert.doesNotMatch(
  pedigreeCompletionStatement([]),
  /已补齐|完整|0\s*匹|0\/0/,
);
assert.equal(regionPedigreeStatement([]), "当前输入无样本");
assert.doesNotMatch(regionPedigreeStatement([]), /已补齐|完整|0\s*匹|0\/0/);
assert.match(
  pedigreeCompletionStatement([completeHorse]),
  /父、母、父父、父母、母父、母母已全部补齐/,
);
assert.doesNotMatch(
  pedigreeCompletionStatement([conflictHorse]),
  /已全部补齐/,
);
assert.match(
  pedigreeCompletionStatement([conflictHorse]),
  /1 个冲突阻断/,
);
assert.match(regionPedigreeStatement([completeHorse]), /三代血统 1\/1/);
assert.match(regionPedigreeStatement([conflictHorse]), /1 个冲突阻断/);
assert.match(pedigreeCompletionStatement([missingHorse]), /1 匹仍有血统字段缺失/);
assert.doesNotMatch(pedigreeCompletionStatement([missingHorse]), /0 个冲突阻断/);

const conflictedJapanConclusion = japanBatchConclusion([conflictHorse], {
  hardFieldAcquired: 12,
  hardFieldTotal: 13,
  recordCount: 20,
  actualStartCount: 20,
  nonstarterCount: 0,
  knownGap: 0,
  careerComplete: true,
});
assert.match(conflictedJapanConclusion, /尚未达到本批完整标准/);
assert.match(conflictedJapanConclusion, /1 个冲突阻断/);
assert.doesNotMatch(conflictedJapanConclusion, /达到本批完整硬字段与完整履历标准/);

const incompleteCareerJapanConclusion = japanBatchConclusion([completeHorse], {
  hardFieldAcquired: 13,
  hardFieldTotal: 13,
  recordCount: 20,
  actualStartCount: 20,
  nonstarterCount: 0,
  knownGap: 0,
  careerComplete: false,
});
assert.match(incompleteCareerJapanConclusion, /尚未达到本批完整标准/);
assert.match(incompleteCareerJapanConclusion, /生涯完整状态未满足/);

const emptyRegionConclusion = regionSummaryConclusion("japan", [], {
  hardFieldAcquired: 0,
  hardFieldTotal: 0,
  careerMissingStartCount: 0,
  careerExcessStartCount: 0,
  unknownRecordCount: 0,
  careerComplete: true,
});
assert.equal(emptyRegionConclusion, "当前输入无样本");
assert.doesNotMatch(emptyRegionConclusion, /0\/0|达到|完整/);
assert.equal(
  japanBatchConclusion([], {
    hardFieldAcquired: 0,
    hardFieldTotal: 0,
    recordCount: 0,
    actualStartCount: 0,
    nonstarterCount: 0,
    knownGap: 0,
    knownExcess: 0,
    careerComplete: true,
  }),
  "日本：当前输入无样本。",
);

const incompleteRegionConclusion = regionSummaryConclusion(
  "hong_kong",
  [completeHorse],
  {
    hardFieldAcquired: 11,
    hardFieldTotal: 13,
    careerMissingStartCount: 2,
    careerExcessStartCount: 1,
    unknownRecordCount: 3,
    careerComplete: false,
  },
);
assert.match(incompleteRegionConclusion, /11\/13 个硬字段格已获取/);
assert.match(incompleteRegionConclusion, /2 个硬字段格未获取/);
assert.match(incompleteRegionConclusion, /缺少 2 场/);
assert.match(incompleteRegionConclusion, /多采 1 场/);
assert.match(incompleteRegionConclusion, /3 场结果状态待确认/);
assert.match(incompleteRegionConclusion, /生涯完整状态未满足/);
assert.doesNotMatch(
  incompleteRegionConclusion,
  /履历无缺口|来源总数与逐场履历一致|状态完整/,
);

const completeRegionConclusion = regionSummaryConclusion(
  "japan",
  [completeHorse],
  {
    hardFieldAcquired: 13,
    hardFieldTotal: 13,
    careerMissingStartCount: 0,
    careerExcessStartCount: 0,
    unknownRecordCount: 0,
    careerComplete: true,
  },
);
assert.match(completeRegionConclusion, /13\/13 个硬字段格已获取/);
assert.match(completeRegionConclusion, /三代血统 1\/1/);
assert.match(completeRegionConclusion, /硬字段、血统与履历状态完整/);

const usSourcePolicy = regionSourcePolicy("united_states");
const usMatrixPolicyText = [
  usSourcePolicy.current,
  usSourcePolicy.currentUrl,
  usSourcePolicy.next,
  usSourcePolicy.nextUrl,
  regionNextRoute("united_states", "career_record_count"),
].join("\n");
assert.doesNotMatch(usMatrixPolicyText, /Fort George|refno=\d+/);
assert.match(usSourcePolicy.currentUrl, /equibase\.com\/profiles\/Results\.cfm$/);

const japanSourcePolicy = regionSourcePolicy("japan");
const japanGapMatrixText = [
  japanSourcePolicy.current,
  japanSourcePolicy.next,
  regionNextRoute("japan", "career_record_count"),
].join("\n");
assert.doesNotMatch(
  japanGapMatrixText,
  /本批无需替代|已覆盖本批字段|本批字段已覆盖/,
);
assert.match(japanGapMatrixText, /缺口|回查/);

for (const [authority, expected] of [
  ["source_blocked", "逐场权威来源受阻"],
  ["unknown", "逐场权威性待确认"],
  ["unexpected", "逐场权威性状态异常（unexpected）"],
]) {
  assert.equal(
    careerStatusLabel({
      career: {
        source_start_count_quality: "source_declared",
        record_authority_status: authority,
      },
      field_status: {
        career_count_matches: true,
        career_gap_count: 0,
        unknown_record_count: 0,
      },
    }),
    expected,
  );
}
assert.equal(
  careerStatusLabel({
    career: {
      source_start_count_quality: "source_declared",
      record_authority_status: "source_records_verified",
    },
    field_status: {
      career_count_matches: true,
      career_gap_count: 0,
      unknown_record_count: 0,
    },
  }),
  "完整",
);

const alignedUsHorse = {
  candidate: { horse_name: "Aligned" },
  career: {
    source_start_count_quality: "official_verified",
    record_authority_status: "count_aligned_records_unverified",
    deduplicated_record_count: 1,
  },
  field_status: {
    career_gap_count: 0,
    career_missing_start_count: 0,
    career_excess_start_count: 0,
  },
};
const gapUsHorse = {
  candidate: { horse_name: "Fort George" },
  career: {
    source_start_count_quality: "official_verified",
    record_authority_status: "source_blocked",
    deduplicated_record_count: 0,
  },
  field_status: {
    career_gap_count: 7,
    career_missing_start_count: 7,
    career_excess_start_count: 0,
  },
};
const excessUsHorse = {
  candidate: { horse_name: "Duplicated" },
  career: {
    source_start_count_quality: "official_verified",
    record_authority_status: "source_blocked",
    deduplicated_record_count: 0,
  },
  field_status: {
    career_gap_count: 2,
    career_missing_start_count: 0,
    career_excess_start_count: 2,
  },
};
const usCareerStatement = unitedStatesCareerStatement([
  alignedUsHorse,
  gapUsHorse,
  excessUsHorse,
]);
assert.equal(careerCountDifferenceStatement(alignedUsHorse), "无数量差异");
assert.equal(careerCountDifferenceStatement(gapUsHorse), "缺少 7 场");
assert.equal(
  careerCountDifferenceStatement(excessUsHorse),
  "多采 2 场，待去重",
);
assert.match(usCareerStatement, /官方总数已核验 3\/3 匹/);
assert.match(usCareerStatement, /1\/3 匹与去重后的备用逐场记录数量对齐/);
assert.match(usCareerStatement, /合并 1 条同场重复行/);
assert.match(usCareerStatement, /Fort George 缺 7 场/);
assert.match(usCareerStatement, /Duplicated 多采 2 场，待去重/);
assert.match(usCareerStatement, /当前已知逐场缺少 7 场、多采待去重 2 场/);

const resultEvidence = ({
  direct = null,
  canonical = null,
  normalized = null,
} = {}) => [{
  field_name: "result",
  direct_raw: { value: direct },
  canonical_raw: { value: canonical },
  normalized: { value: normalized },
}];

const syntheticConclusions = careerConclusionRows([
  {
    region: "france",
    candidate: { horse_name: "SYNTHETIC FRANCE" },
    career: {
      records: [
        {
          finish: "2",
          result_status: "placed",
          direct_result_value: "N/A",
          result_evidence_status: "canonical_verified",
          field_evidence: resultEvidence({
            direct: "N/A",
            canonical: "2",
            normalized: "placed",
          }),
        },
        {
          finish: "tbé",
          result_status: "did_not_finish",
          direct_result_value: "N/A",
          result_evidence_status: "canonical_verified",
          field_evidence: resultEvidence({
            direct: "N/A",
            canonical: "tbé",
            normalized: "did_not_finish",
          }),
        },
      ],
    },
  },
  {
    region: "hong_kong",
    candidate: { horse_name: "SOUTHERN LEGEND" },
    field_status: {
      career_gap_count: 0,
      career_missing_start_count: 0,
      career_excess_start_count: 0,
    },
    career: {
      records: [
        { start_status: "started", finish: "1", result_status: "won" },
        {
          start_status: "did_not_start",
          finish: "SCR",
          result_status: "scratched",
        },
        {
          start_status: "started",
          finish: "4",
          result_status: "unplaced",
          is_overseas: true,
        },
      ],
    },
  },
  {
    region: "united_kingdom",
    candidate: { horse_name: "Edwardstone" },
    career: {
      records: [
        {
          start_status: "started",
          finish: "F",
          casualty: "Fell",
          result_status: "did_not_finish",
        },
        {
          start_status: "started",
          finish: "UR",
          casualty: "UnseatedRider",
          result_status: "did_not_finish",
        },
        {
          start_status: "started",
          finish: "3",
          result_status: "placed",
          direct_result_value: "N/A",
          result_evidence_status: "canonical_verified",
          field_evidence: resultEvidence({
            direct: "N/A",
            canonical: "3",
            normalized: "placed",
          }),
        },
        {
          start_status: "did_not_start",
          finish: "W",
          result_status: "withdrawn",
          direct_result_value: "N/A",
          field_evidence: resultEvidence({
            direct: "N/A",
            canonical: "W",
            normalized: null,
          }),
        },
      ],
    },
  },
]).join("\n");

assert.match(syntheticConclusions, /法国 2 条 Sporting Life N\/A/);
assert.match(
  syntheticConclusions,
  /中国香港现有 3 条履历记录：2 次实际出赛、1 次未出赛，其中 1 次为 Overseas/,
);
assert.match(syntheticConclusions, /SOUTHERN LEGEND.*无数量差异/);
assert.doesNotMatch(syntheticConclusions, /BEAUTY ONLY|TIME WARP/);
assert.match(syntheticConclusions, /Edwardstone 的 2 条 F\/UR\/BD/);
assert.match(
  syntheticConclusions,
  /2 条旧 N\/A 已核验为 1 条正式名次和 1 条未实际出赛/,
);
assert.doesNotMatch(
  syntheticConclusions,
  /法国 12 条|379 条履历记录|376 次实际出赛|5 条 F\/UR\/BD|8 条旧 N\/A/,
);

const alternateConclusions = careerConclusionRows([
  {
    region: "hong_kong",
    candidate: { horse_name: "SYNTHETIC HK" },
    career: {
      records: [
        { start_status: "started", finish: "2", result_status: "placed" },
      ],
    },
  },
]).join("\n");

assert.match(
  alternateConclusions,
  /中国香港现有 1 条履历记录：1 次实际出赛、0 次未出赛，其中 0 次为 Overseas/,
);
assert.doesNotMatch(
  alternateConclusions,
  /Edwardstone|SOUTHERN LEGEND|BEAUTY ONLY|TIME WARP/,
);
assert.notEqual(alternateConclusions, syntheticConclusions);

const sourceResearchFixture = [
  {
    region: "japan",
    candidate: { horse_name: "SYNTHETIC JAPAN" },
    field_status: {
      missing_basic_profile_fields: ["owner"],
      missing_pedigree_fields: [],
      career_missing_start_count: 2,
      career_excess_start_count: 0,
      unknown_record_count: 0,
    },
  },
  {
    region: "hong_kong",
    candidate: { horse_name: "SYNTHETIC HK" },
    field_status: {
      missing_basic_profile_fields: [],
      missing_pedigree_fields: [],
      career_missing_start_count: 0,
      career_excess_start_count: 1,
      unknown_record_count: 0,
    },
  },
  {
    region: "france",
    candidate: { horse_name: "SYNTHETIC FRANCE" },
    field_status: {
      missing_basic_profile_fields: [],
      missing_pedigree_fields: [],
      career_missing_start_count: 0,
      career_excess_start_count: 0,
      unknown_record_count: 0,
    },
    career: {
      records: [
        {
          finish: "2",
          result_status: "placed",
          direct_result_value: "N/A",
          field_evidence: resultEvidence({
            direct: "N/A",
            canonical: "2",
            normalized: "placed",
          }),
        },
        {
          finish: "tbé",
          result_status: "did_not_finish",
          direct_result_value: "N/A",
          field_evidence: resultEvidence({
            direct: "N/A",
            canonical: "tbé",
            normalized: "did_not_finish",
          }),
        },
      ],
    },
  },
  {
    region: "united_kingdom",
    candidate: { horse_name: "SYNTHETIC UK" },
    field_status: {
      missing_basic_profile_fields: [],
      missing_pedigree_fields: [],
      career_missing_start_count: 0,
      career_excess_start_count: 0,
      unknown_record_count: 0,
    },
    career: {
      records: [
        {
          start_status: "started",
          finish: "4",
          result_status: "unplaced",
          direct_result_value: "N/A",
          field_evidence: resultEvidence({
            direct: "N/A",
            canonical: "4",
            normalized: "unplaced",
          }),
        },
        {
          start_status: "did_not_start",
          finish: "W",
          result_status: "withdrawn",
          direct_result_value: "N/A",
          field_evidence: resultEvidence({
            direct: "N/A",
            canonical: "W",
            normalized: null,
          }),
        },
      ],
    },
  },
  {
    region: "united_states",
    candidate: { horse_name: "SYNTHETIC USA" },
    career: {
      source_start_count_quality: "official_verified",
      record_authority_status: "count_aligned_records_unverified",
      records: [{ source_url: "https://www.horseracingnation.com/race/one" }],
    },
    field_status: {
      missing_basic_profile_fields: [],
      missing_pedigree_fields: [],
      career_gap_count: 0,
      career_missing_start_count: 0,
      career_excess_start_count: 0,
      unknown_record_count: 0,
    },
  },
  {
    region: "united_states",
    candidate: { horse_name: "Fort George" },
    source: { name: "equibase+hrn" },
    career: {
      source_start_count_quality: "official_verified",
      record_authority_status: "count_aligned_records_unverified",
      records: [
        { source_url: "https://www.horseracingnation.com/race/base-one" },
        { source_url: "https://www.horseracingnation.com/race/base-two" },
        {
          source_name: "sporting_life",
          source_url: "https://www.sportinglife.com/racing/results/one",
        },
        {
          source_name: "sporting_life",
          source_url: "https://www.sportinglife.com/racing/results/two",
        },
        {
          source_name: "racing_post",
          source_url: "https://www.racingpost.com/results/three",
        },
      ],
    },
    field_status: {
      missing_basic_profile_fields: [],
      missing_pedigree_fields: [],
      career_gap_count: 0,
      career_missing_start_count: 0,
      career_excess_start_count: 0,
      unknown_record_count: 0,
    },
  },
];

const sourceResearchRows = buildSourceResearchRows(sourceResearchFixture);
const sourceResearchByRegion = Object.fromEntries(
  sourceResearchRows.map((row) => [row[0], row]),
);
const sourceResearchText = sourceResearchRows.flat().join("\n");

assert.match(sourceResearchByRegion["日本"][3], /1 个硬字段缺失/);
assert.match(sourceResearchByRegion["日本"][3], /缺少 2 场/);
assert.doesNotMatch(sourceResearchByRegion["日本"][3], /本批无.*缺口/);
assert.match(sourceResearchByRegion["中国香港"][3], /多采 1 场/);
assert.doesNotMatch(sourceResearchByRegion["中国香港"][3], /本批无.*缺口/);
assert.match(sourceResearchByRegion["法国"].join("\n"), /2 条 N\/A/);
assert.match(
  sourceResearchByRegion["英国"].join("\n"),
  /2 条旧 N\/A.*1 条正式名次.*1 条未实际出赛/,
);
assert.match(sourceResearchByRegion["美国"].join("\n"), /2\/2 匹/);
assert.match(
  sourceResearchByRegion["美国"].join("\n"),
  /Fort George.*3 场.*无数量差异/,
);
assert.doesNotMatch(
  sourceResearchText,
  /12 条 N\/A|8 条旧 N\/A|5 条正式名次和 3 条未实际出赛|10\/10|Fort George 7/,
);

const noNamedHorseRows = buildSourceResearchRows([
  {
    region: "japan",
    candidate: { horse_name: "ONLY JAPAN" },
    field_status: {
      missing_basic_profile_fields: [],
      missing_pedigree_fields: [],
      career_missing_start_count: 0,
      career_excess_start_count: 0,
      unknown_record_count: 0,
    },
  },
]);
const noNamedHorseText = noNamedHorseRows.flat().join("\n");
assert.doesNotMatch(noNamedHorseText, /Fort George/);
assert.match(noNamedHorseText, /当前输入无法国样本/);
assert.match(noNamedHorseText, /当前输入无英国样本/);
assert.match(noNamedHorseText, /当前输入无美国样本/);

const unevenBatchHorses = [
  ...Array.from({ length: 2 }, (_, index) => ({
    region: "france",
    candidate: { horse_name: `FRANCE ${index + 1}` },
  })),
  {
    region: "japan",
    candidate: { horse_name: "JAPAN 1" },
  },
  ...Array.from({ length: 3 }, (_, index) => ({
    region: "united_states",
    candidate: { horse_name: `USA ${index + 1}` },
    career: {
      source_start_count_quality:
        index < 2 ? "official_verified" : "source_blocked",
    },
  })),
];
const unevenBatchMetadata = workbookBatchMetadata(unevenBatchHorses);

assert.equal(unevenBatchMetadata.totalHorseCount, 6);
assert.deepEqual(unevenBatchMetadata.regionCounts, [
  { region: "france", label: "法国", count: 2 },
  { region: "japan", label: "日本", count: 1 },
  { region: "united_states", label: "美国", count: 3 },
]);
assert.equal(
  unevenBatchMetadata.summaryTitle,
  "P0 马三地区 6 匹完整解析与字段可用性审核",
);
assert.equal(
  unevenBatchMetadata.scopeStatement,
  "范围：法国 2 匹、日本 1 匹、美国 3 匹",
);
assert.equal(unevenBatchMetadata.totalSheetName, "6匹资料总表");
assert.match(
  unevenBatchMetadata.usCareerStartDictionaryNote,
  /美国 3 匹中 2 匹 Equibase Career Starts 已核验/,
);
assert.doesNotMatch(
  Object.values(unevenBatchMetadata).flat().join("\n"),
  /50匹|五地区|各 10 匹|美国 10 匹/,
);

const defaultRegionOrder = [
  "france",
  "hong_kong",
  "japan",
  "united_kingdom",
  "united_states",
];
const defaultBatchHorses = defaultRegionOrder.flatMap((region) =>
  Array.from({ length: 10 }, (_, index) => ({
    region,
    candidate: { horse_name: `${region} ${index + 1}` },
    career: {
      source_start_count_quality:
        region === "united_states" ? "official_verified" : "source_declared",
    },
  })),
);
const defaultBatchMetadata = workbookBatchMetadata(defaultBatchHorses);

assert.equal(defaultBatchMetadata.totalSheetName, "50匹资料总表");
assert.equal(
  defaultBatchMetadata.summaryTitle,
  "P0 马五地区 50 匹完整解析与字段可用性审核",
);
assert.equal(
  defaultBatchMetadata.scopeStatement,
  "范围：法国、中国香港、日本、英国、美国各 10 匹",
);
assert.equal(
  defaultBatchMetadata.usCareerStartDictionaryNote,
  "美国 10 匹 Equibase Career Starts 均已人工核验；" +
  "HRN 行数仍只是备用逐场记录，数量对齐不代表逐场官方性已确认。",
);

console.log("p0 horse workbook summary tests passed");
