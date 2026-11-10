// Single source of truth for commit headers and PR titles. CI installs
// commitlint from pnpm-lock.yaml (.github/workflows/pr-name.yml and
// commitlint.yml). The same check locally, with the Node version in .nvmrc:
//
//   pnpm install --frozen-lockfile
//   printf '%s\n' "fix(maya): keep the selection" | pnpm exec commitlint --verbose

// U+2014 written as a code point so that this file contains no em dash itself.
const EM_DASH = String.fromCharCode(0x2014);

/** @type {import('@commitlint/types').Plugin} */
const houseRules = {
  rules: {
    // House style: no em dashes anywhere, commit messages and PR titles included.
    "no-em-dash": ({ raw }) => [
      !(raw ?? "").includes(EM_DASH),
      "no em dashes in commit messages or PR titles (house style)",
    ],
  },
};

/** @type {import('@commitlint/types').UserConfig} */
export default {
  extends: ["@commitlint/config-conventional"],
  plugins: [houseRules],
  rules: {
    // The PR template allows 120 characters, more than the 100 default.
    "header-max-length": [2, "always", 120],
    // Off: long URLs and Co-Authored-By trailers exceed the 100-character default.
    "body-max-line-length": [0, "always", 200],
    "footer-max-line-length": [0, "always", 200],
    // Off: Maya, GLB, FBX, UV and model names start many subjects.
    "subject-case": [0],
    // AGENTS.md asks for a scope: warn when there is none, never fail.
    "scope-empty": [1, "never"],
    // The scopes AGENTS.md lists (Commits and pull requests).
    "scope-enum": [
      2,
      "always",
      [
        "core", // scripts/scenario_maya/core/: no Maya import
        "maya", // scripts/scenario_maya/maya/, plug-ins/ and the installer
        "ui", // scripts/scenario_maya/ui/: the PySide6 panel
        "agent", // scripts/scenario_maya/agent/: the local MCP server
        "lanes", // lane definitions, models, quick picks and presets
        "docs", // README.md, docs/
        "tools", // tools/
        "tests", // test harness only; a test for a product area keeps the product scope
        "ci", // .github/workflows
        "deps", // pins: actions, Python test tools, npm
        "release", // version fields, CHANGELOG.md, release ZIP
        "repo", // LICENSE, community files, templates, CODEOWNERS, editor and lint configs
      ],
    ],
    "no-em-dash": [2, "always"],
  },
};
