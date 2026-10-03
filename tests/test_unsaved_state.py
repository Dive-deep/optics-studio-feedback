import unittest
from optics_ui.workbench.unsaved import UnsavedState


class UnsavedTests(unittest.TestCase):
    def test_initial_unknown_state_is_not_assumed_saved(self):
        self.assertTrue(UnsavedState().changed('f', {}, ''))

    def test_saved_receipt_is_a_copy_and_later_changes_remain_dirty(self):
        state = UnsavedState()
        native = {'layout': {'width': 1000}, 'report': {'min': 1.0}}
        state.mark_saved('before-dialog', native, 'saved')
        self.assertFalse(state.changed('before-dialog', {'layout': {'width': 1000}, 'report': {'min': 1}}, 'saved'))
        native['layout']['width'] = 1200
        self.assertTrue(state.changed('before-dialog', native, 'saved'))
        self.assertTrue(state.changed('edited-during-dialog', state.native, 'saved'))
        self.assertTrue(state.changed('before-dialog', state.native, 'new draft'))

    def test_failed_save_cannot_become_a_clean_baseline(self):
        state = UnsavedState()
        state.mark_saved('old', {}, '')
        with self.assertRaises(ValueError):
            state.mark_saved(None, {}, '')
        self.assertTrue(state.changed('new', {}, ''))


if __name__ == '__main__':
    unittest.main()
