# Maintainer handoff

Independent repository: https://github.com/Dive-deep/optics-studio-feedback

Default branch: `feedback/windows-preview`. `main` preserves the snapshot before Windows packaging. Do not synchronize changes back to the primary development project automatically.

- GitHub CLI authentication and source upload are complete.
- Windows verification passed: https://github.com/Dive-deep/optics-studio-feedback/actions/runs/35732824991
- The source-only feedback ZIP is generated with `python scripts/build_feedback_release.py`. It excludes Python/Qt runtimes, virtual environments, tests, research and private artifacts.
- Release target: `v0.1.0-feedback.1`, marked prerelease. Keep ZIP and `SHA256SUMS` together.
- Repository visibility is currently Private pending the owner's explicit Public/Private choice. Private downloads and Issues are limited to authorized collaborators.
- GitHub Pages workflow intentionally skips while the repository is private. The offline guide at `guide/dist/index.html` remains included in every release.

If the owner chooses Public, change visibility, enable Pages with Actions source, dispatch `guide-pages.yml` on the feedback branch, wait for the deployment to succeed, and verify its URL and assets. Only `guide/dist` is uploaded by Pages. Then add the verified guide URL to README and repository About.

Feedback is collected through two Issues templates, not background telemetry. Never put credentials in this repository or disable the Chromium sandbox to make a test pass.
