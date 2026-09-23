"""Validate Python before importing the Qt desktop dependencies."""
import sys

from .runtime import dependency_install_hint, python_runtime_errors


def main(argv=None):
    errors = python_runtime_errors()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    try:
        from .desktop import main as run_desktop
    except (ImportError, OSError) as error:
        print(f"Cannot load desktop dependencies: {error}. {dependency_install_hint()}", file=sys.stderr)
        return 2
    return run_desktop(argv)


if __name__ == "__main__":
    raise SystemExit(main())
