# Maintainer publishing checklist

This snapshot is isolated from the primary research/development project. Do not copy changes back automatically.

Branch: `feedback/windows-preview`; baseline branch: `main`.
Suggested repository: `Dive-deep/optics-studio-feedback` (verify availability before creation).

The following external steps require a valid GitHub CLI login and the owner's chosen repository visibility. At preparation time the old CLI login was invalid; repository creation/upload must not be reported as done until verified.

1. Finish `gh auth login --hostname github.com --git-protocol https --web` using the owner's account. Never place credentials in this repository.
2. Create a new, empty repository with the chosen visibility. Do not reuse an unrelated existing repository.
3. Set `repositoryURL` in `guide/dist/guide.js` to the verified new repository URL. Add a visible guide URL to README after Pages deploys.
4. Rebuild and verify the feedback ZIP after any content change: `python scripts/build_feedback_release.py`.
5. Commit only this isolated source tree, push `main` and `feedback/windows-preview`, and set the default branch to `feedback/windows-preview`.
6. Run Windows source preview checks and inspect the actual result. Fix failures here, never in the primary development folder. Server CI passing is not physical Windows 11 validation.
7. Create a prerelease `v0.1.0-feedback.1` targeting the feedback branch. Attach the source-only ZIP and SHA256SUMS. Do not attach any Python environment or wheel cache.
8. Enable GitHub Pages with Actions source and deploy only `guide/dist`. For private repositories, check the account's supported Pages visibility before publishing; the offline guide remains usable regardless.
9. Verify the repository, prerelease asset, guide URL, and issue templates are accessible as intended. Record URLs and Windows run status in VALIDATION.md.

GitHub Pages deployment grants the workflow only pages/id-token permissions; it uploads the guide directory, not the desktop source or databases. Feedback is collected with Issues templates, not background telemetry.
