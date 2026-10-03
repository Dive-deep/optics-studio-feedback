"""Parameter edits are isolated, precise, and independent of backend execution."""
from copy import deepcopy
import math
import unittest

from optics_ui.services.parameter_draft import ParameterDraft, ParameterDraftError


def make_payload(count=18):
    parameters = [
        {"id": f"p{i}", "label": f"Radius {i}", "group": f"Lens {i % 3 + 1}",
         "unit": "mm", "min": 1.0, "max": 10.0, "value": 6.0,
         "active": True, "available": True, "kind": "number", "lens_index": i % 3}
        for i in range(count)
    ]
    parameters.append({"id": "source", "label": "Image plane → L1", "group": "System",
                       "unit": "mm", "min": 1.0, "max": 35.0, "value": 12.5,
                       "active": False, "available": True, "kind": "number"})
    parameters.extend([
        {"id": "a4", "label": "A4", "group": "Lens 1 / Front", "unit": "mm^-3",
         "min": -1e-5, "max": 1e-5, "value": 1.234567890123456e-12,
         "active": True, "available": True, "kind": "number", "lens_index": 0,
         "coefficient": True},
        {"id": "a12", "label": "A12", "group": "Lens 1 / Front", "unit": "mm^-11",
         "min": None, "max": None, "value": None, "active": False,
         "available": False, "kind": "number", "lens_index": 0, "coefficient": True},
    ])
    return {"revision": "design-17", "parameters": parameters,
            "lenses": [{"index": i, "material": "N-BK7", "surface_type": "EVEN_ASPHERE"}
                       for i in range(3)], "materials": ["N-BK7", "N-F2"]}


class ParameterDraftTests(unittest.TestCase):
    def test_input_and_returned_snapshots_are_deeply_isolated(self):
        payload = make_payload()
        before = deepcopy(payload)
        draft = ParameterDraft(payload)
        draft.set_numeric("p0", value=7)
        draft.set_material(0, "N-F2")
        output = draft.snapshot()
        output["parameters"][0]["value"] = 9
        self.assertEqual(payload, before)
        self.assertEqual(draft.snapshot()["parameters"][0]["value"], 7)
        self.assertEqual(output["revision"], "design-17")

    def test_bound_change_clamps_only_edited_parameter(self):
        draft = ParameterDraft(make_payload())
        before = draft.snapshot()["parameters"]
        draft.set_numeric("p0", minimum=8)
        after = draft.snapshot()["parameters"]
        self.assertEqual((after[0]["min"], after[0]["value"], after[0]["max"]), (8, 8, 10))
        self.assertEqual(after[1:], before[1:])
        draft.set_numeric("p0", minimum=2, maximum=3)
        self.assertEqual(draft.snapshot()["parameters"][0]["value"], 3)

    def test_equal_bounds_are_rejected_without_mutation(self):
        draft = ParameterDraft(make_payload())
        before = draft.snapshot()
        with self.assertRaises(ParameterDraftError):
            draft.set_numeric("p0", minimum=4, maximum=4)
        self.assertEqual(draft.snapshot(), before)

    def test_inactive_keeps_current_and_reactivation(self):
        draft = ParameterDraft(make_payload())
        draft.set_numeric("p0", value=7.125)
        draft.set_active("p0", False)
        self.assertEqual(draft.snapshot()["parameters"][0]["value"], 7.125)
        draft.set_active("p0", True)
        self.assertEqual(draft.snapshot()["parameters"][0]["value"], 7.125)

    def test_invalid_edit_is_atomic(self):
        draft = ParameterDraft(make_payload())
        before = draft.snapshot()
        for update in ({"minimum": 12}, {"value": math.inf}, {"value": math.nan},
                       {"value": True}, {"maximum": "10"}):
            with self.subTest(update=update), self.assertRaises(ParameterDraftError):
                draft.set_numeric("p0", **update)
            self.assertEqual(draft.snapshot(), before)

    def test_type_switch_preserves_coefficients_and_previous_activation(self):
        draft = ParameterDraft(make_payload())
        original = next(p for p in draft.snapshot()["parameters"] if p["id"] == "a4")
        draft.set_surface_type(0, "STANDARD")
        standard = next(p for p in draft.snapshot()["parameters"] if p["id"] == "a4")
        self.assertTrue(standard["active"])
        self.assertFalse(standard["available"])
        self.assertEqual(standard["value"], original["value"])
        draft.set_surface_type(0, "EVEN_ASPHERE")
        self.assertEqual(next(p for p in draft.snapshot()["parameters"] if p["id"] == "a4"), original)

    def test_initial_standard_can_enable_supported_coefficients(self):
        payload = make_payload()
        payload["lenses"][0]["surface_type"] = "STANDARD"
        payload["parameters"][-2].update(active=False, available=False)
        draft = ParameterDraft(payload)
        draft.set_surface_type(0, "EVEN_ASPHERE")
        self.assertTrue(draft.snapshot()["parameters"][-2]["available"])
        self.assertFalse(draft.snapshot()["parameters"][-2]["active"])

    def test_placeholder_remains_null_and_uneditable(self):
        draft = ParameterDraft(make_payload())
        for action in (lambda: draft.set_active("a12", True),
                       lambda: draft.set_numeric("a12", value=0)):
            with self.assertRaises(ParameterDraftError):
                action()
        draft.set_surface_type(0, "STANDARD")
        draft.set_surface_type(0, "EVEN_ASPHERE")
        a12 = draft.snapshot()["parameters"][-1]
        self.assertIsNone(a12["value"])
        self.assertFalse(a12["available"])

    def test_scientific_values_preserve_double_precision(self):
        draft = ParameterDraft(make_payload())
        value = 1.234567890123456e-24
        draft.set_numeric("a4", value=value)
        self.assertEqual(draft.snapshot()["parameters"][-2]["value"], value)

    def test_duplicate_ids_and_malformed_input_are_rejected(self):
        for mutate in (
            lambda p: p["parameters"].append(deepcopy(p["parameters"][0])),
            lambda p: p["parameters"][0].update(value=float("nan")),
            lambda p: p["parameters"][0].update(min=11),
            lambda p: p["parameters"][0].update(active="yes"),
            lambda p: p["parameters"][0].update(lens_index=99),
            lambda p: p["lenses"][0].update(surface_type=[]),
        ):
            payload = make_payload()
            mutate(payload)
            with self.subTest(payload=payload), self.assertRaises(ParameterDraftError):
                ParameterDraft(payload)

    def test_unknown_parameter_material_and_type_do_not_mutate_draft(self):
        draft = ParameterDraft(make_payload())
        before = draft.snapshot()
        for action in (lambda: draft.set_numeric("missing", value=2),
                       lambda: draft.set_material(0, "invented"),
                       lambda: draft.set_surface_type(0, "TOROIDAL"),
                       lambda: draft.set_surface_type(0, [])):
            with self.assertRaises(ParameterDraftError):
                action()
            self.assertEqual(draft.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
