import path from "node:path";

export const P0_HORSE_WORKBOOK_BUILD_CONFIG_RELATIVE_PATH = (
  "runtime/horse_profile_completion/p0_horse_workbook_build_config.json"
);

const DEFAULT_INPUT_RELATIVE_PATH = (
  "runtime/horse_profile_completion/pedigree-research-20260719/"
  + "p0_horse_research_50_enriched_v2.json"
);
const DEFAULT_OUTPUT_RELATIVE_PATH = (
  "outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/"
  + "P0马五地区50匹完整解析与字段可用性审核-v2.xlsx"
);
const DEFAULT_PREVIEW_RELATIVE_PATH = (
  "outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/previews-v2"
);
const FROZEN_V1_WORKBOOK_RELATIVE_PATH = (
  "outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/"
  + "P0马五地区50匹完整解析与字段可用性审核.xlsx"
);
const FROZEN_V1_PREVIEW_RELATIVE_PATH = (
  "outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/previews"
);

function configuredPath(root, value, fallback, label) {
  const selected = value || fallback;
  if (typeof selected !== "string" || selected.trim() !== selected) {
    throw new TypeError(`${label} must be a non-empty path string`);
  }
  return path.resolve(root, selected);
}

function isPathAtOrBelow(candidate, protectedPath) {
  const relative = path.relative(protectedPath, candidate);
  return (
    relative === ""
    || (
      relative !== ".."
      && !relative.startsWith(`..${path.sep}`)
      && !path.isAbsolute(relative)
    )
  );
}

export function resolveP0HorseWorkbookBuildPaths({
  root,
  env = process.env,
  config = {},
}) {
  if (typeof root !== "string" || !path.isAbsolute(root)) {
    throw new TypeError("root must be an absolute path");
  }
  if (config === null || typeof config !== "object" || Array.isArray(config)) {
    throw new TypeError("workbook build config must be an object");
  }

  const inputPath = configuredPath(
    root,
    env.P0_HORSE_WORKBOOK_INPUT || config.input_path,
    DEFAULT_INPUT_RELATIVE_PATH,
    "workbook input",
  );
  const outputPath = configuredPath(
    root,
    env.P0_HORSE_WORKBOOK_OUTPUT || config.output_path,
    DEFAULT_OUTPUT_RELATIVE_PATH,
    "workbook output",
  );
  const previewDir = configuredPath(
    root,
    env.P0_HORSE_WORKBOOK_PREVIEW_DIR || config.preview_dir,
    DEFAULT_PREVIEW_RELATIVE_PATH,
    "workbook preview directory",
  );

  const frozenV1Workbook = path.resolve(
    root,
    FROZEN_V1_WORKBOOK_RELATIVE_PATH,
  );
  const frozenV1Previews = path.resolve(
    root,
    FROZEN_V1_PREVIEW_RELATIVE_PATH,
  );
  if (outputPath === frozenV1Workbook) {
    throw new Error("refusing to overwrite frozen v1 workbook");
  }
  if (
    isPathAtOrBelow(previewDir, frozenV1Previews)
    || isPathAtOrBelow(outputPath, frozenV1Previews)
  ) {
    throw new Error("refusing to overwrite frozen v1 previews");
  }

  return {
    inputPath,
    outputPath,
    previewDir,
  };
}
