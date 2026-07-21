import assert from "node:assert/strict";
import path from "node:path";

import {
  resolveP0HorseWorkbookBuildPaths,
} from "./p0_horse_workbook_build_paths.mjs";

const root = path.resolve("/tmp/umanews-workbook-path-tests");
const defaultPaths = resolveP0HorseWorkbookBuildPaths({
  root,
  env: {},
  config: {},
});

assert.equal(
  defaultPaths.inputPath,
  path.join(
    root,
    "runtime/horse_profile_completion/pedigree-research-20260719/"
      + "p0_horse_research_50_enriched_v2.json",
  ),
);
assert.equal(
  defaultPaths.outputPath,
  path.join(
    root,
    "outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/"
      + "P0马五地区50匹完整解析与字段可用性审核-v2.xlsx",
  ),
);
assert.equal(
  defaultPaths.previewDir,
  path.join(
    root,
    "outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/previews-v2",
  ),
);

const environmentPaths = resolveP0HorseWorkbookBuildPaths({
  root,
  config: {
    input_path: "config/input.json",
    output_path: "config/output.xlsx",
    preview_dir: "config/previews",
  },
  env: {
    P0_HORSE_WORKBOOK_INPUT: "environment/input.json",
    P0_HORSE_WORKBOOK_OUTPUT: "environment/output.xlsx",
    P0_HORSE_WORKBOOK_PREVIEW_DIR: "environment/previews",
  },
});
assert.equal(
  environmentPaths.inputPath,
  path.join(root, "environment/input.json"),
);
assert.equal(
  environmentPaths.outputPath,
  path.join(root, "environment/output.xlsx"),
);
assert.equal(
  environmentPaths.previewDir,
  path.join(root, "environment/previews"),
);

assert.throws(
  () => resolveP0HorseWorkbookBuildPaths({
    root,
    config: {},
    env: {
      P0_HORSE_WORKBOOK_OUTPUT: (
        "outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/"
        + "P0马五地区50匹完整解析与字段可用性审核.xlsx"
      ),
    },
  }),
  /frozen v1 workbook/,
);
assert.throws(
  () => resolveP0HorseWorkbookBuildPaths({
    root,
    config: {},
    env: {
      P0_HORSE_WORKBOOK_PREVIEW_DIR: (
        "outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/previews"
      ),
    },
  }),
  /frozen v1 previews/,
);

console.log("p0 horse workbook build path tests passed");
