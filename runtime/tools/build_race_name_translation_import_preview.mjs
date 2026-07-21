import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { createRequire } from "node:module";
import { promisify } from "node:util";
import { fileURLToPath, pathToFileURL } from "node:url";
import { gunzipSync } from "node:zlib";

import {
  buildNormalizedManifest,
  classifyDryRun,
  normalizeChineseDisplayName,
  parseYears,
  sha256Json,
  stableJson,
  parseJsonPreservingNumericLexemes,
  reassembleSnapshotTransport,
  validateAuthorizedWorkbookRevision,
  validateFullWorkbookRevision,
  validateLosslessSnapshot,
  validateReviewedRows,
  validateStableProductionMetadata,
} from "./race_name_translation_preview_core.mjs";

async function loadArtifactTool() {
  try {
    return await import("@oai/artifact-tool");
  } catch (error) {
    if (error?.code !== "ERR_MODULE_NOT_FOUND") throw error;
  }

  const candidateRoots = [
    process.env.CODEX_WORKSPACE_NODE_MODULES,
    ...String(process.env.NODE_PATH ?? "")
      .split(path.delimiter)
      .filter(Boolean),
    path.join(
      os.homedir(),
      ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules",
    ),
  ].filter(Boolean);
  for (const nodeModulesRoot of candidateRoots) {
    try {
      const requireFromRoot = createRequire(
        path.join(nodeModulesRoot, "__race_name_preview_loader__.cjs"),
      );
      const entrypoint = requireFromRoot.resolve("@oai/artifact-tool");
      return await import(pathToFileURL(entrypoint).href);
    } catch (error) {
      if (error?.code !== "MODULE_NOT_FOUND" && error?.code !== "ERR_MODULE_NOT_FOUND") {
        throw error;
      }
    }
  }
  throw new Error(
    "无法解析 @oai/artifact-tool；请把包含该包的 node_modules 绝对路径写入 CODEX_WORKSPACE_NODE_MODULES。",
  );
}

const { FileBlob, SpreadsheetFile, Workbook } = await loadArtifactTool();

const execFileAsync = promisify(execFile);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../..");
const sourceDocumentPath = path.join(
  repoRoot,
  "docs/collected_complete_race_names_missing_zh_20260719.md",
);
const outputRoot = path.join(
  repoRoot,
  "outputs/translate-race-names-20260719",
);
const expectedGroupingSha256 =
  "c9c209e686bbce669bfdfd161bade5f4dfae357cc899fa649e908a749cfa966d";
const japanRevisionBaseline = Object.freeze({
  regionName: "日本修订前基线",
  regionCode: "japan_revision_baseline",
  expectedRows: 176,
  path: path.join(
    outputRoot,
    "日本_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx",
  ),
  sha256: "57a40984e2723251db554f6a6c7c7a9b2661991fee16ad89b69ed3e902c81fad",
});
const japanRevisionAllowlist = Object.freeze({
  sheetName: "翻译清单",
  range: "A1:L180",
  allowedRowIndex: 67,
  allowedColumnIndex: 2,
  allowedAddress: "C68",
  expectedBefore: "京成杯秋季让赛",
  expectedAfter: "京成杯秋季赛",
});

const regionDefinitions = [
  {
    regionName: "日本",
    regionCode: "japan",
    expectedRows: 176,
    path: path.join(
      outputRoot,
      "日本_已完整赛事中文名翻译审核表_20260719_京成杯秋季赛修订.xlsx",
    ),
    sha256: "e244a0fb366ab1cf259b3c2f714cfea2066e8abbf21a79076c64443220b26eb1",
  },
  {
    regionName: "中国香港",
    regionCode: "hong_kong",
    expectedRows: 91,
    path: path.join(
      outputRoot,
      "中国香港_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx",
    ),
    sha256: "20153db5217a8b05ff7b98b0af9640dea52ead58b17a8a91d35eedd154fa705f",
  },
  {
    regionName: "美国",
    regionCode: "united_states",
    expectedRows: 724,
    path: path.join(
      outputRoot,
      "美国_已完整赛事中文名翻译审核表_20260719_已审核.xlsx",
    ),
    sha256: "f2481cdeea456bbf6ac5faf9102928cb5d67d520082d8b5c47ffecd41aa46c00",
  },
  {
    regionName: "英国",
    regionCode: "united_kingdom",
    expectedRows: 794,
    path: path.join(
      outputRoot,
      "英国_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx",
    ),
    sha256: "f0a80a5f55244224698fab6f3d56f0d5a7d776eb01ba02bf75c7d5f33d45488b",
  },
  {
    regionName: "法国",
    regionCode: "france",
    expectedRows: 238,
    path: path.join(
      outputRoot,
      "法国_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx",
    ),
    sha256: "8234a68a16dc6c8e13b2cbef7a5eaf91a31ceeb0b0b561fcda4b596d5ffe02da",
  },
];

const expectedTotals = Object.freeze({
  rowCount: 2023,
  sourceSeriesCount: 1301,
  targetSeriesCount: 1300,
  annualEventCount: 8663,
  eventActionCount: 8883,
  supplementalEventCount: 220,
  identityCorrectionActionCount: 1,
  outOfScopeEventCount: 2,
  crossSeriesDuplicateGroupCount: 101,
});

function timestampForPath(date = new Date()) {
  return date.toISOString().replaceAll(":", "").replaceAll("-", "").replace(/\.\d{3}Z$/u, "Z");
}

function normalizeCell(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

async function sha256File(filePath) {
  const bytes = await fs.readFile(filePath);
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

async function loadLockedWorkbook(definition) {
  const stat = await fs.stat(definition.path);
  const blob = await FileBlob.load(definition.path);
  const bytes = Buffer.from(blob.data);
  const actualSha256 = crypto.createHash("sha256").update(bytes).digest("hex");
  if (actualSha256 !== definition.sha256) {
    throw new Error(
      `${definition.regionName} workbook SHA mismatch: expected=${definition.sha256}, actual=${actualSha256}`,
    );
  }
  return {
    blob,
    bytes,
    lock: {
      regionName: definition.regionName,
      regionCode: definition.regionCode,
      path: definition.path,
      expectedRows: definition.expectedRows,
      sha256: actualSha256,
      sizeBytes: bytes.length,
      modifiedAt: stat.mtime.toISOString(),
    },
  };
}

async function resolveLayoutComparisonPython() {
  const candidates = [
    process.env.CODEX_WORKSPACE_PYTHON,
    path.join(
      os.homedir(),
      ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3",
    ),
    "python3",
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      await execFileAsync(candidate, ["-c", "import openpyxl"], {
        timeout: 10_000,
      });
      return candidate;
    } catch {
      // Try the next explicit interpreter; comparison must fail closed if none work.
    }
  }
  throw new Error("无法找到包含 openpyxl 的 Python，不能执行 XLSX 完整布局校验。");
}

async function validateJapanWorkbookLayout(beforeBytes, afterBytes) {
  const temporaryDirectory = await fs.mkdtemp(
    path.join(os.tmpdir(), "race-name-japan-layout-"),
  );
  const beforePath = path.join(temporaryDirectory, "before.xlsx");
  const afterPath = path.join(temporaryDirectory, "after.xlsx");
  try {
    await Promise.all([
      fs.writeFile(beforePath, beforeBytes, { mode: 0o600 }),
      fs.writeFile(afterPath, afterBytes, { mode: 0o600 }),
    ]);
    const python = await resolveLayoutComparisonPython();
    const { stdout } = await execFileAsync(
      python,
      [
        path.join(scriptDir, "compare_xlsx_layout.py"),
        "--before",
        beforePath,
        "--after",
        afterPath,
      ],
      { timeout: 30_000, maxBuffer: 1024 * 1024 },
    );
    return JSON.parse(stdout);
  } finally {
    await fs.rm(temporaryDirectory, { recursive: true, force: true });
  }
}

function unescapeMarkdownCell(value) {
  return value.replaceAll("\\|", "|").replaceAll("\\\\", "\\").trim();
}

function parseBaselineDocument(sourceText) {
  const rowsByRegion = new Map(regionDefinitions.map((region) => [region.regionName, []]));
  let currentRegion = "";
  for (const line of sourceText.split(/\r?\n/u)) {
    const heading = line.match(/^## (日本|中国香港|美国|英国|法国)（/u);
    if (heading) {
      currentRegion = heading[1];
      continue;
    }
    if (!currentRegion) continue;
    const match = line.match(
      /^\| (\d+) \| (.*?) \| (.*?) \| (\d+) \| `([^`]+)`（ID (\d+)） \|$/u,
    );
    if (!match) continue;
    const definition = regionDefinitions.find(
      (region) => region.regionName === currentRegion,
    );
    rowsByRegion.get(currentRegion).push({
      regionName: currentRegion,
      regionCode: definition.regionCode,
      sequence: Number(match[1]),
      displayName: unescapeMarkdownCell(match[2]),
      chineseName: "",
      status: "",
      yearsText: unescapeMarkdownCell(match[3]),
      annualEventCount: Number(match[4]),
      seriesKey: match[5],
      seriesId: Number(match[6]),
      source: "",
      sourceUrl: "",
      sourceNote: "",
    });
  }
  for (const definition of regionDefinitions) {
    const actual = rowsByRegion.get(definition.regionName).length;
    if (actual !== definition.expectedRows) {
      throw new Error(
        `${definition.regionName} baseline row count mismatch: expected=${definition.expectedRows}, actual=${actual}`,
      );
    }
  }
  return rowsByRegion;
}

function calculateGroupingSha256(rowsByRegion) {
  const originalDatabaseOrder = [...regionDefinitions].sort((left, right) =>
    left.regionCode.localeCompare(right.regionCode, "en"),
  );
  const groupingRows = originalDatabaseOrder.flatMap((definition) =>
    rowsByRegion.get(definition.regionName).map((row) => ({
      country_region: row.regionCode,
      race_series_id: row.seriesId,
      race_series__key: row.seriesKey,
      event__chinese_name: row.displayName,
      years: parseYears(row.yearsText),
      event_count: row.annualEventCount,
    })),
  );
  return sha256Json(groupingRows);
}

async function readReviewedWorkbook(definition, blob) {
  const workbook = await SpreadsheetFile.importXlsx(blob);
  const sheet = workbook.worksheets.getItem("翻译清单");
  const values = sheet
    .getRange(`A1:L${definition.expectedRows + 4}`)
    .values.slice(4);
  const rows = values
    .filter((row) => row.some((cell) => normalizeCell(cell) !== ""))
    .map((row) => ({
      regionName: definition.regionName,
      regionCode: definition.regionCode,
      sequence: Number(row[0]),
      displayName: normalizeCell(row[1]),
      chineseName: normalizeCell(row[2]),
      status: normalizeCell(row[3]),
      yearsText: normalizeCell(row[4]),
      annualEventCount: Number(row[5]),
      seriesKey: normalizeCell(row[6]),
      seriesId: Number(row[7]),
      translationNote: normalizeCell(row[8]),
      source: normalizeCell(row[9]),
      sourceUrl: normalizeCell(row[10]),
      sourceNote: normalizeCell(row[11]),
    }));
  if (rows.length !== definition.expectedRows) {
    throw new Error(
      `${definition.regionName} reviewed row count mismatch: expected=${definition.expectedRows}, actual=${rows.length}`,
    );
  }
  const formulaErrors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: `${definition.regionName} formula error scan`,
  });
  return {
    workbook,
    rows,
    formulaErrorScan: formulaErrors.ndjson,
  };
}

function validateJapanAuthorizedRevision(beforeWorkbook, afterWorkbook) {
  return validateFullWorkbookRevision(
    beforeWorkbook,
    afterWorkbook,
    japanRevisionAllowlist,
  );
}

function buildProductionQueryScript(seriesIds) {
  return `
import base64
import datetime
import decimal
import hashlib
import json
import uuid
import gzip
from django.db import connection, transaction
from stable.models import HistoricalRaceEventTarget, RaceEvent, RaceSeries

series_ids = ${JSON.stringify(seriesIds)}

def iso(value):
    return value.isoformat().replace("+00:00", "Z") if value else ""

def normalize(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime.datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return {"__bytes_base64__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize(value[key]) for key in sorted(value, key=lambda item: str(item))}
    return str(value)

def full_row(instance):
    fields = {
        field.attname: normalize(getattr(instance, field.attname))
        for field in sorted(instance._meta.concrete_fields, key=lambda item: item.attname)
    }
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "fields": fields,
        "rowSha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }

def take_snapshot():
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        series = [
            {
                "id": row.id,
                "key": row.key,
                "countryRegion": row.country_region,
                "chineseName": row.chinese_name,
                "manualLockFlags": row.manual_lock_flags or {},
                "updatedAt": iso(row.updated_at),
                "fullRow": full_row(row),
            }
            for row in RaceSeries.objects.filter(id__in=series_ids)
            .order_by("id")
        ]
        events = [
            {
                "id": row.id,
                "year": row.year,
                "raceSeriesId": row.race_series_id,
                "seriesKey": row.series_key,
                "countryRegion": row.country_region,
                "originalName": row.original_name,
                "chineseName": row.chinese_name,
                "manualLockFlags": row.manual_lock_flags or {},
                "updatedAt": iso(row.updated_at),
                "fullRow": full_row(row),
            }
            for row in RaceEvent.objects.filter(race_series_id__in=series_ids)
            .order_by("id")
        ]
        historical_targets = [
            {
                "id": row.id,
                "eventId": row.event_id,
                "year": row.year,
                "raceSeriesId": row.race_series_id,
                "countryRegion": row.country_region,
                "updatedAt": iso(row.updated_at),
                "fullRow": full_row(row),
            }
            for row in HistoricalRaceEventTarget.objects.filter(
                race_series_id__in=series_ids
            ).order_by("id")
        ]
        payload = {
            "series": series,
            "events": events,
            "historicalTargets": historical_targets,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {
            "content": payload,
            "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "seriesCount": len(series),
            "eventCount": len(events),
            "historicalTargetCount": len(historical_targets),
        }

first = take_snapshot()
first_summary = {key: value for key, value in first.items() if key != "content"}
# 第一轮 content 只用于比对摘要，从不传输；在第二轮快照前显式释放，
# 否则两份完整快照同时驻留会使容器内进程在 4 GiB 主机上被 OOM 杀死。
del first
import gc
gc.collect()
second = take_snapshot()
payload = json.dumps({
    "databaseVendor": connection.vendor,
    "first": first_summary,
    "second": second,
    "stable": (
        first_summary["sha256"] == second["sha256"]
        and first_summary["seriesCount"] == second["seriesCount"]
        and first_summary["eventCount"] == second["eventCount"]
        and first_summary["historicalTargetCount"] == second["historicalTargetCount"]
    ),
}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
envelope = json.dumps({
    "payloadBase64": base64.b64encode(payload).decode("ascii"),
    "payloadSha256": hashlib.sha256(payload).hexdigest(),
}, sort_keys=True, separators=(",", ":")).encode("utf-8")
encoded = base64.b64encode(gzip.compress(envelope, compresslevel=6)).decode("ascii")
chunk_size = 512 * 1024
chunks = [encoded[index:index + chunk_size] for index in range(0, len(encoded), chunk_size)]
for index, chunk in enumerate(chunks, start=1):
    print(f"RACE_NAME_SNAPSHOT_CHUNK {index}/{len(chunks)} {chunk}")
`;
}

async function fetchProductionSnapshot(seriesIds) {
  const pythonSource = buildProductionQueryScript(seriesIds);
  const encoded = Buffer.from(pythonSource, "utf8").toString("base64");
  const remoteCommand =
    `docker exec umanewsbot-web-1 python manage.py shell -c ` +
    `"exec(__import__('base64').b64decode('${encoded}'))"`;
  const { stdout } = await execFileAsync(
    "ssh",
    [
      "-o",
      "BatchMode=yes",
      "-o",
      "ConnectTimeout=15",
      "-o",
      "ControlMaster=no",
      "-o",
      "ControlPath=none",
      "root@47.239.167.86",
      remoteCommand,
    ],
    { maxBuffer: 256 * 1024 * 1024 },
  );
  const lines = stdout.split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
  const encodedEnvelope = reassembleSnapshotTransport(lines);
  const envelope = JSON.parse(
    gunzipSync(Buffer.from(encodedEnvelope, "base64")).toString("utf8"),
  );
  const payloadBytes = Buffer.from(envelope.payloadBase64, "base64");
  const transportSha256 = crypto
    .createHash("sha256")
    .update(payloadBytes)
    .digest("hex");
  if (transportSha256 !== envelope.payloadSha256) {
    throw new Error(
      `production snapshot transport digest mismatch: server=${envelope.payloadSha256}, local=${transportSha256}`,
    );
  }
  const payloadText = payloadBytes.toString("utf8");
  const payload = JSON.parse(payloadText);
  const losslessPayload = parseJsonPreservingNumericLexemes(payloadText);
  if (!payload.stable) {
    throw new Error(
      `production snapshot drift: first=${payload.first.sha256}, second=${payload.second.sha256}`,
    );
  }
  const losslessSecondContent = validateLosslessSnapshot(payload, losslessPayload);
  const losslessByKind = [
    ["series", "series"],
    ["events", "events"],
    ["historicalTargets", "historicalTargets"],
  ];
  for (const [normalKey, losslessKey] of losslessByKind) {
    const losslessById = new Map(
      losslessSecondContent[losslessKey].map((row) => [
        Number(row.id),
        row.fullRow,
      ]),
    );
    for (const row of payload.second.content[normalKey]) {
      row.fullRow = losslessById.get(Number(row.id));
    }
  }
  payload.losslessSecondContent = losslessSecondContent;
  return payload;
}

async function fetchProductionMetadata() {
  const { stdout } = await execFileAsync(
    "ssh",
    [
      "-o",
      "BatchMode=yes",
      "-o",
      "ConnectTimeout=15",
      "-o",
      "ControlMaster=no",
      "-o",
      "ControlPath=none",
      "root@47.239.167.86",
      "cd /opt/umanewsbot && git rev-parse HEAD && docker inspect -f '{{.Image}} {{.Config.Image}} {{.State.StartedAt}}' umanewsbot-web-1",
    ],
    { maxBuffer: 1024 * 1024 },
  );
  const lines = stdout.split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
  const [imageId, imageTag, containerStartedAt] = lines[1].split(/\s+/u);
  return {
    server: "root@47.239.167.86",
    checkoutPath: "/opt/umanewsbot",
    gitHead: lines[0],
    container: "umanewsbot-web-1",
    imageId,
    imageTag,
    containerStartedAt,
  };
}

function buildOutOfScopeEvents(manifest, snapshot, dryRun) {
  const inScopeEventIds = new Set(
    dryRun.eventActions
      .map((action) => Number(action.eventId))
      .filter(Number.isInteger),
  );
  const relevantSeriesIds = new Set(manifest.queriedSeriesIds.map(Number));
  return snapshot.events
    .filter((event) => {
      return (
        relevantSeriesIds.has(Number(event.raceSeriesId)) &&
        !inScopeEventIds.has(Number(event.id))
      );
    })
    .map((event) => ({
      eventId: event.id,
      raceSeriesId: event.raceSeriesId,
      year: event.year,
      originalName: event.originalName,
      chineseName: event.chineseName,
    }));
}

function buildCrossSeriesDuplicates(seriesActions) {
  const grouped = new Map();
  for (const row of seriesActions) {
    const items = grouped.get(row.proposedChineseName) ?? [];
    items.push(row);
    grouped.set(row.proposedChineseName, items);
  }
  return [...grouped.entries()]
    .filter(([, rows]) => rows.length > 1)
    .map(([chineseName, rows]) => ({
      chineseName,
      seriesCount: rows.length,
      series: rows.map((row) => ({
        regionName: row.regionName,
        seriesId: row.seriesId,
        seriesKey: row.seriesKey,
      })),
    }))
    .sort((left, right) => left.chineseName.localeCompare(right.chineseName, "zh-CN"));
}

function buildRollbackBefore(dryRun) {
  return {
    schemaVersion: "race-name-translation-rollback-before.v3",
    series: dryRun.seriesActions
      .filter((row) => row.classification === "would_update")
      .map((row) => ({
        seriesId: row.seriesId,
        before: row.before.fullRow,
        after: row.after,
      })),
    events: dryRun.eventActions
      .filter((row) => row.classification === "would_update")
      .map((row) => ({
        eventId: row.eventId,
        actionType: row.actionType,
        before: row.before.fullRow,
        after: row.after,
      })),
    historicalTargets: dryRun.eventActions
      .filter(
        (row) =>
          row.classification === "would_update" &&
          row.actionType === "reassign_series_and_translate",
      )
      .map((row) => ({
        historicalTargetId: row.historicalTargetBefore.id,
        eventId: row.eventId,
        before: row.historicalTargetBefore.fullRow,
        after: {
          raceSeriesId: row.after.raceSeriesId,
        },
      })),
  };
}

function stableFieldsSha256(fields, mutableFields) {
  const stableFields = Object.fromEntries(
    Object.entries(fields).filter(([key]) => !mutableFields.has(key)),
  );
  return sha256Json(stableFields);
}

function buildExecutionPlan(rollbackBefore, production, manifest) {
  const content = {
    schemaVersion: "race-name-translation-execution-plan.v1",
    sourceRollbackContentSha256: rollbackBefore.contentSha256,
    eventScope: {
      series: production.losslessSecondContent.series.map((row) => ({
        seriesId: Number(row.id),
        beforeRowSha256: row.fullRow.rowSha256,
      })),
      events: production.losslessSecondContent.events.map((row) => ({
        eventId: Number(row.id),
        raceSeriesId: Number(row.raceSeriesId),
        beforeRowSha256: row.fullRow.rowSha256,
      })),
    },
    series: rollbackBefore.series.map((row) => ({
      seriesId: row.seriesId,
      beforeRowSha256: row.before.rowSha256,
      stableFieldsSha256: stableFieldsSha256(
        row.before.fields,
        new Set(["chinese_name", "updated_at"]),
      ),
      restore: {
        chinese_name: row.before.fields.chinese_name,
      },
      after: row.after,
    })),
    events: rollbackBefore.events.map((row) => ({
      eventId: row.eventId,
      actionType: row.actionType,
      beforeRowSha256: row.before.rowSha256,
      stableFieldsSha256: stableFieldsSha256(
        row.before.fields,
        new Set(["chinese_name", "race_series_id", "series_key", "updated_at"]),
      ),
      restore: {
        chinese_name: row.before.fields.chinese_name,
        race_series_id: row.before.fields.race_series_id,
        series_key: row.before.fields.series_key,
      },
      after: row.after,
    })),
    historicalTargets: rollbackBefore.historicalTargets.map((row) => ({
      historicalTargetId: row.historicalTargetId,
      eventId: row.eventId,
      beforeRowSha256: row.before.rowSha256,
      stableFieldsSha256: stableFieldsSha256(
        row.before.fields,
        new Set(["race_series_id", "updated_at"]),
      ),
      restore: {
        race_series_id: row.before.fields.race_series_id,
      },
      after: row.after,
    })),
  };
  return {
    ...content,
    contentSha256: sha256Json(content),
  };
}

async function saveJson(filePath, value) {
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function setTitle(sheet, title, subtitle, lastColumn) {
  sheet.showGridLines = false;
  const titleRange = sheet.getRange(`A1:${lastColumn}1`);
  titleRange.merge();
  titleRange.values = [[title]];
  titleRange.format = {
    fill: "#17324D",
    font: { bold: true, color: "#FFFFFF", size: 18, name: "Microsoft YaHei" },
    verticalAlignment: "center",
  };
  titleRange.format.rowHeight = 32;
  const subtitleRange = sheet.getRange(`A2:${lastColumn}2`);
  subtitleRange.merge();
  subtitleRange.values = [[subtitle]];
  subtitleRange.format = {
    fill: "#DCEAF7",
    font: { color: "#5B6573", italic: true, size: 10, name: "Microsoft YaHei" },
    verticalAlignment: "center",
  };
  subtitleRange.format.rowHeight = 24;
}

function writeTable(sheet, startRow, headers, rows, widths = []) {
  const endColumn = String.fromCharCode(64 + headers.length);
  const headerRange = sheet.getRange(`A${startRow}:${endColumn}${startRow}`);
  headerRange.values = [headers];
  headerRange.format = {
    fill: "#244C73",
    font: { bold: true, color: "#FFFFFF", name: "Microsoft YaHei" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: {
      bottom: { style: "medium", color: "#17324D" },
    },
  };
  headerRange.format.rowHeight = 30;
  if (rows.length > 0) {
    const dataRange = sheet.getRange(
      `A${startRow + 1}:${endColumn}${startRow + rows.length}`,
    );
    dataRange.values = rows;
    dataRange.format = {
      font: { color: "#243447", size: 9, name: "Microsoft YaHei" },
      verticalAlignment: "top",
      wrapText: true,
      borders: {
        bottom: { style: "thin", color: "#D9E2EA" },
      },
    };
    dataRange.format.rowHeight = 26;
  }
  widths.forEach((width, index) => {
    const column = String.fromCharCode(65 + index);
    sheet
      .getRange(`${column}1:${column}${Math.max(startRow + rows.length, 2)}`)
      .format.columnWidth = width;
  });
  sheet.freezePanes.freezeRows(startRow);
}

async function buildReportWorkbook({
  generatedAt,
  manifest,
  dryRun,
  inputLocks,
  productionSnapshot,
  crossSeriesDuplicates,
}) {
  const workbook = Workbook.create();
  const summary = workbook.worksheets.add("概览");
  setTitle(
    summary,
    "五区赛事中文名统一导入预演",
    `只读 dry-run｜生成时间 ${generatedAt}｜未修改生产数据库`,
    "H",
  );
  const summaryRows = [
    ["结论", dryRun.applyReady ? "可进入人工审核" : "阻断", "阻断项", dryRun.blockerCount],
    ["审核分组", manifest.sourceRowCount, "源赛事系列", manifest.sourceSeriesCount],
    ["目标系列动作", manifest.targetSeriesCount, "年度赛事目标", manifest.annualEventCount],
    [
      "系列待更新",
      dryRun.seriesCounts.would_update,
      "系列已一致",
      dryRun.seriesCounts.already_applied,
    ],
    [
      "赛事待更新",
      dryRun.eventCounts.would_update,
      "赛事已一致",
      dryRun.eventCounts.already_applied,
    ],
    [
      "身份修正待执行",
      dryRun.identityCorrectionCounts.would_update,
      "跨系列同译名组",
      crossSeriesDuplicates.length,
    ],
    ["生产快照系列", productionSnapshot.second.seriesCount, "生产快照赛事", productionSnapshot.second.eventCount],
    [
      "让赛规则调整",
      manifest.groupActions.filter((row) => row.translationRuleAdjustment).length,
      "原工作簿改动",
      0,
    ],
    ["生产快照 SHA-256", productionSnapshot.second.sha256, "输入 manifest SHA-256", manifest.contentSha256],
  ];
  summary.getRange("A4:D12").values = summaryRows;
  summary.getRange("A4:D12").format = {
    font: { name: "Microsoft YaHei", color: "#243447", size: 10 },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: "#D9E2EA" },
  };
  summary.getRange("A4:A12").format.fill = "#DCEAF7";
  summary.getRange("C4:C12").format.fill = "#DCEAF7";
  summary.getRange("A4:A12").format.font = {
    bold: true,
    name: "Microsoft YaHei",
    color: "#243447",
  };
  summary.getRange("C4:C12").format.font = {
    bold: true,
    name: "Microsoft YaHei",
    color: "#243447",
  };
  summary.getRange("A4:D12").format.rowHeight = 28;
  summary.getRange("A1:A12").format.columnWidth = 18;
  summary.getRange("B1:B12").format.columnWidth = 28;
  summary.getRange("C1:C12").format.columnWidth = 18;
  summary.getRange("D1:D12").format.columnWidth = 28;
  summary.freezePanes.freezeRows(2);

  const blockers = workbook.worksheets.add("阻断项");
  setTitle(blockers, "阻断项", "存在任一记录时 apply_ready=false", "H");
  const blockerRows = [
    ...dryRun.seriesActions
      .filter((row) => ["conflict", "locked", "missing"].includes(row.classification))
      .map((row) => [
        "RaceSeries",
        row.classification,
        row.regionCode,
        row.seriesId,
        row.seriesKey,
        row.before?.chineseName ?? "",
        row.proposedChineseName,
        "",
      ]),
    ...dryRun.eventActions
      .filter((row) => ["conflict", "locked", "missing"].includes(row.classification))
      .map((row) => [
        "RaceEvent",
        row.classification,
        row.regionCode,
        row.eventId ?? "",
        `${row.year} ${row.displayName}`,
        row.before?.chineseName ?? "",
        row.proposedChineseName,
        row.actionType,
      ]),
  ];
  writeTable(
    blockers,
    4,
    ["对象", "分类", "地区", "ID", "身份", "当前中文名", "建议中文名", "动作"],
    blockerRows.length > 0 ? blockerRows : [["—", "无阻断项", "", "", "", "", "", ""]],
    [14, 14, 14, 12, 38, 24, 24, 24],
  );

  const seriesSheet = workbook.worksheets.add("系列动作");
  setTitle(seriesSheet, "RaceSeries 中文名动作", "不同系列同译名不会自动合并", "H");
  writeTable(
    seriesSheet,
    4,
    ["分类", "地区", "Series ID", "Series Key", "当前中文名", "建议中文名", "锁", "更新时间"],
    dryRun.seriesActions.map((row) => [
      row.classification,
      row.regionCode,
      row.seriesId,
      row.seriesKey,
      row.before?.chineseName ?? "",
      row.proposedChineseName,
      JSON.stringify(row.before?.manualLockFlags ?? {}),
      row.before?.updatedAt ?? "",
    ]),
    [16, 15, 12, 38, 24, 24, 24, 24],
  );
  seriesSheet
    .getRange(`H5:H${dryRun.seriesActions.length + 4}`)
    .setNumberFormat("yyyy-mm-dd hh:mm:ss");

  const eventSheet = workbook.worksheets.add("年度赛事动作");
  setTitle(eventSheet, "RaceEvent 中文名动作", "逐年度精确定位；原始赛事名不改写", "L");
  writeTable(
    eventSheet,
    4,
    [
      "分类",
      "地区",
      "Event ID",
      "年份",
      "动作",
      "当前 Series ID",
      "目标 Series ID",
      "原始赛事名",
      "当前中文名",
      "建议中文名",
      "锁",
      "更新时间",
    ],
    dryRun.eventActions.map((row) => [
      row.classification,
      row.regionCode,
      row.eventId ?? "",
      row.year,
      row.actionType,
      row.before?.raceSeriesId ?? "",
      row.after?.raceSeriesId ?? row.before?.raceSeriesId ?? "",
      row.before?.originalName ?? row.displayName,
      row.before?.chineseName ?? "",
      row.proposedChineseName,
      JSON.stringify(row.before?.manualLockFlags ?? {}),
      row.before?.updatedAt ?? "",
    ]),
    [16, 15, 12, 10, 24, 14, 14, 36, 26, 26, 22, 24],
  );
  eventSheet
    .getRange(`L5:L${dryRun.eventActions.length + 4}`)
    .setNumberFormat("yyyy-mm-dd hh:mm:ss");

  const correctionSheet = workbook.worksheets.add("身份修正");
  setTitle(correctionSheet, "显式身份修正", "仅包含用户点名复查的香港 SURFACE 污染行", "J");
  const corrections = dryRun.eventActions.filter(
    (row) => row.actionType === "reassign_series_and_translate",
  );
  writeTable(
    correctionSheet,
    4,
    [
      "分类",
      "Event ID",
      "年份",
      "原始赛事名",
      "当前 Series ID",
      "目标 Series ID",
      "当前 Series Key",
      "目标 Series Key",
      "当前中文名",
      "建议中文名",
    ],
    corrections.map((row) => [
      row.classification,
      row.eventId ?? "",
      row.year,
      row.before?.originalName ?? row.displayName,
      row.before?.raceSeriesId ?? "",
      row.after?.raceSeriesId ?? row.before?.raceSeriesId ?? "",
      row.before?.seriesKey ?? "",
      row.after?.seriesKey ?? row.before?.seriesKey ?? "",
      row.before?.chineseName ?? "",
      row.proposedChineseName,
    ]),
    [16, 12, 10, 42, 15, 15, 38, 38, 26, 26],
  );

  const adjustmentSheet = workbook.worksheets.add("规则调整");
  setTitle(
    adjustmentSheet,
    "中文展示规则调整",
    "仅应用用户已锁定的“让赛不展示”规则；原工作簿保持不变",
    "G",
  );
  const adjustments = manifest.groupActions.filter(
    (row) => row.translationRuleAdjustment,
  );
  writeTable(
    adjustmentSheet,
    4,
    ["地区", "序号", "原始赛事名", "工作簿中文名", "最终中文名", "规则", "来源"],
    adjustments.map((row) => [
      row.regionName,
      row.sequence,
      row.displayName,
      row.reviewedChineseName,
      row.proposedChineseName,
      row.translationRuleAdjustment,
      row.source,
    ]),
    [15, 10, 38, 26, 26, 24, 16],
  );

  const duplicatesSheet = workbook.worksheets.add("跨系列同译名");
  setTitle(
    duplicatesSheet,
    "跨系列同译名提示",
    "仅供身份复核，不阻断中文名写入，不触发自动合并",
    "E",
  );
  const duplicateRows = crossSeriesDuplicates.flatMap((group) =>
    group.series.map((series) => [
      group.chineseName,
      group.seriesCount,
      series.regionName,
      series.seriesId,
      series.seriesKey,
    ]),
  );
  writeTable(
    duplicatesSheet,
    4,
    ["中文名", "系列数", "地区", "Series ID", "Series Key"],
    duplicateRows,
    [28, 12, 15, 12, 42],
  );

  const inputSheet = workbook.worksheets.add("输入锁");
  setTitle(inputSheet, "输入文件锁", "五份最终审核工作簿与生产快照身份", "F");
  writeTable(
    inputSheet,
    4,
    ["地区", "行数", "大小", "修改时间", "SHA-256", "路径"],
    inputLocks.map((lock) => [
      lock.regionName,
      lock.expectedRows,
      lock.sizeBytes,
      lock.modifiedAt,
      lock.sha256,
      lock.path,
    ]),
    [15, 12, 14, 24, 68, 72],
  );
  inputSheet
    .getRange(`D5:D${inputLocks.length + 4}`)
    .setNumberFormat("yyyy-mm-dd hh:mm:ss");

  return workbook;
}

async function writeArtifactIndex(outputDir, entries) {
  const files = [];
  for (const entry of entries) {
    const filePath = path.join(outputDir, entry);
    const stat = await fs.stat(filePath);
    files.push({
      file: entry,
      sizeBytes: stat.size,
      sha256: await sha256File(filePath),
    });
  }
  const index = {
    schemaVersion: "race-name-translation-artifact-index.v1",
    files,
  };
  await saveJson(path.join(outputDir, "artifact-index.json"), index);
  return index;
}

async function writeBundleIndex(outputDir) {
  const scriptMembers = [
    "apply_race_name_translation_manifest.py",
    "verify_race_name_translation_manifest.py",
  ];
  for (const scriptName of scriptMembers) {
    await fs.copyFile(
      path.join(repoRoot, "runtime/tools", scriptName),
      path.join(outputDir, scriptName),
    );
  }
  const bundleMembers = [
    ...scriptMembers,
    "input-lock.json",
    "normalized-input.json",
    "manifest.json",
    "production-before.json",
    "dry-run.json",
    "rollback-before.json",
    "execution-metadata.json",
    "execution-plan.json",
    "artifact-index.json",
  ];
  const files = [];
  for (const file of bundleMembers) {
    const filePath = path.join(outputDir, file);
    const stat = await fs.stat(filePath);
    files.push({
      file,
      sizeBytes: stat.size,
      sha256: await sha256File(filePath),
    });
  }
  const content = {
    schemaVersion: "race-name-translation-bundle-index.v1",
    files,
  };
  const index = {
    ...content,
    contentSha256: sha256Json(content),
  };
  const indexPath = path.join(outputDir, "bundle-index.json");
  await saveJson(indexPath, index);
  return {
    ...index,
    rawSha256: await sha256File(indexPath),
  };
}

async function main() {
  const generatedAt = new Date().toISOString();
  const outputDir = path.join(
    outputRoot,
    `unified-import-preview-${timestampForPath(new Date(generatedAt))}`,
  );
  const qaDir = path.join(outputDir, "qa");
  await fs.mkdir(qaDir, { recursive: true });

  const inputLocks = [];
  const reviewedRows = [];
  const sourceText = await fs.readFile(sourceDocumentPath, "utf8");
  const baselineRowsByRegion = parseBaselineDocument(sourceText);
  const calculatedGroupingSha256 = calculateGroupingSha256(baselineRowsByRegion);
  if (calculatedGroupingSha256 !== expectedGroupingSha256) {
    throw new Error(
      `baseline grouping SHA mismatch: expected=${expectedGroupingSha256}, actual=${calculatedGroupingSha256}`,
    );
  }
  const workbookScans = [];
  const baselineJapan = await loadLockedWorkbook(japanRevisionBaseline);
  const baselineJapanWorkbook = await SpreadsheetFile.importXlsx(baselineJapan.blob);
  let japanAuthorizedRevision = null;

  for (const definition of regionDefinitions) {
    const lockedWorkbook = await loadLockedWorkbook(definition);
    inputLocks.push(lockedWorkbook.lock);
    const reviewed = await readReviewedWorkbook(definition, lockedWorkbook.blob);
    if (definition.regionCode === "japan") {
      japanAuthorizedRevision = validateJapanAuthorizedRevision(
        baselineJapanWorkbook,
        reviewed.workbook,
      );
      japanAuthorizedRevision.layoutComparison =
        await validateJapanWorkbookLayout(
          baselineJapan.bytes,
          lockedWorkbook.bytes,
        );
    }
    const adjustedRows = reviewed.rows.map((row) => ({
      ...row,
      ...normalizeChineseDisplayName(row.chineseName),
    }));
    validateReviewedRows(
      adjustedRows,
      baselineRowsByRegion.get(definition.regionName),
    );
    reviewedRows.push(...adjustedRows);
    workbookScans.push({
      regionName: definition.regionName,
      formulaErrorScan: reviewed.formulaErrorScan,
    });
  }

  const manifestContent = buildNormalizedManifest(reviewedRows, {
    expectedRowCount: expectedTotals.rowCount,
    expectedSeriesCount: expectedTotals.sourceSeriesCount,
    expectedAnnualEventCount: expectedTotals.annualEventCount,
  });
  if (manifestContent.targetSeriesCount !== expectedTotals.targetSeriesCount) {
    throw new Error(
      `target series count mismatch: expected=${expectedTotals.targetSeriesCount}, actual=${manifestContent.targetSeriesCount}`,
    );
  }
  const manifest = {
    generatedAt,
    inputGroupingSha256: calculatedGroupingSha256,
    inputLocks,
    japanRevisionBaselineLock: baselineJapan.lock,
    japanAuthorizedRevision,
    workbookScans,
    contentSha256: sha256Json(manifestContent),
    ...manifestContent,
  };

  const productionMetadataBefore = await fetchProductionMetadata();
  const production = await fetchProductionSnapshot(manifest.queriedSeriesIds);
  const productionMetadata = validateStableProductionMetadata(
    productionMetadataBefore,
    await fetchProductionMetadata(),
  );
  const snapshot = production.second.content;
  const dryRunContent = classifyDryRun(manifest, snapshot);
  const dryRun = {
    generatedAt,
    productionMetadata,
    productionSnapshotSha256: production.second.sha256,
    snapshotStable: production.stable,
    contentSha256: sha256Json(dryRunContent),
    ...dryRunContent,
  };
  dryRun.outOfScopeEvents = buildOutOfScopeEvents(manifest, snapshot, dryRun);
  dryRun.crossSeriesDuplicates = buildCrossSeriesDuplicates(manifest.seriesActions);
  // 目标计数锚点：supplemental、身份修正、范围外提示与总动作数都是规格
  // 锁定值；生产漂移导致任一计数偏离时 fail closed，不产出候选，避免
  // applyReady 在目标集缩小的情况下假阳性。
  const actualTotals = {
    seriesActionCount: dryRun.seriesActions.length,
    eventActionCount: dryRun.eventActions.length,
    supplementalEventCount: dryRun.supplementalEventCount,
    identityCorrectionActionCount: dryRun.eventActions.filter(
      (action) => action.actionType === "reassign_series_and_translate",
    ).length,
    outOfScopeEventCount: dryRun.outOfScopeEvents.length,
    crossSeriesDuplicateGroupCount: dryRun.crossSeriesDuplicates.length,
  };
  const expectedActionTotals = {
    seriesActionCount: expectedTotals.targetSeriesCount,
    eventActionCount: expectedTotals.eventActionCount,
    supplementalEventCount: expectedTotals.supplementalEventCount,
    identityCorrectionActionCount: expectedTotals.identityCorrectionActionCount,
    outOfScopeEventCount: expectedTotals.outOfScopeEventCount,
    crossSeriesDuplicateGroupCount: expectedTotals.crossSeriesDuplicateGroupCount,
  };
  if (stableJson(actualTotals) !== stableJson(expectedActionTotals)) {
    throw new Error(
      `dry-run action totals drift: expected=${stableJson(expectedActionTotals)}, actual=${stableJson(actualTotals)}`,
    );
  }
  dryRun.contentSha256 = sha256Json({
    ...dryRunContent,
    outOfScopeEvents: dryRun.outOfScopeEvents,
    crossSeriesDuplicates: dryRun.crossSeriesDuplicates,
  });

  const rollbackBefore = {
    generatedAt,
    sourceManifestSha256: manifest.contentSha256,
    sourceProductionSnapshotSha256: production.second.sha256,
    ...buildRollbackBefore(dryRun),
  };
  rollbackBefore.contentSha256 = sha256Json({
    schemaVersion: rollbackBefore.schemaVersion,
    series: rollbackBefore.series,
    events: rollbackBefore.events,
    historicalTargets: rollbackBefore.historicalTargets,
  });
  const executionPlan = buildExecutionPlan(rollbackBefore, production, manifest);

  await saveJson(path.join(outputDir, "input-lock.json"), {
    generatedAt,
    inputGroupingSha256: calculatedGroupingSha256,
    inputLocks,
    japanRevisionBaselineLock: baselineJapan.lock,
    japanAuthorizedRevision,
  });
  await saveJson(path.join(outputDir, "normalized-input.json"), {
    schemaVersion: "race-name-translation-normalized-input.v1",
    generatedAt,
    rows: reviewedRows,
  });
  await saveJson(path.join(outputDir, "manifest.json"), manifest);
  await saveJson(path.join(outputDir, "production-before.json"), {
    generatedAt,
    productionMetadata,
    databaseVendor: production.databaseVendor,
    firstSha256: production.first.sha256,
    secondSha256: production.second.sha256,
    stable: production.stable,
    ...production.losslessSecondContent,
  });
  await saveJson(path.join(outputDir, "dry-run.json"), dryRun);
  await saveJson(path.join(outputDir, "rollback-before.json"), rollbackBefore);
  await saveJson(path.join(outputDir, "execution-plan.json"), executionPlan);
  await saveJson(path.join(outputDir, "execution-metadata.json"), {
    schemaVersion: "race-name-translation-execution-metadata.v1",
    manifestContentSha256: manifest.contentSha256,
    productionBeforeSecondSha256: production.second.sha256,
    dryRunContentSha256: dryRun.contentSha256,
    dryRunApplyReady: dryRun.applyReady,
    dryRunBlockerCount: dryRun.blockerCount,
    rollbackContentSha256: rollbackBefore.contentSha256,
    executionPlanContentSha256: executionPlan.contentSha256,
    manifestFileSha256: await sha256File(path.join(outputDir, "manifest.json")),
    productionBeforeFileSha256: await sha256File(
      path.join(outputDir, "production-before.json"),
    ),
    dryRunFileSha256: await sha256File(path.join(outputDir, "dry-run.json")),
    rollbackFileSha256: await sha256File(
      path.join(outputDir, "rollback-before.json"),
    ),
  });

  const report = await buildReportWorkbook({
    generatedAt,
    manifest,
    dryRun,
    inputLocks,
    productionSnapshot: production,
    crossSeriesDuplicates: dryRun.crossSeriesDuplicates,
  });

  const previewRanges = {
    概览: "A1:H12",
    阻断项: "A1:H8",
    系列动作: `A1:H${Math.min(dryRun.seriesActions.length + 4, 35)}`,
    年度赛事动作: "A1:L35",
    身份修正: "A1:J8",
    规则调整: "A1:G8",
    跨系列同译名: `A1:E${Math.min(
      dryRun.crossSeriesDuplicates.reduce(
        (sum, group) => sum + group.series.length,
        0,
      ) + 4,
      35,
    )}`,
    输入锁: "A1:F9",
  };
  for (const [sheetName, range] of Object.entries(previewRanges)) {
    const preview = await report.render({
      sheetName,
      range,
      scale: 1.2,
      format: "png",
    });
    await fs.writeFile(
      path.join(qaDir, `${sheetName}.png`),
      new Uint8Array(await preview.arrayBuffer()),
    );
  }
  const eventTail = await report.render({
    sheetName: "年度赛事动作",
    range: `A${dryRun.eventActions.length - 25}:L${dryRun.eventActions.length + 4}`,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(qaDir, "年度赛事动作_末段.png"),
    new Uint8Array(await eventTail.arrayBuffer()),
  );

  const errorScan = await report.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "final formula error scan",
  });
  await fs.writeFile(
    path.join(qaDir, "formula-error-scan.ndjson"),
    `${errorScan.ndjson}\n`,
    "utf8",
  );
  const reportPath = path.join(outputDir, "五区赛事中文名统一导入预演.xlsx");
  const reportBlob = await SpreadsheetFile.exportXlsx(report);
  await reportBlob.save(reportPath);

  const index = await writeArtifactIndex(outputDir, [
    "input-lock.json",
    "normalized-input.json",
    "manifest.json",
    "production-before.json",
    "dry-run.json",
    "rollback-before.json",
    "execution-metadata.json",
    "execution-plan.json",
    "五区赛事中文名统一导入预演.xlsx",
  ]);
  const bundleIndex = await writeBundleIndex(outputDir);
  console.log(
    JSON.stringify(
      {
        outputDir,
        reportPath,
        manifestSha256: manifest.contentSha256,
        productionSnapshotSha256: production.second.sha256,
        dryRunSha256: dryRun.contentSha256,
        rollbackSha256: rollbackBefore.contentSha256,
        applyReady: dryRun.applyReady,
        blockerCount: dryRun.blockerCount,
        seriesCounts: dryRun.seriesCounts,
        eventCounts: dryRun.eventCounts,
        identityCorrectionCounts: dryRun.identityCorrectionCounts,
        outOfScopeEventCount: dryRun.outOfScopeEvents.length,
        crossSeriesDuplicateGroupCount: dryRun.crossSeriesDuplicates.length,
        artifactIndex: index,
        bundleIndex,
      },
      null,
      2,
    ),
  );
}

await main();
