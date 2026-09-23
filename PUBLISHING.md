# Maintainer handoff

Independent repository: https://github.com/Dive-deep/optics-studio-feedback

Default branch: `feedback/windows-preview`. `main` preserves the snapshot before Windows packaging. Do not synchronize changes back to the primary development project automatically.

- GitHub CLI authentication and source upload are complete.
- Windows Python 3.10–3.14 compatibility matrix passed: https://github.com/Dive-deep/optics-studio-feedback/actions/runs/35804703019
- The source-only feedback ZIP is generated with `python scripts/build_feedback_release.py`. It excludes Python/Qt runtimes, virtual environments, tests, research and private artifacts.
- Release target: `v0.1.0-feedback.2`, marked prerelease. Keep ZIP and `SHA256SUMS` together.
- The owner approved Public visibility on 2026-09-22. Repository and Release downloads are public; posting Issues requires a GitHub account.
- GitHub Pages uses the Actions workflow and publishes only `guide/dist`: https://dive-deep.github.io/optics-studio-feedback/
- The offline guide at `guide/dist/index.html` remains included in every release.

Guide changes on the feedback branch trigger `guide-pages.yml`. Wait for the deployment to succeed and verify the page and assets without authentication before sharing a new guide URL. The workflow still skips if the repository is made private in the future.

Feedback is collected through two Issues templates, not background telemetry. Never put credentials in this repository or disable the Chromium sandbox to make a test pass.
