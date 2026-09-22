# Feedback snapshot validation

Date: 2026-09-22. Scope: separate Windows source preview and static user guide.

## Completed locally

- Python 3.12 / PySide6 6.11.2 on the Mac development host: 133 unit checks passed: existing 114, launcher 11, source-only release builder 8.
- JavaScript domain/controller/session/ray checks: 133 passed.
- New launcher and release builder tests were written first and failed before implementation. The builder tests cover required files, runtime exclusion, path/symlink boundaries, ZIP CRC, repeatable hashes and identical CRLF CMD bytes/ZIP hashes from LF or CRLF source files.
- Static guide checks passed: every local link/anchor and all five screenshots resolve; JavaScript syntax passes. No personal filesystem paths were found in the guide.
- Actual Qt app loaded the bundled synthetic report and target, captured Workspace / 2D / Add Zemax Sim / Update model, and exited successfully. Local asset requests: 16; JavaScript errors: 0; external requests: 0. File dialogs used explicit test paths.
- Guide is plain HTML/CSS/JS with relative assets and no external runtime, tracking or submission code. Navigation does not execute optical workflows.

- The built 47-file source-only ZIP passed CRC / SHA-256 checks. After extracting to a new Unicode-and-space path, the actual Mac Qt app passed all 22 file/scene/Compute integration checks, with zero JavaScript errors and external requests. This checks package completeness, not Windows OS behavior.
- Baseline hashes confirm all 72 copied source files in the primary project remain unchanged.

## Pending external verification

- GitHub Windows CI must actually run before it is recorded as passing. The workflow checks a Windows Server hosted runner, not a physical Windows 11 workstation.
- Windows 11 physical machine, native file chooser/drop, display scaling, local GPU combinations and accessibility review: TBU.
- Surrogate/Zemax/training/Claude workflows and optical performance validation are outside this feedback release.

The primary development directory is unchanged. `snapshot-manifest.json` records the source baseline; release edits are only on `feedback/windows-preview` in this separate repository.
