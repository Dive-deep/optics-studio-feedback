"""Saved-state comparison, independent from widgets and file transports."""
from copy import deepcopy


def _native_comparison(value):
    result = deepcopy(value)
    # Explorer's code pane consumes remaining space automatically. A first
    # visit lays out its formerly hidden widget; that is not a user edit to the
    # file-tree width. Keep complete sizes in saved files, compare intent here.
    layout = result.get('layout', {}) if isinstance(result, dict) else {}
    split = layout.get('explorer_split')
    if isinstance(split, list) and len(split) == 2:
        layout['explorer_split'] = [split[0], 0]
    return result


class UnsavedState:
    def __init__(self):
        self.frontend = None
        self.native = None
        self.draft = ''

    @property
    def initialized(self):
        return isinstance(self.frontend, str) and self.native is not None

    def mark_saved(self, frontend, native, draft):
        if not isinstance(frontend, str):
            raise ValueError('A confirmed renderer fingerprint is required.')
        self.frontend = frontend
        self.native = deepcopy(native)
        self.draft = draft

    def changed(self, frontend, native, draft):
        return (not self.initialized or self.frontend != frontend
                or _native_comparison(self.native) != _native_comparison(native) or self.draft != draft)
