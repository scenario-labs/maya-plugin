# Releasing

Releases are made by `.github/workflows/release-please.yml`, which follows photoshop-plugin's release workflow. Nobody edits version fields, edits the release-please entries of `CHANGELOG.md`, creates a tag or publishes a release by hand.

## How a release happens

1. Pull requests are squash-merged with a Conventional Commit title (`commitlint.config.mjs`). That title is what the changelog says.
2. On each push to `main`, release-please keeps one pull request open, **chore(release): release maya-plugin X.Y.Z**. It sets the next version in `pyproject.toml`, `ScenarioForMaya/scripts/scenario_maya/__init__.py` and `ScenarioForMaya.mod`, and writes the changelog entry above "Hand-written history" in `CHANGELOG.md`. Before 1.0, a `feat` raises the minor version and anything else the patch; a `Release-As: X.Y.Z` footer in a commit sets the version.
3. Merging that pull request is the decision to release. The same workflow run then:
   - creates a draft release targeting the release commit;
   - builds `scenario-maya-X.Y.Z.zip` from that commit with `tools/package.py` (the module, `install_scenario.py`, the licence, and the SDK unpacked from the wheels pinned in `tools/sdk_wheels.json`);
   - checks it with `tools/release/check_package.py`: every file byte for byte against the commit, the version, and a `pydantic_core` build for each Python and platform Maya runs on;
   - writes `SHA256SUMS`, attests the ZIP and the checksums, and attaches them with the Sigstore bundle `scenario-maya-X.Y.Z.sigstore.json`;
   - adds a Contributors section to the notes (`tools/release/contributors.py`; never blocks the release);
   - checks the ZIP again on macOS (the same commit must give the same files there);
   - publishes the draft, which creates the tag `maya-plugin-vX.Y.Z`;
   - opens the next release pull request.

   **publish-changelog** (`.github/workflows/publish-changelog.yml`) runs on the published release: see [Public changelog](#public-changelog).

There is no release before the first one: `.release-please-manifest.json` starts at 0.0.0, so the first release is 0.1.0 and its entry covers every commit since the repository started.

Before merging a release pull request, run `tools/test_maya.sh` and `tools/test_maya_gui.sh` on a Mac with Maya (no runner has Maya), install the ZIP the release will build (`python3 tools/package.py`) by dragging `install_scenario.py` onto a viewport, and put the reports under `tests/reports/`.

## What it needs

Set once by an administrator:

- The release GitHub App installed on this repository, and the organization secrets `GH_ACTIONS_TOKEN_RETRIEVER_PUBLIC_REPO_CLIENT_ID` and `GH_ACTIONS_TOKEN_RETRIEVER_PUBLIC_REPO_PRIVATE_KEY` available to it. Without them every run stops at "Retrieve GitHub App token". Pull requests and releases are made with the App's token because GitHub starts no workflow from an event made with `GITHUB_TOKEN`: the release pull request would get no CI.
- A tag ruleset on `maya-plugin-v*` that only the App can bypass.
- Immutable releases, once the first release is published and checked.
- The secret `CHANGELOG_INGEST_SECRET` available to this repository (an organization secret, as for photoshop-plugin), and `maya-plugin` known to the changelog ingest of www.scenario.com as a source in the Plugins group. Without the secret publish-changelog fails; without the source the ingest answers HTTP 400.

## Check a release

```sh
gh release download maya-plugin-vX.Y.Z --repo scenario-labs/maya-plugin
sha256sum -c SHA256SUMS
gh attestation verify scenario-maya-X.Y.Z.zip --repo scenario-labs/maya-plugin
```

## Public changelog

`.github/workflows/publish-changelog.yml`, as in photoshop-plugin, posts the notes of each published stable release to the changelog of www.scenario.com, where they show under Plugins. It runs on `release: published` (the publish job flips the draft with the App's token, so the event starts it) or by hand with a published tag (Actions > publish-changelog > Run workflow). Notes with no `### ` section post nothing.

It checks the answer for this release's version, since an HTTP 200 alone can carry a processing error. `queued` means accepted for processing, which is asynchronous; `already exists` means the version was received before, not that it shows. Either way, check that the entry appears at [scenario.com/changelog](https://www.scenario.com/changelog). After a timeout or an ingest error, check the changelog and the run before re-running: the workflow never posts twice by itself nor asks for an overwrite.

## Site

`.github/workflows/pages.yml` publishes https://maya.scenario.com after each release, on changes to the docs, and by hand, through [scenario-labs/plugin-site](https://github.com/scenario-labs/plugin-site), the site tooling the plug-ins share: the handbook built from the newest published release's docs (chapters in `handbook.config.json`), its pictures under `/media/`, and the release's ZIP under `/download/` with `download/latest.json`. Preview it from a checkout with `npx github:scenario-labs/plugin-site handbook --no-pdf --out build/handbook`. The Vercel project on `tools/site_proxy` holds the domain, forwards every path to GitHub Pages, counts downloads in PostHog and answers `/download/latest`.

Set once by an administrator:

- Repository Settings > Pages: source "GitHub Actions" and no custom domain (one would make Pages redirect the proxy's requests back to it).
- Vercel, Scenario team: project `maya-plugin-site`, Root Directory `tools/site_proxy`, framework Other, no build or install command, production branch `main`, Ignored Build Step `git diff --quiet HEAD^ HEAD -- .`, Web Analytics on, the domain `maya.scenario.com`, and `POSTHOG_PROJECT_TOKEN` (the PostHog project the other plug-ins count downloads in; without it nothing is counted). `POSTHOG_HOST` and `SITE_ORIGIN` are optional. `tools/site_proxy` holds only `vercel.json` and `middleware.ts`: Vercel would serve any other file there instead of forwarding its path.
- DNS for scenario.com (Route 53, scenario-labs/management `lib/dns-records-scenario.com.ts`, as for photoshop.scenario.com): a CNAME `maya` to the target Vercel shows for the domain.

Until then the workflow still publishes to the Pages address, and `/download/latest` exists only behind the proxy.

## When a release run fails

Re-run the failed jobs of that same workflow run (Actions > release-please). A draft has no tag yet, which hides it from release-please, so `tools/release/find_draft.py` hands the draft back to the run of its own commit only; a run for a later push to `main` stops with "Rerun the original release workflow for <sha>" instead of building the draft from newer code. The assets job also refuses to build anything but the release commit, so the attestation always names it. Recovery is tested with fake GitHub answers (`tests/unit/test_release.py`), not on GitHub.
