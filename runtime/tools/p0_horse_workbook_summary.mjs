const PEDIGREE_FIELDS = [
  "sire",
  "dam",
  "sire_sire",
  "sire_dam",
  "dam_sire",
  "dam_dam",
];

const WORKBOOK_REGIONS = [
  { region: "france", label: "法国" },
  { region: "hong_kong", label: "中国香港" },
  { region: "japan", label: "日本" },
  { region: "united_kingdom", label: "英国" },
  { region: "united_states", label: "美国" },
];

const CHINESE_COUNT_LABELS = [
  "零",
  "一",
  "二",
  "三",
  "四",
  "五",
];

const REGION_SOURCE_POLICIES = {
  france: {
    current:
      "Sporting Life 履历 + France Galop 结果补证 + " +
      "France-Sire/France Galop 基础资料与血统补证",
    currentUrl: "https://www.sportinglife.com/racing/profiles/horse",
    next:
      "France Galop / IFCE SIRE 优先；" +
      "Sporting Life 仅作定位与直接展示证据",
    nextUrl:
      "https://www.ifce.fr/ifce/sire-demarches/donnees-sire/" +
      "listes-de-chevaux/",
  },
  hong_kong: {
    current:
      "HKJC 马匹资料与完整赛绩表 + 原产地血统/赛事来源基础资料补证 + " +
      "netkeiba 父母实体反查",
    currentUrl:
      "https://racing.hkjc.com/en-us/local/information/selecthorse",
    next:
      "按产地转入官方 Stud Book；澳洲马优先 Australian Stud Book，" +
      "英爱马转 Weatherbys/BHA",
    nextUrl: "https://studbook.org.au/General.aspx",
  },
  japan: {
    current: "JBIS 马匹资料、血统与竞走成绩",
    currentUrl: "https://www.jbis.or.jp/horse/",
    next:
      "优先回查 JBIS profile/record；仍有缺口时转人工官方来源核验，" +
      "并持续保留来源 ID 与逐场 URL",
    nextUrl: "https://www.jbis.or.jp/jbis_hp/english/",
  },
  united_kingdom: {
    current:
      "Sporting Life Full Form + Irish Racing/Racing Post/France Galop " +
      "基础资料补证 + 血统页补证",
    currentUrl: "https://www.sportinglife.com/racing/profiles/horse",
    next:
      "BHA Horse Search / Weatherbys / Racing Post " +
      "补育马者、产地与完整三代血统",
    nextUrl: "https://www.britishhorseracing.com/racing/horses/",
  },
  united_states: {
    current:
      "Equibase 核验身份、毛色与总数 + HRN 去重逐场履历 + " +
      "其他结果页补证 + 血统补证",
    currentUrl: "https://www.equibase.com/profiles/Results.cfm",
    next:
      "以 Equibase/Equineline/TrackMaster 授权数据或人工 " +
      "Full Charts/Lifetime PP 核验逐场官方性",
    nextUrl: "https://www.equibase.com/profiles/Results.cfm",
  },
};

export function regionSourcePolicy(region) {
  return {
    current: "",
    currentUrl: "",
    next: "",
    nextUrl: "",
    ...(REGION_SOURCE_POLICIES[region] || {}),
  };
}

export function regionNextRoute(region, key) {
  if (region === "japan") {
    return (
      "优先回查 JBIS profile/record；仍有缺口时转人工官方来源核验，" +
      "并保留来源 ID 与逐场证据。"
    );
  }
  if (region === "hong_kong") {
    if (
      ["birth_date", "breeder_name", "sire_sire", "sire_dam", "dam_dam"]
        .includes(key)
    ) {
      return (
        "按 HKJC 产地值进入对应官方 Stud Book；" +
        "以马名+父+母+出生年消歧。"
      );
    }
    if (
      key.startsWith("career")
      || key.startsWith("race")
      || key === "result_status"
    ) {
      return "用 HKJC 海外赛绩/原产地赛绩补齐已知缺口，不强建 RaceEvent。";
    }
  }
  if (region === "france") {
    if (
      ["country", "breeder_name", "sire_sire", "sire_dam", "dam_dam"]
        .includes(key)
    ) {
      return (
        "IFCE SIRE/France Galop Stud Book 为长期方案，" +
        "Racing Post 结果页可作人工补充。"
      );
    }
    return "Sporting Life 继续提供履历；对旧记录补抓结果状态。";
  }
  if (region === "united_kingdom") {
    if (
      ["country", "breeder_name", "sire_sire", "sire_dam", "dam_dam"]
        .includes(key)
    ) {
      return "BHA/Weatherbys/Racing Post 补充，并用身份键校验。";
    }
    return "Sporting Life 继续提供履历；对旧记录补抓结果状态。";
  }
  if (region === "united_states") {
    return (
      "以 Equibase profile/API 核验官方总数与逐场结果；" +
      "HRN 只在父母名和出生年匹配后作备用。"
    );
  }
  return regionSourcePolicy(region).next;
}

export function workbookBatchMetadata(horses) {
  const regionCounts = WORKBOOK_REGIONS.flatMap(({ region, label }) => {
    const count = horses.filter((horse) => horse.region === region).length;
    return count ? [{ region, label, count }] : [];
  });
  const regionCountLabel =
    CHINESE_COUNT_LABELS[regionCounts.length] || String(regionCounts.length);
  const isUniformBatch =
    regionCounts.length > 1
    && regionCounts.every((item) => item.count === regionCounts[0].count);
  const scopeDetails = isUniformBatch
    ? `${regionCounts.map((item) => item.label).join("、")}各 ` +
      `${regionCounts[0].count} 匹`
    : regionCounts
      .map((item) => `${item.label} ${item.count} 匹`)
      .join("、");
  const usHorses = horses.filter(
    (horse) => horse.region === "united_states",
  );
  const usOfficialStartCountVerifiedCount = usHorses.filter(
    (horse) =>
      horse.career?.source_start_count_quality === "official_verified",
  ).length;
  const dictionaryPolicy =
    "HRN 行数仍只是备用逐场记录，数量对齐不代表逐场官方性已确认。";
  const usCareerStartDictionaryNote = usHorses.length === 0
    ? `当前输入无美国样本；${dictionaryPolicy}`
    : usOfficialStartCountVerifiedCount === usHorses.length
      ? (
        `美国 ${usHorses.length} 匹 Equibase Career Starts 均已人工核验；` +
        dictionaryPolicy
      )
      : (
        `美国 ${usHorses.length} 匹中 ` +
        `${usOfficialStartCountVerifiedCount} 匹 Equibase Career Starts 已核验；` +
        dictionaryPolicy
      );
  return {
    totalHorseCount: horses.length,
    regionCounts,
    usHorseCount: usHorses.length,
    usOfficialStartCountVerifiedCount,
    summaryTitle:
      `P0 马${regionCountLabel}地区 ${horses.length} 匹完整解析与字段可用性审核`,
    scopeStatement: regionCounts.length
      ? `范围：${scopeDetails}`
      : "范围：当前输入无样本",
    totalSheetName: `${horses.length}匹资料总表`,
    usCareerStartDictionaryNote,
  };
}

export function actualStartLabelFromStatuses({
  startStatus,
  resultStatus,
  resultEvidenceStatus,
}) {
  if (startStatus === "did_not_start") return "未实际出赛";
  if (resultStatus === "scratched" || resultStatus === "withdrawn") {
    return "未实际出赛";
  }
  if (startStatus === "started") {
    if (
      resultStatus === "unknown" &&
      resultEvidenceStatus === "requires_authoritative_supplement"
    ) {
      return "实际出赛（结果待补）";
    }
    if (resultStatus === "unknown") return "实际出赛（结果待确认）";
    return "实际出赛";
  }
  if (resultStatus === "unknown") return "待确认";
  return "实际出赛";
}

export function normalizedResultValue(resultEvidence, fallbackValue) {
  const normalized = resultEvidence?.normalized;
  if (normalized?.status === "not_applicable") return "";
  const value = normalized?.value != null
    ? normalized.value
    : fallbackValue;
  if (
    typeof value === "string"
    && value.trim().toLowerCase() === "finished"
  ) {
    return "unplaced";
  }
  return value;
}

export function conflictCandidateValue(evidence) {
  if (evidence?.status !== "conflict") return "";
  return evidence.source_value || evidence.direct_raw_value || "";
}

export function pedigreeConflictCount(horses) {
  return horses.reduce(
    (sum, horse) =>
      sum +
      (horse.pedigree_field_evidence || []).filter(
        (item) =>
          PEDIGREE_FIELDS.includes(item.field_name) &&
          item.status === "conflict",
      ).length,
    0,
  );
}

function completePedigreeHorseCount(horses) {
  return horses.filter((horse) => {
    const pedigree = horse.pedigree || {};
    const conflictedFields = new Set(
      (horse.pedigree_field_evidence || [])
        .filter((item) => item.status === "conflict")
        .map((item) => item.field_name),
    );
    return PEDIGREE_FIELDS.every(
      (fieldName) => pedigree[fieldName] && !conflictedFields.has(fieldName),
    );
  }).length;
}

export function regionPedigreeStatement(horses) {
  if (!horses.length) return "当前输入无样本";

  const completeCount = completePedigreeHorseCount(horses);
  const conflictCount = pedigreeConflictCount(horses);
  if (conflictCount) {
    return `三代血统 ${completeCount}/${horses.length}，${conflictCount} 个冲突阻断`;
  }
  return `三代血统 ${completeCount}/${horses.length}`;
}

export function regionSummaryConclusion(
  region,
  horses,
  {
    hardFieldAcquired,
    hardFieldTotal,
    careerMissingStartCount,
    careerExcessStartCount,
    unknownRecordCount,
    careerComplete,
  },
) {
  if (!horses.length) return "当前输入无样本";

  const pedigreeStatement = regionPedigreeStatement(horses);
  const hardFieldGapCount = Math.max(
    hardFieldTotal - hardFieldAcquired,
    0,
  );
  const pedigreeComplete =
    completePedigreeHorseCount(horses) === horses.length
    && pedigreeConflictCount(horses) === 0;
  const issues = [];
  if (hardFieldTotal <= 0) {
    issues.push("硬字段总格数未配置");
  } else if (hardFieldGapCount) {
    issues.push(`${hardFieldGapCount} 个硬字段格未获取`);
  }
  if (!pedigreeComplete) issues.push("血统完整性未满足");
  if (careerMissingStartCount) {
    issues.push(`缺少 ${careerMissingStartCount} 场`);
  }
  if (careerExcessStartCount) {
    issues.push(`多采 ${careerExcessStartCount} 场`);
  }
  if (unknownRecordCount) {
    issues.push(`${unknownRecordCount} 场结果状态待确认`);
  }
  if (!careerComplete) issues.push("生涯完整状态未满足");

  const statusStatement = issues.length
    ? `当前仍有${issues.join("、")}`
    : "当前硬字段、血统与履历状态完整";
  const usStatement = region === "united_states"
    ? `；${unitedStatesCareerStatement(horses)}`
    : "";
  return (
    `${hardFieldAcquired}/${hardFieldTotal} 个硬字段格已获取；` +
    `${pedigreeStatement}；${statusStatement}${usStatement}`
  );
}

export function pedigreeCompletionStatement(horses) {
  if (!horses.length) return "当前输入无样本";

  const completeCount = completePedigreeHorseCount(horses);
  const conflictCount = pedigreeConflictCount(horses);
  if (completeCount === horses.length && conflictCount === 0) {
    return `本批 ${horses.length} 匹的父、母、父父、父母、母父、母母已全部补齐`;
  }
  if (conflictCount === 0) {
    return (
      `本批 ${horses.length} 匹中 ${completeCount} 匹的六项三代血统通过完整性检查` +
      `，${horses.length - completeCount} 匹仍有血统字段缺失，不能声明全部补齐`
    );
  }
  return (
    `本批 ${horses.length} 匹中 ${completeCount} 匹的六项三代血统通过完整性检查` +
    `，存在 ${conflictCount} 个冲突阻断，不能声明全部补齐`
  );
}

export function japanBatchConclusion(
  horses,
  {
    hardFieldAcquired,
    hardFieldTotal,
    recordCount,
    actualStartCount,
    nonstarterCount,
    knownGap,
    knownExcess = 0,
    careerComplete,
  },
) {
  if (!horses.length) return "日本：当前输入无样本。";

  const pedigreeStatement = regionPedigreeStatement(horses);
  const isComplete =
    hardFieldAcquired === hardFieldTotal &&
    pedigreeConflictCount(horses) === 0 &&
    knownGap === 0 &&
    knownExcess === 0 &&
    careerComplete === true;
  const countDifferenceStatement = knownGap
    ? `缺少 ${knownGap} 场`
    : knownExcess
      ? `多采 ${knownExcess} 场，待去重`
      : "无数量差异";
  return (
    `日本${isComplete ? "达到" : "尚未达到"}本批完整标准：` +
    `${hardFieldAcquired}/${hardFieldTotal} 个基础/血统硬字段格已获取；` +
    `${pedigreeStatement}；${recordCount} 条记录中 ${actualStartCount} 次实际出赛、` +
    `${nonstarterCount} 次退赛/未出赛，来源总数${countDifferenceStatement}；` +
    `生涯完整状态${careerComplete ? "满足" : "未满足"}。`
  );
}

export function careerCountDifferenceStatement(horse) {
  const status = horse.field_status || {};
  const missing = status.career_missing_start_count;
  const excess = status.career_excess_start_count;
  if (Number.isInteger(missing) && missing > 0) {
    return `缺少 ${missing} 场`;
  }
  if (Number.isInteger(excess) && excess > 0) {
    return `多采 ${excess} 场，待去重`;
  }
  if (status.career_gap_count > 0) {
    return `数量相差 ${status.career_gap_count} 场，方向待确认`;
  }
  return "无数量差异";
}

export function careerStatusLabel(horse) {
  const status = horse.field_status || {};
  const quality = horse.career?.source_start_count_quality;
  const authority = horse.career?.record_authority_status;
  if (
    !["source_declared", "source_reconciled", "official_verified"].includes(
      quality,
    )
  ) {
    return authority === "source_blocked"
      ? "官方总数/逐场来源受阻"
      : "待官方总出赛数核验";
  }
  if (status.career_count_matches === false) {
    return `计数不一致（${careerCountDifferenceStatement(horse)}）`;
  }
  if (authority === "count_aligned_records_unverified") {
    return "数量已对齐、逐场官方性待确认";
  }
  if (authority !== "source_records_verified") {
    if (authority === "source_blocked") return "逐场权威来源受阻";
    if (!authority || authority === "unknown") return "逐场权威性待确认";
    return `逐场权威性状态异常（${authority}）`;
  }
  if ((status.career_gap_count || 0) > 0) {
    return careerCountDifferenceStatement(horse);
  }
  if ((status.unknown_record_count || 0) > 0) {
    return `计数完整，${status.unknown_record_count} 场结果状态待补`;
  }
  return "完整";
}

const NONSTART_FINISH_VALUES = new Set([
  "scr",
  "scratched",
  "w",
  "wv",
  "withdrawn",
  "nr",
  "non runner",
]);

function normalizedText(value) {
  return value == null
    ? ""
    : String(value).trim().toLowerCase().replace(/\s+/g, " ");
}

function horseName(horse) {
  return horse.candidate?.horse_name || horse.identity?.horse_name || "";
}

function recordsFor(horses) {
  return horses.flatMap((horse) => horse.career?.records || []);
}

function resultEvidence(record) {
  if (Array.isArray(record.field_evidence)) {
    return (
      record.field_evidence.find((item) => item.field_name === "result") || {}
    );
  }
  return record.field_evidence?.result || {};
}

function recordResultStatus(record) {
  const explicit = normalizedText(record.result_status);
  const finish = normalizedText(record.finish || record.finish_position);
  const casualty = normalizedText(record.casualty);
  const startStatus = normalizedText(record.start_status);
  if (explicit === "finished") return "unplaced";
  if (explicit) return explicit;
  if (
    record.result_evidence_status === "requires_authoritative_supplement"
    || finish === "n/a"
  ) {
    return "unknown";
  }
  if (
    ["did_not_start", "not_started"].includes(startStatus)
    || NONSTART_FINISH_VALUES.has(finish)
  ) {
    return ["scr", "scratched"].includes(finish)
      ? "scratched"
      : "withdrawn";
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

function recordStartKind(record) {
  const startStatus = normalizedText(record.start_status);
  const resultStatus = recordResultStatus(record);
  const finish = normalizedText(record.finish || record.finish_position);
  if (
    ["did_not_start", "not_started"].includes(startStatus)
    || ["scratched", "withdrawn", "did_not_start"].includes(resultStatus)
    || NONSTART_FINISH_VALUES.has(finish)
  ) {
    return "nonstart";
  }
  if (startStatus === "started" || resultStatus !== "unknown") return "start";
  return "unknown";
}

function legacyNaRecords(records) {
  return records.filter((record) => {
    const evidence = resultEvidence(record);
    const directValue =
      evidence.direct_raw?.value ?? record.direct_result_value;
    return normalizedText(directValue) === "n/a";
  });
}

function currentResultValue(record) {
  const evidence = resultEvidence(record);
  return (
    evidence.canonical_raw?.value
    ?? record.finish
    ?? record.finish_position
    ?? evidence.normalized?.value
    ?? ""
  );
}

function legacyNaBreakdown(records) {
  const oldNaRecords = legacyNaRecords(records);
  const positionCount = oldNaRecords.filter((record) =>
    /^\d+$/.test(normalizedText(currentResultValue(record))),
  ).length;
  const nonstarterCount = oldNaRecords.filter(
    (record) => recordStartKind(record) === "nonstart",
  ).length;
  const otherResolvedCount = oldNaRecords.filter((record) => {
    const currentValue = normalizedText(currentResultValue(record));
    return (
      recordStartKind(record) !== "nonstart"
      && !/^\d+$/.test(currentValue)
      && currentValue !== "n/a"
      && recordResultStatus(record) !== "unknown"
    );
  }).length;
  return {
    totalCount: oldNaRecords.length,
    positionCount,
    nonstarterCount,
    otherResolvedCount,
    unresolvedCount:
      oldNaRecords.length
      - positionCount
      - nonstarterCount
      - otherResolvedCount,
  };
}

function legacyNaResolutionStatement(records) {
  const breakdown = legacyNaBreakdown(records);
  if (!breakdown.totalCount) return "";
  if (
    breakdown.otherResolvedCount === 0
    && breakdown.unresolvedCount === 0
  ) {
    return (
      `${breakdown.totalCount} 条旧 N/A 已核验为 ` +
      `${breakdown.positionCount} 条正式名次和 ` +
      `${breakdown.nonstarterCount} 条未实际出赛`
    );
  }
  return (
    `${breakdown.totalCount} 条旧 N/A 中 ` +
    `${breakdown.positionCount} 条为正式名次、` +
    `${breakdown.nonstarterCount} 条为未实际出赛、` +
    `${breakdown.otherResolvedCount} 条为其他已核验结果、` +
    `${breakdown.unresolvedCount} 条仍待确认`
  );
}

function horseCountValue(horse, fieldStatusKey, careerKey) {
  const value =
    horse.field_status?.[fieldStatusKey] ?? horse.career?.[careerKey];
  return Number.isInteger(value) && value > 0 ? value : 0;
}

function regionalBatchGapStatement(horses, region, regionLabel) {
  const regionHorses = horses.filter((horse) => horse.region === region);
  if (!regionHorses.length) return `当前输入无${regionLabel}样本`;

  const hardFieldGapCount = regionHorses.reduce(
    (sum, horse) =>
      sum
      + (horse.field_status?.missing_basic_profile_fields || []).length
      + (horse.field_status?.missing_pedigree_fields || []).length,
    0,
  );
  const missingStartCount = regionHorses.reduce(
    (sum, horse) =>
      sum
      + horseCountValue(
        horse,
        "career_missing_start_count",
        "missing_start_count",
      ),
    0,
  );
  const excessStartCount = regionHorses.reduce(
    (sum, horse) =>
      sum
      + horseCountValue(
        horse,
        "career_excess_start_count",
        "excess_start_count",
      ),
    0,
  );
  const totalGapCount = regionHorses.reduce(
    (sum, horse) =>
      sum + horseCountValue(horse, "career_gap_count", "gap_count"),
    0,
  );
  const directionUnknownGapCount = Math.max(
    totalGapCount - missingStartCount - excessStartCount,
    0,
  );
  const unknownResultCount = regionHorses.reduce(
    (sum, horse) =>
      sum
      + horseCountValue(
        horse,
        "unknown_record_count",
        "unconfirmed_count",
      ),
    0,
  );
  const issues = [];
  if (hardFieldGapCount) issues.push(`${hardFieldGapCount} 个硬字段缺失`);
  if (missingStartCount) issues.push(`缺少 ${missingStartCount} 场`);
  if (excessStartCount) issues.push(`多采 ${excessStartCount} 场`);
  if (directionUnknownGapCount) {
    issues.push(`数量相差 ${directionUnknownGapCount} 场，方向待确认`);
  }
  if (unknownResultCount) {
    issues.push(`${unknownResultCount} 场结果状态待确认`);
  }
  return issues.length
    ? `本批存在${issues.join("、")}`
    : "本批未发现硬字段、履历数量或结果状态缺口";
}

function franceCareerConclusion(horses) {
  const franceHorses = horses.filter((horse) => horse.region === "france");
  if (!franceHorses.length) return "法国：当前输入无样本。";

  const oldNaRecords = legacyNaRecords(recordsFor(franceHorses));
  const resolvedCount = oldNaRecords.filter(
    (record) =>
      normalizedText(currentResultValue(record)) !== "n/a"
      && recordResultStatus(record) !== "unknown",
  ).length;
  const unresolvedCount = oldNaRecords.length - resolvedCount;
  const resolution = unresolvedCount === 0
    ? "已全部由逐场结果证据还原"
    : `已有 ${resolvedCount} 条由逐场结果证据还原，${unresolvedCount} 条仍待确认`;
  return (
    `法国 ${oldNaRecords.length} 条 Sporting Life N/A ${resolution}；` +
    "直接原始值、标准原始值、归一化值分层保存。"
  );
}

function hongKongCareerConclusion(horses) {
  const hongKongHorses = horses.filter(
    (horse) => horse.region === "hong_kong",
  );
  if (!hongKongHorses.length) return "中国香港：当前输入无样本。";

  const records = recordsFor(hongKongHorses);
  const actualStartCount = records.filter(
    (record) => recordStartKind(record) === "start",
  ).length;
  const nonstarterCount = records.filter(
    (record) => recordStartKind(record) === "nonstart",
  ).length;
  const unknownCount = records.length - actualStartCount - nonstarterCount;
  const overseasCount = records.filter(
    (record) =>
      record.is_overseas === true && recordStartKind(record) === "start",
  ).length;
  const namedStatements = [
    "SOUTHERN LEGEND",
    "BEAUTY ONLY",
    "TIME WARP",
  ].flatMap((expectedName) => {
    const horse = hongKongHorses.find(
      (candidate) =>
        normalizedText(horseName(candidate))
        === normalizedText(expectedName),
    );
    return horse
      ? [`${horseName(horse)}：${careerCountDifferenceStatement(horse)}`]
      : [];
  });
  const unknownStatement = unknownCount
    ? `、${unknownCount} 次待确认`
    : "";
  const namedStatement = namedStatements.length
    ? `；${namedStatements.join("，")}`
    : "";
  return (
    `中国香港现有 ${records.length} 条履历记录：` +
    `${actualStartCount} 次实际出赛、${nonstarterCount} 次未出赛` +
    `${unknownStatement}，其中 ${overseasCount} 次为 Overseas` +
    `${namedStatement}。`
  );
}

function unitedKingdomCareerConclusion(horses) {
  const ukHorses = horses.filter(
    (horse) => horse.region === "united_kingdom",
  );
  if (!ukHorses.length) return "";

  const statements = [];
  const edwardstone = ukHorses.find(
    (horse) => normalizedText(horseName(horse)) === "edwardstone",
  );
  if (edwardstone) {
    const abnormalCount = (edwardstone.career?.records || []).filter(
      (record) =>
        ["f", "ur", "bd"].includes(
          normalizedText(record.official_result_code || record.finish),
        ),
    ).length;
    statements.push(
      `Edwardstone 的 ${abnormalCount} 条 F/UR/BD 已按实际出赛未完赛计入`,
    );
  }

  const oldNaRecords = legacyNaRecords(recordsFor(ukHorses));
  const oldNaStatement = legacyNaResolutionStatement(oldNaRecords);
  if (oldNaStatement) statements.push(oldNaStatement);

  if (!statements.length) return "英国当前输入无专项结果状态结论";
  return `英国 ${statements.join("；")}`;
}

export function careerConclusionRows(horses) {
  const unitedKingdomStatement = unitedKingdomCareerConclusion(horses);
  const unitedStatesHorses = horses.filter(
    (horse) => horse.region === "united_states",
  );
  const unitedStatesStatement = unitedStatesHorses.length
    ? `美国 ${unitedStatesCareerStatement(unitedStatesHorses)}`
    : "";
  const ukAndUsStatement = [
    unitedKingdomStatement,
    unitedStatesStatement,
  ].filter(Boolean).join("；") || "英国/美国：当前输入无样本";
  return [
    franceCareerConclusion(horses),
    hongKongCareerConclusion(horses),
    `${ukAndUsStatement}。`,
  ];
}

function fortGeorgeSupplementStatement(horse) {
  const primarySource = normalizedText(horse.source?.name);
  const supplementedCount = (horse.career?.records || []).filter((record) => {
    if (record.is_supplemental === true || record.supplementation_reason) {
      return true;
    }
    if (!primarySource.includes("hrn")) return false;
    const recordSource = normalizedText(record.source_name);
    const sourceUrl = normalizedText(record.source_url);
    const hasSource = Boolean(recordSource || sourceUrl);
    const isHrnRecord =
      ["hrn", "horse_racing_nation"].includes(recordSource)
      || sourceUrl.includes("horseracingnation.com");
    return hasSource && !isHrnRecord;
  }).length;
  const supplementStatement = supplementedCount
    ? `${supplementedCount} 场非 HRN 逐场来源补入，`
    : "";
  return (
    `Fort George：${supplementStatement}` +
    careerCountDifferenceStatement(horse)
  );
}

export function buildSourceResearchRows(horses) {
  const franceHorses = horses.filter((horse) => horse.region === "france");
  const franceBreakdown = legacyNaBreakdown(recordsFor(franceHorses));
  const franceResolvedCount =
    franceBreakdown.totalCount - franceBreakdown.unresolvedCount;
  const franceNaStatement = franceHorses.length
    ? franceBreakdown.unresolvedCount
      ? `${franceBreakdown.totalCount} 条 N/A 中 ` +
        `${franceResolvedCount} 条已有逐场结果证据、` +
        `${franceBreakdown.unresolvedCount} 条仍待确认`
      : `${franceBreakdown.totalCount} 条 N/A 已由逐场结果证据补证`
    : "";

  const ukHorses = horses.filter(
    (horse) => horse.region === "united_kingdom",
  );
  const ukNaStatement = legacyNaResolutionStatement(recordsFor(ukHorses));

  const usHorses = horses.filter(
    (horse) => horse.region === "united_states",
  );
  const usVerifiedCount = usHorses.filter(
    (horse) =>
      horse.career?.source_start_count_quality === "official_verified",
  ).length;
  const usAlignedCount = usHorses.filter(
    (horse) =>
      horse.field_status?.career_gap_count === 0
      && horse.career?.record_authority_status
        === "count_aligned_records_unverified",
  ).length;
  const usOfficialityPendingCount = usHorses.filter(
    (horse) =>
      horse.career?.record_authority_status !== "source_records_verified",
  ).length;
  const fortGeorge = usHorses.find(
    (horse) => normalizedText(horseName(horse)) === "fort george",
  );
  const usVerificationStatement = usHorses.length
    ? `${usVerifiedCount}/${usHorses.length} 匹 Career Starts 已核验`
    : "";
  const fortGeorgeStatement = fortGeorge
    ? fortGeorgeSupplementStatement(fortGeorge)
    : "";
  const usBatchStatus = usHorses.length
    ? (
      `${usAlignedCount}/${usHorses.length} 匹处于数量已对齐、` +
      `逐场官方性待确认状态；` +
      `${usOfficialityPendingCount}/${usHorses.length} 匹逐场官方性仍待确认`
    )
    : "当前输入无美国样本";

  return [
    [
      "日本",
      "JBIS",
      "马名/ID、产地、性别、毛色、出生日期、马主、练马师、育马者、三代血统、完整逐场履历",
      regionalBatchGapStatement(horses, "japan", "日本"),
      "直接按 JBIS horse ID 抓 profile + record；保留逐场结果 URL",
      "公开页面可用",
      "https://www.jbis.or.jp/horse/",
      "https://www.jbis.or.jp/jbis_hp/english/",
      "可作为日本长期主来源",
    ],
    [
      "中国香港",
      "HKJC + 原产地血统/赛事来源 + netkeiba 父母实体反查",
      "产地、精确出生日期、性别、毛色、马主、练马师、育马者、六项三代血统、本地及 Overseas 完整履历",
      `${regionalBatchGapStatement(horses, "hong_kong", "中国香港")}；` +
      "新增祖父母及基础资料仍待原产地 Stud Book 长期复核",
      "现以马名+父母锁定身份后反查父母的父母；长期按产地进入官方 Stud Book，澳洲马可进 ASB",
      "公开页面可用；Overseas 主表与下方重复表必须稳定键去重",
      "https://racing.hkjc.com/en-us/local/information/selecthorse",
      "https://studbook.org.au/General.aspx",
      "长期需要“HKJC + 原产地 Stud Book”双来源",
    ],
    [
      "法国",
      "Sporting Life / France Galop / France-Sire / netkeiba",
      "产地、性别、毛色、出生日期、马主、练马师、育马者、六项三代血统、完整可见履历" +
      (franceNaStatement ? `；${franceNaStatement}` : ""),
      `${regionalBatchGapStatement(horses, "france", "法国")}；` +
      "法国标准原始字段和二级血统值待 IFCE SIRE 长期复核",
      "当前通过目标马或父母实体血统页补祖父母；长期以 France Galop/IFCE SIRE 回填标准原始值",
      "Geny 自动访问 HTTP 429；不得由 Class 反推 Groupe，也不得由舍入英制距离反推官方米制",
      "https://www.ifce.fr/ifce/sire-demarches/donnees-sire/listes-de-chevaux/",
      "https://www.france-galop.com/fr/content/nomination-stud-book-identification-fee",
      "生产长期方案优先 France Galop/IFCE SIRE，不依赖 Sporting Life 单站语义",
    ],
    [
      "英国",
      "Sporting Life / Irish Racing / Racing Post / France Galop / 血统页",
      "产地、性别、毛色、出生日期、马主、练马师、育马者、六项三代血统、完整可见履历与来源出赛数",
      `${regionalBatchGapStatement(horses, "united_kingdom", "英国")}` +
      (ukNaStatement ? `；${ukNaStatement}` : "") +
      "；二级血统值待 Weatherbys 长期复核",
      "当前以父母实体和拍卖目录补祖父母；BHA Horse Search/Weatherbys 补育马者与官方血统",
      "BHA 页面当前有 Cloudflare，需浏览器、许可接口或稳定数据合作",
      "https://www.britishhorseracing.com/racing/horses/",
      "https://www.weatherbys.co.uk/breeding",
      "Sporting Life 可维持履历，身份和血统补全需第二来源",
    ],
    [
      "美国",
      "Equibase / HRN / Sporting Life / Racing Post / 父母实体与种公马资料页",
      "产地、性别、毛色、出生日期、马主、练马师、育马者、六项三代血统" +
      (usVerificationStatement ? `；${usVerificationStatement}` : "") +
      (fortGeorgeStatement ? `；${fortGeorgeStatement}` : ""),
      `${usBatchStatus}；` +
      "二级血统值待 Equineline 复核",
      "短期保留 Equibase 人工总数/毛色证据并对 HRN 同场重复行去重；长期使用授权 Equibase/Equineline/TrackMaster",
      "普通 HTTP 触发 Incapsula，且条款限制机器人抓取/再发布；禁止浏览器绕过做生产爬虫",
      "https://www.equibase.com/profiles/Results.cfm",
      "https://www.equineline.com/",
      "数量相等只标记“数量已对齐、逐场官方性待确认”；同名马禁止只按 slug 合并",
    ],
  ];
}

export function unitedStatesCareerStatement(horses) {
  const verifiedCount = horses.filter(
    (horse) =>
      horse.career?.source_start_count_quality === "official_verified",
  ).length;
  const alignedCount = horses.filter(
    (horse) =>
      horse.field_status?.career_gap_count === 0 &&
      horse.career?.record_authority_status ===
        "count_aligned_records_unverified",
  ).length;
  const gapHorses = horses.filter(
    (horse) =>
      (horse.field_status?.career_missing_start_count || 0) > 0,
  );
  const gapCount = gapHorses.reduce(
    (sum, horse) =>
      sum + (horse.field_status?.career_missing_start_count || 0),
    0,
  );
  const excessHorses = horses.filter(
    (horse) =>
      (horse.field_status?.career_excess_start_count || 0) > 0,
  );
  const excessCount = excessHorses.reduce(
    (sum, horse) =>
      sum + (horse.field_status?.career_excess_start_count || 0),
    0,
  );
  const deduplicatedCount = horses.reduce(
    (sum, horse) => sum + (horse.career?.deduplicated_record_count || 0),
    0,
  );
  const gapDescription = gapHorses.length
    ? `；${gapHorses.map(
        (horse) =>
          `${horse.candidate?.horse_name || horse.identity?.horse_name} 缺 ${horse.field_status?.career_missing_start_count} 场`,
      ).join("、")}`
    : "";
  const excessDescription = excessHorses.length
    ? `；${excessHorses.map(
        (horse) =>
          `${horse.candidate?.horse_name || horse.identity?.horse_name} 多采 ${horse.field_status?.career_excess_start_count} 场，待去重`,
      ).join("、")}`
    : "";
  return (
    `Equibase 官方总数已核验 ${verifiedCount}/${horses.length} 匹，` +
    `${alignedCount}/${horses.length} 匹与去重后的备用逐场记录数量对齐` +
    `；合并 ${deduplicatedCount} 条同场重复行` +
    `${gapDescription}` +
    `${excessDescription}` +
    `；当前已知逐场缺少 ${gapCount} 场、多采待去重 ${excessCount} 场，逐场官方性仍待授权数据或人工 Full Charts 核验`
  );
}
