import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import {
  actualStartLabelFromStatuses,
  buildSourceResearchRows,
  careerConclusionRows,
  careerCountDifferenceStatement,
  careerStatusLabel,
  conflictCandidateValue,
  japanBatchConclusion,
  normalizedResultValue,
  pedigreeCompletionStatement,
  regionNextRoute,
  regionPedigreeStatement,
  regionSourcePolicy,
  regionSummaryConclusion,
  workbookBatchMetadata,
} from "./p0_horse_workbook_summary.mjs";
import {
  P0_HORSE_WORKBOOK_BUILD_CONFIG_RELATIVE_PATH,
  resolveP0HorseWorkbookBuildPaths,
} from "./p0_horse_workbook_build_paths.mjs";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");
const configPath = path.join(
  root,
  P0_HORSE_WORKBOOK_BUILD_CONFIG_RELATIVE_PATH,
);
let buildConfig = {};
try {
  buildConfig = JSON.parse(await fs.readFile(configPath, "utf8"));
} catch (error) {
  if (error?.code !== "ENOENT") {
    throw error;
  }
}
const {
  inputPath,
  outputPath,
  previewDir,
} = resolveP0HorseWorkbookBuildPaths({
  root,
  env: process.env,
  config: buildConfig,
});
const outputDir = path.dirname(outputPath);

const artifactToolModuleRoot = process.env.CODEX_WORKSPACE_NODE_MODULES;
const artifactToolSpecifier = artifactToolModuleRoot
  ? pathToFileURL(
    path.join(
      artifactToolModuleRoot,
      "@oai/artifact-tool/dist/artifact_tool.mjs",
    ),
  ).href
  : "@oai/artifact-tool";
const { SpreadsheetFile, Workbook } = await import(artifactToolSpecifier);

const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const horses = data.horses;

const REGION_LABELS = {
  france: "法国",
  hong_kong: "中国香港",
  japan: "日本",
  united_kingdom: "英国",
  united_states: "美国",
};
const REGION_ORDER = [
  "france",
  "hong_kong",
  "japan",
  "united_kingdom",
  "united_states",
];

const FIELD_DEFS = [
  ["identity", "original_name", "原始马名", "来源中的原始马名；暂无中文译名时必须保留原文", "非空且与已确认候选一致"],
  ["identity", "aliases", "多语别名", "同一匹马的其他语言、历史名或地区名", "至少保留原始名；有已知别名时一并列出"],
  ["identity", "external_horse_id", "来源马 ID", "主来源可稳定定位马匹的 ID", "非空；不能只依赖马名"],
  ["identity", "source_url", "马匹来源 URL", "可人工回看身份与资料的马匹页面", "非空且可定位到具体马或官方检索结果"],
  ["identity", "identity_key", "候选唯一身份键", "马名 + 父名 + 母名 + 出生年份", "四部分均有值；用于数据库内同名马消歧"],
  ["basic", "country", "产地/国家", "马匹出生国或官方 country of origin", "非空；不能拿参赛地区替代"],
  ["basic", "sex", "性别", "牡、牝、骟等来源值", "非空"],
  ["basic", "color", "毛色", "鹿毛、栗毛、芦毛等来源值", "非空"],
  ["basic", "birth_date", "出生日期", "完整出生年月日；不能用出生年份虚构日期", "完整日期为已获取；只有年份算部分获取"],
  ["basic", "owner_name", "马主", "来源页面显示的当前或该时间点马主", "非空，并保留来源原文"],
  ["basic", "trainer_name", "练马师", "来源页面显示的当前或该时间点练马师", "非空，并保留来源原文"],
  ["basic", "breeder_name", "育马者/生产者", "繁育该马的 breeder 或生产牧场", "非空"],
  ["pedigree", "sire", "父", "父马原始名", "非空"],
  ["pedigree", "dam", "母", "母马原始名", "非空"],
  ["pedigree", "sire_sire", "父父", "父马的父马", "非空"],
  ["pedigree", "sire_dam", "父母", "父马的母马", "非空"],
  ["pedigree", "dam_sire", "母父", "母马的父马", "非空"],
  ["pedigree", "dam_dam", "母母", "母马的母马", "非空"],
  ["career", "official_or_source_start_count", "官方/来源实际出赛总数", "官方或主来源明确声明的实际出赛总数；不含退赛/未出赛", "必须来自权威来源声明；备用页面可见行数推导不算完成"],
  ["career", "official_start_count_source", "总出赛数来源", "官方/来源总出赛数由哪个来源给出", "非空且能回溯来源"],
  ["career", "official_start_count_source_url", "总出赛数来源URL", "人工复核官方/来源总数的页面", "非空且可定位到马匹或来源记录"],
  ["career", "official_start_count_verified_at", "总出赛数核验时间", "本次确认官方/来源总数的时间", "非空；人工核验与自动采集均需记录"],
  ["career", "visible_source_record_count", "来源可见/已采集行数", "当前来源可见并解析到的逐场行数；不等于官方总数", "明确计数；不得冒充官方总出赛数"],
  ["career", "career_record_count", "履历记录数", "当前已保存的逐场记录总数，包含退赛/未出赛记录", "非空且可与来源总数、退赛数核对"],
  ["career", "collected_start_count", "已采集实际出赛数", "当前履历中被确认为实际出赛的记录数", "可复算，并与来源总数比较"],
  ["career", "missing_start_count", "缺少实际出赛数", "官方/来源实际出赛总数高于已采集实际出赛数的差额", "只记录缺少方向；0 也是有效值"],
  ["career", "excess_start_count", "多采/待去重数", "已采集实际出赛数高于官方/来源总数的差额", "只记录多采方向；大于 0 时必须继续去重或核查总数口径"],
  ["career", "nonstarter_count", "退赛/未出赛数", "scratched、withdrawn、WV、NR 等未实际出赛记录", "明确计数；0 也是有效值"],
  ["career", "abnormal_official_status_count", "正式异常结果数", "F/UR/BD/PU/arr/tbé/t.j 等实际出赛但未完赛或异常的正式结果数", "明确计数；finish_position 可空但必须计入实际出赛"],
  ["career", "overseas_start_count", "海外实际出赛数", "主地区以外、来源标记为 Overseas 的实际出赛记录数", "明确计数，并与本地记录跨来源去重"],
  ["career", "unknown_result_count", "结果状态未知数", "有比赛记录但尚不能确认完赛、退赛或异常结果状态的记录数", "明确计数；大于 0 表示结果状态仍不完整"],
  ["career", "gap_count", "数量差异数", "缺少实际出赛数与多采/待去重数之和；不表示单一方向", "必须同时查看缺少和多采两列，不能把多采写成缺失"],
  ["career", "record_authority_status", "逐场权威性状态", "逐场来源已核验、数量已对齐但逐场官方性待确认、来源受阻或未知", "数量相等不等于逐场官方性已确认"],
  ["career", "career_completeness", "生涯完整状态", "完整、存在缺口、结果状态待补或待官方总数核验", "必须同时看总数、逐场记录、退赛和异常状态"],
  ["career_detail", "race_date", "逐场日期", "每条生涯履历的比赛日期", "所有已采集记录均有日期"],
  ["career_detail", "race_name", "逐场赛事名", "每条生涯履历的比赛名称；普通比赛也应保留", "所有已采集记录均有赛事名"],
  ["career_detail", "racecourse", "逐场赛场", "每条履历的赛场或场地标识", "所有已采集记录均有赛场"],
  ["career_detail", "result_status", "逐场结果状态", "won/placed/unplaced/did_not_finish/disqualified/scratched/withdrawn/unknown 等", "所有记录均能判定；unknown 为部分获取"],
  ["career_detail", "result_evidence_status", "结果证据状态", "直接结果、来源原因映射、权威补证或仍待权威补查", "法国 N/A 不得直接等同于缺失或 unknown"],
  ["career_detail", "distance_text", "逐场距离", "来源原始距离文本", "所有已采集记录均有距离"],
  ["career_detail", "record_source_url", "逐场来源 URL", "每条履历的直接证据链接", "所有已采集记录均有 URL"],
];

const PROFILE_KEYS = [
  "country",
  "sex",
  "color",
  "birth_date",
  "owner_name",
  "trainer_name",
  "breeder_name",
];
const PEDIGREE_KEYS = [
  "sire",
  "dam",
  "sire_sire",
  "sire_dam",
  "dam_sire",
  "dam_dam",
];
const NONSTARTERS = new Set([
  "scr",
  "scratched",
  "wv",
  "withdrawn",
  "nr",
  "non runner",
]);

function text(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function unique(values) {
  return [...new Set(values.map(text).filter(Boolean))];
}

function aliasNames(horse) {
  const candidateAliases = (horse.candidate.aliases || []).map((item) =>
    typeof item === "string" ? item : item?.name,
  );
  const parsedAliases = (horse.aliases || []).map((item) =>
    typeof item === "string" ? item : item?.name,
  );
  return unique([horse.candidate.horse_name, ...candidateAliases, ...parsedAliases]);
}

function identityKey(horse) {
  const identity = horse.identity || {};
  return [
    horse.candidate.horse_name,
    identity.sire_name || horse.pedigree?.sire,
    identity.dam_name || horse.pedigree?.dam,
    identity.birth_year || text(horse.basic_profile?.birth_date).slice(0, 4),
  ]
    .map(text)
    .join(" | ");
}

function excelDate(value) {
  const raw = text(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  return new Date(`${raw}T00:00:00Z`);
}

function excelDateTime(value) {
  const raw = text(value);
  if (!raw) return "";
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? raw : parsed;
}

function displayDateTime(value) {
  const parsed = excelDateTime(value);
  if (!(parsed instanceof Date)) return parsed;
  return `${parsed.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

function normalized(value) {
  return text(value).toLowerCase().replace(/\s+/g, " ");
}

function recordStatus(record) {
  const explicit = normalized(record.result_status);
  const finish = normalized(record.finish || record.finish_position);
  const casualty = normalized(record.casualty);
  const startStatus = normalized(record.start_status);
  if (explicit === "finished") return "unplaced";
  if (explicit) return explicit;
  if (
    record.result_evidence_status === "requires_authoritative_supplement" ||
    finish === "n/a"
  ) {
    return "unknown";
  }
  if (startStatus === "not_started" || NONSTARTERS.has(finish)) {
    return finish === "scr" || finish === "scratched" ? "scratched" : "withdrawn";
  }
  if (casualty) return "did_not_finish";
  if (/^\d+$/.test(finish)) {
    const position = Number.parseInt(finish, 10);
    if (position === 1) return "won";
    if (position === 2 || position === 3) return "placed";
    return "unplaced";
  }
  if (finish) return "unplaced";
  return "unknown";
}

function actualStartLabel(record) {
  const status = recordStatus(record);
  return actualStartLabelFromStatuses({
    startStatus: normalized(record.start_status),
    resultStatus: status,
    resultEvidenceStatus: text(record.result_evidence_status),
  });
}

function careerStatus(horse) {
  return careerStatusLabel(horse);
}

function fieldValue(horse, key) {
  const basic = horse.basic_profile || {};
  const pedigree = horse.pedigree || {};
  const status = horse.field_status || {};
  const records = horse.career?.records || [];
  const source = horse.source || {};
  const values = {
    original_name: horse.candidate.horse_name,
    aliases: aliasNames(horse).join(" / "),
    external_horse_id: source.external_horse_id,
    source_url: source.url,
    identity_key: identityKey(horse),
    ...basic,
    ...pedigree,
    official_or_source_start_count: status.official_or_source_start_count,
    official_start_count_source: status.official_start_count_source,
    official_start_count_source_url: status.official_start_count_source_url,
    official_start_count_verified_at: status.official_start_count_verified_at,
    visible_source_record_count:
      horse.career?.visible_source_record_count ?? status.career_record_count,
    career_record_count: status.career_record_count,
    collected_start_count: status.collected_actual_start_count,
    missing_start_count: status.career_missing_start_count,
    excess_start_count: status.career_excess_start_count,
    nonstarter_count: status.nonstarter_record_count,
    abnormal_official_status_count: status.abnormal_official_status_count,
    overseas_start_count: status.overseas_start_count,
    unknown_result_count: status.unknown_record_count,
    gap_count: status.career_gap_count,
    record_authority_status: status.record_authority_status,
    career_completeness: careerStatus(horse),
    race_date: records.map((record) => text(record.race_date)),
    race_name: records.map((record) => text(record.race_name)),
    racecourse: records.map((record) => text(record.racecourse)),
    result_status: records.map(recordStatus),
    result_evidence_status: records.map(
      (record) =>
        text(record.result_evidence_status) ||
        (recordStatus(record) !== "unknown" ? "direct_source_record" : ""),
    ),
    distance_text: records.map((record) => text(record.distance_text)),
    record_source_url: records.map((record) => text(record.source_url)),
  };
  return values[key];
}

function fieldStatus(horse, field) {
  const [category, key] = field;
  const value = fieldValue(horse, key);
  const records = horse.career?.records || [];
  if (
    category === "pedigree" &&
    (horse.pedigree_field_evidence || []).some(
      (item) => item.field_name === key && item.status === "conflict",
    )
  ) {
    return "冲突阻断";
  }
  if (
    [
      "official_or_source_start_count",
      "missing_start_count",
      "excess_start_count",
      "gap_count",
    ].includes(key)
  ) {
    return ["source_declared", "source_reconciled", "official_verified"].includes(
      horse.career?.source_start_count_quality,
    )
      ? "已获取"
      : "待官方总数核验";
  }
  if (key === "career_completeness") {
    return careerStatus(horse) === "完整" ? "已获取" : "部分获取";
  }
  if (category === "career_detail") {
    if (!records.length) return "缺失";
    const values = Array.isArray(value) ? value : [];
    if (
      key === "result_status" &&
      records.some(
        (record) =>
          recordStatus(record) === "unknown" &&
          normalized(record.start_status) !== "did_not_start",
      )
    ) {
      return "部分获取";
    }
    const complete = values.length === records.length && values.every(Boolean);
    return complete ? "已获取" : values.some(Boolean) ? "部分获取" : "缺失";
  }
  if (key === "identity_key") {
    const basic = horse.basic_profile || {};
    const identity = horse.identity || {};
    const parts = [
      horse.candidate.horse_name,
      identity.sire_name || horse.pedigree?.sire,
      identity.dam_name || horse.pedigree?.dam,
      identity.birth_year || text(basic.birth_date).slice(0, 4),
    ];
    return parts.every((item) => text(item)) ? "已获取" : "部分获取";
  }
  if (value === 0) return "已获取";
  if (text(value)) return "已获取";
  if (
    horse.region === "united_states" &&
    (
      key === "color" ||
      key === "official_or_source_start_count" ||
      key === "official_start_count_verified_at" ||
      key === "missing_start_count" ||
      key === "excess_start_count" ||
      key === "gap_count"
    )
  ) {
    return "来源阻断";
  }
  return "缺失";
}

function evidenceNote(horse, field, status) {
  const [, key, label] = field;
  if (status === "已获取") return `${label}已从本批解析来源取得。`;
  if (status === "部分获取") {
    if (key === "result_status") {
      return `${horse.field_status.unknown_record_count} 场结果状态仍为 unknown。`;
    }
    return `${label}已有部分值，但未满足完整性规则。`;
  }
  if (status === "待官方总数核验" || status === "来源阻断") {
    return `${label}当前仅有备用来源可见行或被官方站点反自动化拦截，不能标记为完整。`;
  }
  return `${label}在当前来源未出现，需按地区补充来源。`;
}

function pedigreeFieldEvidence(horse, key) {
  const evidence = (horse.pedigree_field_evidence || []).filter(
    (item) => item.field_name === key,
  );
  return {
    verified: evidence.filter((item) => item.status !== "conflict").at(-1) || null,
    conflict: evidence.filter((item) => item.status === "conflict").at(-1) || null,
  };
}

function basicProfileFieldEvidence(horse, key) {
  return (
    (horse.basic_profile_field_evidence || []).filter(
      (item) => item.field_name === key,
    ).at(-1) || null
  );
}

function fieldEvidenceSource(horse, field) {
  const [category, key] = field;
  if (category === "basic") {
    const evidence = basicProfileFieldEvidence(horse, key);
    if (evidence) {
      return {
        name: evidence.source_name || horse.source?.name || "",
        url: evidence.source_url || horse.source?.url || "",
        level: evidence.status || "",
        method: evidence.verification_method || "",
        verifiedAt: evidence.verified_at || "",
        originalName: horse.source?.name || "",
        originalUrl: horse.source?.url || "",
        candidateValue: conflictCandidateValue(evidence),
        note: evidence.evidence_note || "",
      };
    }
  }
  if (category === "pedigree") {
    const { verified, conflict } = pedigreeFieldEvidence(horse, key);
    const evidence = conflict || verified;
    if (evidence) {
      return {
        name: evidence.source_name || horse.source?.name || "",
        url: evidence.source_url || horse.source?.url || "",
        level: evidence.status || "",
        method: evidence.verification_method || "",
        verifiedAt: evidence.verified_at || "",
        originalName: horse.source?.name || "",
        originalUrl: horse.source?.url || "",
        candidateValue: conflict?.source_value || "",
        note:
          (
            conflict
              ? `原值 ${fieldValue(horse, key) || ""} 与补充来源值 ${conflict.source_value || ""} 冲突，已阻断审核。`
              : evidence.evidence_note
          ) ||
          (
            evidence.verification_method === "exact_parent_name_and_known_sire_match"
              ? "通过母马实体反查，并用既有母父交叉确认同名身份。"
              : evidence.verification_method === "exact_parent_name_unique_match"
                ? "通过父马实体唯一精确同名候选反查其父母。"
                : "通过目标马或父母实体血统页人工核验。"
          ),
      };
    }
  }
  if (
    category === "career" &&
    [
      "official_or_source_start_count",
      "official_start_count_source",
      "official_start_count_source_url",
      "official_start_count_verified_at",
      "gap_count",
      "record_authority_status",
      "career_completeness",
    ].includes(key)
  ) {
    const evidence = (horse.source_evidence || []).find(
      (item) =>
        item.source_name === "equibase" &&
        item.evidence_role ===
          "identity_profile_color_and_official_start_count",
    );
    if (evidence) {
      return {
        name: evidence.source_name,
        url: evidence.source_url,
        level: "official_manual_verified",
        method: evidence.verification_method || "",
        verifiedAt: evidence.verified_at || "",
        originalName: horse.source?.name || "",
        originalUrl: horse.source?.url || "",
        candidateValue: "",
        note: evidence.evidence_note || "",
      };
    }
  }
  return {
    name: horse.source?.name || "",
    url: horse.source?.url || "",
    level: "direct_primary_source",
    method: "direct_profile_parse",
    verifiedAt: horse.source?.fetched_at || "",
    originalName: horse.source?.name || "",
    originalUrl: horse.source?.url || "",
    candidateValue: "",
    note: evidenceNote(horse, field, fieldStatus(horse, field)),
  };
}

const evidenceRows = [];
for (const horse of horses) {
  for (const field of FIELD_DEFS) {
    const [category, key, label] = field;
    const value = fieldValue(horse, key);
    const status = fieldStatus(horse, field);
    const displayValue = Array.isArray(value)
      ? `${value.filter(Boolean).length}/${value.length} 条有值`
      : key === "official_start_count_verified_at"
        ? displayDateTime(value)
        : value ?? "";
    const evidenceSource = fieldEvidenceSource(horse, field);
    evidenceRows.push([
      REGION_LABELS[horse.region],
      horse.candidate.horse_name,
      key,
      label,
      category,
      status,
      displayValue,
      evidenceSource.name,
      evidenceSource.url,
      evidenceSource.level,
      evidenceSource.method,
      excelDateTime(evidenceSource.verifiedAt),
      evidenceSource.originalName,
      evidenceSource.originalUrl,
      evidenceSource.candidateValue,
      evidenceSource.note,
      regionNextRoute(horse.region, key),
    ]);
  }
}

function recordFieldEvidence(record, fieldName) {
  return (
    (record.field_evidence || []).find(
      (item) => item.field_name === fieldName,
    ) || {}
  );
}

const careerRows = [];
const recordEvidenceRows = [];
for (const horse of horses) {
  (horse.career?.records || []).forEach((record, index) => {
    const resultEvidence = recordFieldEvidence(record, "result");
    const directResult =
      resultEvidence.direct_raw?.value ??
      record.direct_result_value ??
      record.finish ??
      record.finish_position ??
      "";
    const canonicalResult =
      resultEvidence.canonical_raw?.value ??
      (
        record.result_evidence_status === "canonical_verified"
          ? record.finish
          : ""
      );
    const normalizedResult = normalizedResultValue(
      resultEvidence,
      recordStatus(record),
    );
    careerRows.push([
      REGION_LABELS[horse.region],
      horse.candidate.horse_name,
      identityKey(horse),
      index + 1,
      excelDate(record.race_date),
      text(record.race_name),
      text(record.racecourse),
      text(record.distance_text),
      text(directResult),
      text(canonicalResult),
      text(normalizedResult),
      text(record.result_evidence_status || "direct_source_record"),
      actualStartLabel(record),
      record.is_overseas === true ? "是" : record.is_overseas === false ? "否" : "",
      text(record.external_race_id),
      text(record.external_result_id),
      text(record.source_name || horse.source?.name),
      text(record.source_url),
      (record.source_urls || [record.source_url])
        .map(text)
        .filter(Boolean)
        .filter((value, valueIndex, values) => values.indexOf(value) === valueIndex)
        .join("\n"),
      (record.source_record_names || [record.race_name])
        .map(text)
        .filter(Boolean)
        .filter((value, valueIndex, values) => values.indexOf(value) === valueIndex)
        .join(" / "),
      (record.corroborating_source_urls || [])
        .map(text)
        .filter(Boolean)
        .filter((value, valueIndex, values) => values.indexOf(value) === valueIndex)
        .join("\n"),
      text(resultEvidence.canonical_raw?.source_name),
      text(resultEvidence.canonical_raw?.source_url),
      text(resultEvidence.normalized?.conversion_rule),
    ]);
    for (const fieldEvidence of record.field_evidence || []) {
      const direct = fieldEvidence.direct_raw || {};
      const canonical = fieldEvidence.canonical_raw || {};
      const normalizedLayer = fieldEvidence.normalized || {};
      recordEvidenceRows.push([
        REGION_LABELS[horse.region],
        horse.candidate.horse_name,
        identityKey(horse),
        index + 1,
        excelDate(record.race_date),
        text(record.race_name),
        text(fieldEvidence.field_name),
        direct.value ?? "",
        text(direct.status),
        text(direct.source_name),
        text(direct.source_url),
        excelDateTime(direct.observed_at),
        text(direct.conversion_rule),
        canonical.value ?? "",
        text(canonical.status),
        text(canonical.source_name),
        text(canonical.source_url),
        excelDateTime(canonical.observed_at),
        text(canonical.conversion_rule),
        normalizedLayer.value ?? "",
        text(normalizedLayer.status),
        text(normalizedLayer.source_name),
        text(normalizedLayer.source_url),
        excelDateTime(normalizedLayer.observed_at),
        text(normalizedLayer.conversion_rule),
      ]);
    }
  });
}

const invalidUnplacedRows = careerRows.filter((row) => {
  const rawPosition = text(row[8]);
  const position = /^\d+$/.test(rawPosition)
    ? Number.parseInt(rawPosition, 10)
    : null;
  return position !== null && position >= 4 && row[10] !== "unplaced";
});
if (invalidUnplacedRows.length) {
  throw new Error(
    `${invalidUnplacedRows.length} fourth-or-lower finishes were not normalized as unplaced`,
  );
}

const totalRows = horses.map((horse) => {
  const basic = horse.basic_profile || {};
  const pedigree = horse.pedigree || {};
  const status = horse.field_status || {};
  return [
    REGION_LABELS[horse.region],
    horse.candidate.sample_rank,
    horse.candidate.horse_name,
    aliasNames(horse).join(" / "),
    identityKey(horse),
    horse.source?.name || "",
    horse.source?.external_horse_id || "",
    horse.source?.url || "",
    pedigree.sire || "",
    pedigree.dam || "",
    horse.identity?.birth_year || text(basic.birth_date).slice(0, 4),
    basic.country || "",
    basic.sex || "",
    basic.color || "",
    excelDate(basic.birth_date),
    basic.owner_name || "",
    basic.trainer_name || "",
    basic.breeder_name || "",
    pedigree.sire_sire || "",
    pedigree.sire_dam || "",
    pedigree.dam_sire || "",
    pedigree.dam_dam || "",
    status.official_or_source_start_count ?? "",
    status.official_start_count_source ?? "",
    status.official_start_count_source_url ?? "",
    excelDateTime(status.official_start_count_verified_at),
    horse.career?.visible_source_record_count ?? status.career_record_count ?? "",
    status.career_record_count ?? "",
    status.collected_actual_start_count ?? "",
    status.career_missing_start_count ?? "",
    status.career_excess_start_count ?? "",
    status.nonstarter_record_count ?? "",
    status.abnormal_official_status_count ?? "",
    status.overseas_start_count ?? "",
    status.unknown_record_count ?? "",
    status.career_gap_count ?? "",
    status.record_authority_status ?? "",
    careerStatus(horse),
    (status.missing_basic_profile_fields || []).join(", "),
    (status.missing_pedigree_fields || []).join(", "),
    horse.research_error || "",
    horse.candidate.evidence_count,
    horse.candidate.latest_event_name,
    horse.candidate.latest_event_grade,
  ];
});

const regionSummary = REGION_ORDER.map((region) => {
  const group = horses.filter((horse) => horse.region === region);
  const hardFields = FIELD_DEFS.filter(([category]) =>
    ["basic", "pedigree"].includes(category),
  );
  const acquired = group.reduce(
    (sum, horse) =>
      sum +
      hardFields.filter((field) => fieldStatus(horse, field) === "已获取").length,
    0,
  );
  const statusTotal = (key) => group.reduce(
    (sum, horse) => sum + (horse.field_status?.[key] || 0),
    0,
  );
  const hardFieldTotal = group.length * hardFields.length;
  const careerRecordCount = statusTotal("career_record_count");
  const actualStartCount = statusTotal("collected_actual_start_count");
  const nonstarterCount = statusTotal("nonstarter_record_count");
  const abnormalResultCount = statusTotal("abnormal_official_status_count");
  const overseasStartCount = statusTotal("overseas_start_count");
  const unknownRecordCount = statusTotal("unknown_record_count");
  const careerMissingStartCount = statusTotal("career_missing_start_count");
  const careerExcessStartCount = statusTotal("career_excess_start_count");
  const careerComplete = group.length > 0
    && group.every((horse) => careerStatus(horse) === "完整");
  const conclusion = regionSummaryConclusion(region, group, {
    hardFieldAcquired: acquired,
    hardFieldTotal,
    careerMissingStartCount,
    careerExcessStartCount,
    unknownRecordCount,
    careerComplete,
  });
  return [
    REGION_LABELS[region],
    group.length,
    acquired,
    hardFieldTotal,
    careerRecordCount,
    actualStartCount,
    nonstarterCount,
    abnormalResultCount,
    overseasStartCount,
    unknownRecordCount,
    careerMissingStartCount,
    careerExcessStartCount,
    conclusion,
  ];
});

const sourceResearchRows = buildSourceResearchRows(horses);
const batchMetadata = workbookBatchMetadata(horses);
const totalSheetName = batchMetadata.totalSheetName;

const workbook = Workbook.create();
const summarySheet = workbook.worksheets.add("结论与说明");
const matrixSheet = workbook.worksheets.add("地区字段矩阵");
const totalSheet = workbook.worksheets.add(totalSheetName);
const evidenceSheet = workbook.worksheets.add("逐字段证据");
const careerSheet = workbook.worksheets.add("逐场履历");
const recordEvidenceSheet = workbook.worksheets.add("逐场字段证据");
const researchSheet = workbook.worksheets.add("来源调研");
const dictionarySheet = workbook.worksheets.add("字段字典");

const COLORS = {
  navy: "#17324D",
  teal: "#176B67",
  green: "#DDEFE7",
  amber: "#FFF0C7",
  red: "#FCE0DE",
  blue: "#DCEAF5",
  gray: "#F3F5F7",
  line: "#D4DCE3",
  white: "#FFFFFF",
  text: "#1F2933",
};

function colName(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function writeTable(sheet, startRow, headers, rows, tableName) {
  const lastCol = colName(headers.length - 1);
  const lastRow = startRow + rows.length;
  sheet.getRange(`A${startRow}:${lastCol}${lastRow}`).values = [headers, ...rows];
  const table = sheet.tables.add(`A${startRow}:${lastCol}${lastRow}`, true, tableName);
  table.style = "TableStyleMedium2";
  table.showBandedColumns = false;
  table.showFilterButton = true;
  return { lastCol, lastRow };
}

function styleTitle(sheet, range, title) {
  sheet.getRange(range).merge();
  sheet.getRange(range).values = [[title]];
  sheet.getRange(range).format = {
    fill: COLORS.navy,
    font: { bold: true, color: COLORS.white, size: 18 },
    verticalAlignment: "center",
    horizontalAlignment: "left",
  };
}

function styleHeader(sheet, range) {
  sheet.getRange(range).format = {
    fill: COLORS.teal,
    font: { bold: true, color: COLORS.white },
    verticalAlignment: "center",
    horizontalAlignment: "center",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: COLORS.line },
  };
}

function styleUsed(sheet) {
  const used = sheet.getUsedRange();
  used.format.verticalAlignment = "top";
  sheet.showGridLines = false;
}

styleTitle(summarySheet, "A1:M1", batchMetadata.summaryTitle);
summarySheet.getRange("A2:M2").merge();
summarySheet.getRange("A2:M2").values = [[
  `原始解析时间：${data.generated_at}｜血统补证核验时间：${data.pedigree_research?.verified_at || ""}｜人工证据应用：${data.manual_evidence_application?.applied_at || ""}｜证据批次：${text(data.manual_evidence_application?.application_id).slice(0, 12)}｜${batchMetadata.scopeStatement}｜只做研究与人工审核，不写生产数据库`,
]];
summarySheet.getRange("A2:M2").format = {
  fill: COLORS.blue,
  font: { color: COLORS.navy },
  wrapText: true,
};
summarySheet.getRange("A4:M4").values = [[
  "地区",
  "样本数",
  "13项硬字段已获取",
  "13项硬字段总格数",
  "履历记录数",
  "实际出赛数",
  "退赛/未出赛",
  "正式异常结果",
  "海外实际出赛",
  "结果状态未知",
  "缺少实际出赛",
  "多采/待去重",
  "结论",
]];
summarySheet.getRange("A5:M9").values = regionSummary;
summarySheet.getRange("A5:M9").format.wrapText = true;
styleHeader(summarySheet, "A4:M4");
summarySheet.getRange("A11:M11").merge();
summarySheet.getRange("A11:M11").values = [["本批明确结论"]];
summarySheet.getRange("A11:M11").format = {
  fill: COLORS.teal,
  font: { bold: true, color: COLORS.white },
};
const pedigreeConclusion =
  `${pedigreeCompletionStatement(horses)}：` +
  `${Math.max(
    (data.pedigree_research?.filled_field_count || 0)
      - (
        data.parent_identity_review_application
          ?.filled_field_review_count
        || 0
      ),
    0,
  )} 个字段由已有强身份自动反查，` +
  `${data.parent_identity_review_application?.filled_field_review_count || 0} 个补入字段及 ` +
  `${Math.max(
    (data.parent_identity_review_application?.row_count || 0)
      - (
        data.parent_identity_review_application
          ?.filled_field_review_count
        || 0
      ),
    0,
  )} 条既有字段确认经项目负责人审核并绑定父母马来源 ID，` +
  `${data.pedigree_research?.manual_filled_field_count || 0} 个歧义/未命中字段由人工证据补齐；` +
  "字段级 URL 和证据等级均已落表。其他缺失仍按 missing/partial/source_blocked/parser_gap 保留，不猜值。";
const japanHorses = horses.filter((horse) => horse.region === "japan");
const japanSummary = regionSummary.find((row) => row[0] === REGION_LABELS.japan);
const japanConclusion = japanBatchConclusion(japanHorses, {
  hardFieldAcquired: japanSummary[2],
  hardFieldTotal: japanSummary[3],
  recordCount: japanSummary[4],
  actualStartCount: japanSummary[5],
  nonstarterCount: japanSummary[6],
  knownGap: japanSummary[10],
  knownExcess: japanSummary[11],
  careerComplete: japanHorses.every((horse) => careerStatus(horse) === "完整"),
});
const [
  franceCareerConclusion,
  hongKongCareerConclusion,
  unitedKingdomAndUnitedStatesCareerConclusion,
] = careerConclusionRows(horses);
summarySheet.getRange("A12:M16").values = [
  ["1", japanConclusion, ...Array(11).fill("")],
  ["2", franceCareerConclusion, ...Array(11).fill("")],
  ["3", hongKongCareerConclusion, ...Array(11).fill("")],
  [
    "4",
    unitedKingdomAndUnitedStatesCareerConclusion,
    ...Array(11).fill(""),
  ],
  ["5", pedigreeConclusion, ...Array(11).fill("")],
];
for (let row = 12; row <= 16; row += 1) {
  summarySheet.getRange(`B${row}:M${row}`).merge();
}
summarySheet.getRange("A12:M16").format = {
  fill: COLORS.gray,
  wrapText: true,
  borders: { preset: "inside", style: "thin", color: COLORS.line },
};
summarySheet.getRange("A18:M18").merge();
summarySheet.getRange("A18:M18").values = [["状态说明"]];
summarySheet.getRange("A18:M18").format = {
  fill: COLORS.teal,
  font: { bold: true, color: COLORS.white },
};
summarySheet.getRange("A19:M24").values = [
  ["已获取", "字段值存在并满足完整性规则。", ...Array(11).fill("")],
  ["部分获取", "已有部分值或数量已对齐，但结果语义或逐场官方性仍未满足完整规则。", ...Array(11).fill("")],
  ["待官方总数核验", "备用来源有逐场行，但没有权威来源总数，因此数量差异未知。", ...Array(11).fill("")],
  ["来源阻断", "目标官方页面存在，但自动访问受阻或许可条款不允许生产爬取。", ...Array(11).fill("")],
  ["冲突阻断", "字段原值与补充来源值冲突；保留双方证据，人工裁决前不得标记为已获取。", ...Array(11).fill("")],
  ["缺失", "当前来源未提供该字段；工作簿列出下一来源和查询方法。", ...Array(11).fill("")],
];
for (let row = 19; row <= 24; row += 1) {
  summarySheet.getRange(`B${row}:M${row}`).merge();
}
summarySheet.getRange("A19:M24").format = {
  wrapText: true,
  borders: { preset: "inside", style: "thin", color: COLORS.line },
};
summarySheet.getRange("A19:A19").format.fill = COLORS.green;
summarySheet.getRange("A20:A20").format.fill = COLORS.amber;
summarySheet.getRange("A21:A22").format.fill = COLORS.blue;
summarySheet.getRange("A23:A24").format.fill = COLORS.red;
summarySheet.freezePanes.freezeRows(4);
summarySheet.getRange("A1:M24").format.rowHeight = 22;
summarySheet.getRange("A1:M1").format.rowHeight = 34;
summarySheet.getRange("A5:M9").format.rowHeight = 72;
summarySheet.getRange("A12:M16").format.rowHeight = 48;
summarySheet.getRange("A:A").format.columnWidth = 15;
summarySheet.getRange("B:L").format.columnWidth = 14;
summarySheet.getRange("M:M").format.columnWidth = 58;

const matrixHeaders = [
  "地区",
  "类别",
  "字段键",
  "字段中文名",
  "已获取匹数",
  "部分获取匹数",
  "待核验/阻断匹数",
  "缺失匹数",
  "样本总数",
  "地区字段状态",
  "当前来源",
  "缺口说明",
  "下一获取路径",
];
const matrixRows = [];
for (const region of REGION_ORDER) {
  const sourcePolicy = regionSourcePolicy(region);
  for (const field of FIELD_DEFS) {
    matrixRows.push([
      REGION_LABELS[region],
      field[0],
      field[1],
      field[2],
      null,
      null,
      null,
      null,
      null,
      null,
      sourcePolicy.current,
      field[4],
      regionNextRoute(region, field[1]),
    ]);
  }
}
const matrixRange = writeTable(matrixSheet, 1, matrixHeaders, matrixRows, "RegionFieldMatrix");
const evidenceEnd = evidenceRows.length + 1;
for (let row = 2; row <= matrixRange.lastRow; row += 1) {
  matrixSheet.getRange(`E${row}:J${row}`).formulas = [[
    `=COUNTIFS('逐字段证据'!$A$2:$A$${evidenceEnd},A${row},'逐字段证据'!$C$2:$C$${evidenceEnd},C${row},'逐字段证据'!$F$2:$F$${evidenceEnd},"已获取")`,
    `=COUNTIFS('逐字段证据'!$A$2:$A$${evidenceEnd},A${row},'逐字段证据'!$C$2:$C$${evidenceEnd},C${row},'逐字段证据'!$F$2:$F$${evidenceEnd},"部分获取")`,
    `=COUNTIFS('逐字段证据'!$A$2:$A$${evidenceEnd},A${row},'逐字段证据'!$C$2:$C$${evidenceEnd},C${row},'逐字段证据'!$F$2:$F$${evidenceEnd},"待官方总数核验")+COUNTIFS('逐字段证据'!$A$2:$A$${evidenceEnd},A${row},'逐字段证据'!$C$2:$C$${evidenceEnd},C${row},'逐字段证据'!$F$2:$F$${evidenceEnd},"来源阻断")+COUNTIFS('逐字段证据'!$A$2:$A$${evidenceEnd},A${row},'逐字段证据'!$C$2:$C$${evidenceEnd},C${row},'逐字段证据'!$F$2:$F$${evidenceEnd},"冲突阻断")`,
    `=COUNTIFS('逐字段证据'!$A$2:$A$${evidenceEnd},A${row},'逐字段证据'!$C$2:$C$${evidenceEnd},C${row},'逐字段证据'!$F$2:$F$${evidenceEnd},"缺失")`,
    `=SUM(E${row}:H${row})`,
    `=IF(I${row}=0,"当前输入无样本",IF(E${row}=I${row},"可正常获取",IF(E${row}=0,IF(F${row}+G${row}>0,"当前不可完整获取","未获取"),"部分可获取")))`,
  ]];
}
styleHeader(matrixSheet, `A1:${matrixRange.lastCol}1`);
matrixSheet.freezePanes.freezeRows(1);
matrixSheet.freezePanes.freezeColumns(4);
matrixSheet.getRange(`A2:${matrixRange.lastCol}${matrixRange.lastRow}`).format.rowHeight = 56;
matrixSheet.getRange("A:A").format.columnWidth = 13;
matrixSheet.getRange("B:D").format.columnWidth = 17;
matrixSheet.getRange("E:J").format.columnWidth = 14;
matrixSheet.getRange("K:K").format.columnWidth = 34;
matrixSheet.getRange("L:M").format.columnWidth = 44;
matrixSheet.getRange(`A1:${matrixRange.lastCol}${matrixRange.lastRow}`).format.wrapText = true;

const totalHeaders = [
  "地区",
  "地区内排名",
  "原始马名",
  "多语别名",
  "候选身份键（马名|父|母|出生年）",
  "主解析来源",
  "来源马ID",
  "主来源URL",
  "父",
  "母",
  "出生年份",
  "产地/国家",
  "性别",
  "毛色",
  "出生日期",
  "马主",
  "练马师",
  "育马者/生产者",
  "父父",
  "父母",
  "母父",
  "母母",
  "官方/来源实际出赛总数",
  "总出赛数来源",
  "总出赛数来源URL",
  "总出赛数核验时间",
  "来源可见/已采集行数",
  "履历记录数",
  "已采集实际出赛",
  "缺少实际出赛",
  "多采/待去重",
  "退赛/未出赛",
  "正式异常结果",
  "海外实际出赛",
  "结果状态未知",
  "数量差异",
  "逐场权威性状态",
  "生涯完整状态",
  "缺失基础字段",
  "缺失血统字段",
  "研究错误",
  "候选赛事证据数",
  "候选最近赛事",
  "候选赛事级别",
];
const totalRange = writeTable(totalSheet, 1, totalHeaders, totalRows, "HorseProfileSummary");
styleHeader(totalSheet, `A1:${totalRange.lastCol}1`);
totalSheet.freezePanes.freezeRows(1);
totalSheet.freezePanes.freezeColumns(3);
totalSheet.getRange(`A2:${totalRange.lastCol}${totalRange.lastRow}`).format.rowHeight = 34;
totalSheet.getRange(`A1:${totalRange.lastCol}${totalRange.lastRow}`).format.wrapText = true;
totalSheet.getRange("A:B").format.columnWidth = 13;
totalSheet.getRange("C:C").format.columnWidth = 22;
totalSheet.getRange("D:D").format.columnWidth = 30;
totalSheet.getRange("E:E").format.columnWidth = 52;
totalSheet.getRange("F:G").format.columnWidth = 18;
totalSheet.getRange("H:H").format.columnWidth = 52;
totalSheet.getRange("I:V").format.columnWidth = 20;
totalSheet.getRange("W:X").format.columnWidth = 18;
totalSheet.getRange("Y:Y").format.columnWidth = 52;
totalSheet.getRange("Z:AL").format.columnWidth = 18;
totalSheet.getRange("AM:AO").format.columnWidth = 28;
totalSheet.getRange("AP:AR").format.columnWidth = 20;
totalSheet.getRange(`O2:O${totalRange.lastRow}`).format.numberFormat = "yyyy-mm-dd";
totalSheet.getRange(`Z2:Z${totalRange.lastRow}`).format.numberFormat =
  "yyyy-mm-dd hh:mm:ss";
totalSheet.getRange(`B2:B${totalRange.lastRow}`).format.numberFormat = "0";
totalSheet.getRange(`W2:W${totalRange.lastRow}`).format.numberFormat = "0";
totalSheet.getRange(`AA2:AJ${totalRange.lastRow}`).format.numberFormat = "0";

const evidenceHeaders = [
  "地区",
  "原始马名",
  "字段键",
  "字段中文名",
  "类别",
  "获取状态",
  "解析值/覆盖数",
  "字段证据来源",
  "字段证据URL",
  "证据等级",
  "核验方式",
  "核验时间",
  "原始解析来源",
  "原始来源URL",
  "冲突候选值",
  "证据说明",
  "下一获取路径",
];
const evidenceRange = writeTable(
  evidenceSheet,
  1,
  evidenceHeaders,
  evidenceRows,
  "FieldEvidence",
);
styleHeader(evidenceSheet, `A1:${evidenceRange.lastCol}1`);
evidenceSheet.freezePanes.freezeRows(1);
evidenceSheet.freezePanes.freezeColumns(2);
evidenceSheet.getRange(`A1:${evidenceRange.lastCol}${evidenceRange.lastRow}`).format.wrapText = true;
evidenceSheet.getRange(`A2:${evidenceRange.lastCol}${evidenceRange.lastRow}`).format.rowHeight = 34;
evidenceSheet.getRange("A:A").format.columnWidth = 13;
evidenceSheet.getRange("B:B").format.columnWidth = 22;
evidenceSheet.getRange("C:F").format.columnWidth = 19;
evidenceSheet.getRange("G:G").format.columnWidth = 36;
evidenceSheet.getRange("H:H").format.columnWidth = 20;
evidenceSheet.getRange("I:I").format.columnWidth = 52;
evidenceSheet.getRange("J:L").format.columnWidth = 24;
evidenceSheet.getRange("M:M").format.columnWidth = 20;
evidenceSheet.getRange("N:N").format.columnWidth = 52;
evidenceSheet.getRange("O:O").format.columnWidth = 22;
evidenceSheet.getRange("P:Q").format.columnWidth = 48;
evidenceSheet
  .getRange(`L2:L${evidenceRange.lastRow}`)
  .format.numberFormat = "yyyy-mm-dd hh:mm:ss";

const careerHeaders = [
  "地区",
  "原始马名",
  "候选身份键",
  "履历序号",
  "比赛日期",
  "赛事名",
  "赛场",
  "距离",
  "直接原始结果",
  "权威标准原始结果",
  "内部归一化结果",
  "结果证据状态",
  "是否实际出赛",
  "是否海外",
  "外部赛事ID",
  "外部结果ID",
  "来源",
  "逐场来源URL",
  "全部来源URL",
  "合并前来源赛事名",
  "佐证URL",
  "权威结果来源",
  "权威结果来源URL",
  "归一化规则",
];
const careerRange = writeTable(careerSheet, 1, careerHeaders, careerRows, "CareerRecords");
styleHeader(careerSheet, `A1:${careerRange.lastCol}1`);
careerSheet.freezePanes.freezeRows(1);
careerSheet.freezePanes.freezeColumns(3);
careerSheet.getRange(`A1:${careerRange.lastCol}${careerRange.lastRow}`).format.wrapText = true;
careerSheet.getRange(`A2:${careerRange.lastCol}${careerRange.lastRow}`).format.rowHeight = 32;
careerSheet.getRange("A:A").format.columnWidth = 13;
careerSheet.getRange("B:B").format.columnWidth = 22;
careerSheet.getRange("C:C").format.columnWidth = 48;
careerSheet.getRange("D:E").format.columnWidth = 14;
careerSheet.getRange("F:F").format.columnWidth = 46;
careerSheet.getRange("G:N").format.columnWidth = 18;
careerSheet.getRange("O:Q").format.columnWidth = 17;
careerSheet.getRange("R:R").format.columnWidth = 56;
careerSheet.getRange("S:S").format.columnWidth = 60;
careerSheet.getRange("T:T").format.columnWidth = 38;
careerSheet.getRange("U:U").format.columnWidth = 60;
careerSheet.getRange("V:V").format.columnWidth = 20;
careerSheet.getRange("W:W").format.columnWidth = 56;
careerSheet.getRange("X:X").format.columnWidth = 34;
careerSheet.getRange(`E2:E${careerRange.lastRow}`).format.numberFormat = "yyyy-mm-dd";
careerSheet.getRange(`D2:D${careerRange.lastRow}`).format.numberFormat = "0";

const recordEvidenceHeaders = [
  "地区",
  "原始马名",
  "候选身份键",
  "履历序号",
  "比赛日期",
  "赛事名",
  "字段键",
  "直接原始值",
  "直接值状态",
  "直接值来源",
  "直接值来源URL",
  "直接值采集时间",
  "直接值规则",
  "权威标准原始值",
  "标准值状态",
  "标准值来源",
  "标准值来源URL",
  "标准值核验时间",
  "标准值规则",
  "内部归一化值",
  "归一化状态",
  "归一化来源",
  "归一化证据URL",
  "归一化时间",
  "归一化规则",
];
const recordEvidenceRange = writeTable(
  recordEvidenceSheet,
  1,
  recordEvidenceHeaders,
  recordEvidenceRows,
  "RecordFieldEvidence",
);
styleHeader(recordEvidenceSheet, `A1:${recordEvidenceRange.lastCol}1`);
recordEvidenceSheet.freezePanes.freezeRows(1);
recordEvidenceSheet.freezePanes.freezeColumns(3);
recordEvidenceSheet
  .getRange(`A1:${recordEvidenceRange.lastCol}${recordEvidenceRange.lastRow}`)
  .format.wrapText = true;
recordEvidenceSheet
  .getRange(`A2:${recordEvidenceRange.lastCol}${recordEvidenceRange.lastRow}`)
  .format.rowHeight = 38;
recordEvidenceSheet.getRange("A:B").format.columnWidth = 18;
recordEvidenceSheet.getRange("C:C").format.columnWidth = 48;
recordEvidenceSheet.getRange("D:G").format.columnWidth = 16;
recordEvidenceSheet.getRange("F:F").format.columnWidth = 44;
recordEvidenceSheet.getRange("H:J").format.columnWidth = 20;
recordEvidenceSheet.getRange("K:K").format.columnWidth = 52;
recordEvidenceSheet.getRange("L:M").format.columnWidth = 28;
recordEvidenceSheet.getRange("N:P").format.columnWidth = 20;
recordEvidenceSheet.getRange("Q:Q").format.columnWidth = 52;
recordEvidenceSheet.getRange("R:S").format.columnWidth = 28;
recordEvidenceSheet.getRange("T:V").format.columnWidth = 20;
recordEvidenceSheet.getRange("W:W").format.columnWidth = 52;
recordEvidenceSheet.getRange("X:Y").format.columnWidth = 30;
recordEvidenceSheet
  .getRange(`E2:E${recordEvidenceRange.lastRow}`)
  .format.numberFormat = "yyyy-mm-dd";
for (const column of ["L", "R", "X"]) {
  recordEvidenceSheet
    .getRange(`${column}2:${column}${recordEvidenceRange.lastRow}`)
    .format.numberFormat = "yyyy-mm-dd hh:mm:ss";
}

const researchHeaders = [
  "地区",
  "本批/目标来源",
  "已能获取",
  "仍缺失或不完整",
  "按马名继续获取的方法",
  "访问限制",
  "主来源URL",
  "补充来源URL",
  "建议",
];
const researchRange = writeTable(
  researchSheet,
  1,
  researchHeaders,
  sourceResearchRows,
  "SourceResearch",
);
styleHeader(researchSheet, `A1:${researchRange.lastCol}1`);
researchSheet.freezePanes.freezeRows(1);
researchSheet.getRange(`A1:${researchRange.lastCol}${researchRange.lastRow}`).format.wrapText = true;
researchSheet.getRange(`A2:${researchRange.lastCol}${researchRange.lastRow}`).format.rowHeight = 92;
researchSheet.getRange("A:A").format.columnWidth = 13;
researchSheet.getRange("B:B").format.columnWidth = 28;
researchSheet.getRange("C:F").format.columnWidth = 43;
researchSheet.getRange("G:H").format.columnWidth = 52;
researchSheet.getRange("I:I").format.columnWidth = 48;

const dictionaryHeaders = [
  "类别",
  "字段键",
  "字段中文名",
  "含义",
  "完整性判定",
  "值与状态注意事项",
];
const dictionaryRows = FIELD_DEFS.map(([category, key, label, meaning, rule]) => [
  category,
  key,
  label,
  meaning,
  rule,
  key === "country"
    ? "产地/国家不是赛事地区；进口马需保留官方出生国。"
    : key === "birth_date"
      ? "只知道年份时不得虚构 1 月 1 日。"
      : key === "official_or_source_start_count"
        ? batchMetadata.usCareerStartDictionaryNote
        : key === "record_authority_status"
          ? "数量对齐不等于逐场官方结果已确认；两种完整度必须分开。"
        : key === "career_record_count"
          ? "可能大于实际出赛数，因为退赛/未出赛也保留为记录。"
          : key === "result_status"
            ? "异常状态与是否实际出赛分开记录；PU/DNF 是实际出赛，WV/SCR 不是。"
            : key === "identity_key"
              ? "同名马必须比较父、母、出生年份；地区不能作为唯一联合主键的一部分。"
              : "空白表示来源未提供，不代表 0，也不自动代表解析错误。",
]);
const dictionaryRange = writeTable(
  dictionarySheet,
  1,
  dictionaryHeaders,
  dictionaryRows,
  "FieldDictionary",
);
styleHeader(dictionarySheet, `A1:${dictionaryRange.lastCol}1`);
dictionarySheet.freezePanes.freezeRows(1);
dictionarySheet.getRange(`A1:${dictionaryRange.lastCol}${dictionaryRange.lastRow}`).format.wrapText = true;
dictionarySheet.getRange(`A2:${dictionaryRange.lastCol}${dictionaryRange.lastRow}`).format.rowHeight = 50;
dictionarySheet.getRange("A:C").format.columnWidth = 20;
dictionarySheet.getRange("D:F").format.columnWidth = 52;

for (const sheet of [
  summarySheet,
  matrixSheet,
  totalSheet,
  evidenceSheet,
  careerSheet,
  recordEvidenceSheet,
  researchSheet,
  dictionarySheet,
]) {
  styleUsed(sheet);
}

for (const [sheet, statusColumn, lastRow] of [
  [matrixSheet, "J", matrixRange.lastRow],
  [evidenceSheet, "F", evidenceRange.lastRow],
]) {
  const range = sheet.getRange(`${statusColumn}2:${statusColumn}${lastRow}`);
  range.conditionalFormats.add("containsText", {
    text: "已获取",
    format: { fill: COLORS.green, font: { color: "#165A3A" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "部分",
    format: { fill: COLORS.amber, font: { color: "#7A4B00" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "阻断",
    format: { fill: COLORS.blue, font: { color: COLORS.navy } },
  });
  range.conditionalFormats.add("containsText", {
    text: "待官方",
    format: { fill: COLORS.blue, font: { color: COLORS.navy } },
  });
  range.conditionalFormats.add("containsText", {
    text: "缺失",
    format: { fill: COLORS.red, font: { color: "#8B2F2A" } },
  });
}

await fs.mkdir(previewDir, { recursive: true });
const previewSpecs = [
  ["结论与说明", "A1:M24"],
  ["地区字段矩阵", "A1:M34"],
  [totalSheetName, "A1:R14"],
  [totalSheetName, "S1:AR14"],
  ["逐字段证据", "A1:Q25"],
  ["逐场履历", "A1:X25"],
  ["逐场字段证据", "A1:Y25"],
  ["来源调研", "A1:I6"],
  ["字段字典", "A1:F32"],
];
for (let index = 0; index < previewSpecs.length; index += 1) {
  const [sheetName, range] = previewSpecs[index];
  const preview = await workbook.render({
    sheetName,
    range,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(previewDir, `${String(index + 1).padStart(2, "0")}-${sheetName}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const checks = [
  ["结论与说明", "A1:M24"],
  ["地区字段矩阵", "A1:M12"],
  [totalSheetName, "A1:AR6"],
  ["逐字段证据", "A1:Q8"],
  ["逐场履历", "A1:X8"],
  ["逐场字段证据", "A1:Y8"],
  ["来源调研", "A1:I6"],
  ["字段字典", "A1:F8"],
];
for (const [sheetName, range] of checks) {
  const inspection = await workbook.inspect({
    kind: "table",
    range: `${sheetName}!${range}`,
    include: "values,formulas",
    tableMaxRows: 8,
    tableMaxCols: 16,
    maxChars: 8000,
  });
  console.log(`INSPECT ${sheetName}\n${inspection.ndjson}`);
}
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(`FORMULA_ERRORS\n${formulaErrors.ndjson}`);

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(
  JSON.stringify({
    outputPath,
    horseCount: horses.length,
    evidenceRows: evidenceRows.length,
    careerRows: careerRows.length,
    recordEvidenceRows: recordEvidenceRows.length,
    previews: previewSpecs.length,
  }),
);
