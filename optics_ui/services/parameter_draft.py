"""Isolated parameter configuration drafts, with no file or backend side effects.

``active`` stores the user's configured selection. ``available`` gates it for
the current surface type; an unavailable asphere may retain ``active=True`` so
switching back restores the selection without changing its numeric value.
"""
from copy import deepcopy
import math


class ParameterDraftError(ValueError):
    """A user-editable parameter or lens setting is invalid."""


_UNSET = object()
_SURFACE_TYPES = {"STANDARD", "EVEN_ASPHERE"}


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParameterDraftError(f"{label}: 유한한 숫자를 입력하세요.")
    try:
        valid = math.isfinite(value)
    except (OverflowError, TypeError):
        valid = False
    if not valid:
        raise ParameterDraftError(f"{label}: 유한한 숫자를 입력하세요.")
    return value


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


class ParameterDraft:
    """Validate and edit a deep copy of a revision-bound workspace payload."""

    def __init__(self, payload):
        if not isinstance(payload, dict):
            raise ParameterDraftError("파라미터 설정 형식이 올바르지 않습니다.")
        self._data = deepcopy(payload)
        if not isinstance(self._data.get("revision"), str):
            raise ParameterDraftError("설계 revision이 필요합니다.")
        parameters = self._data.get("parameters")
        lenses = self._data.get("lenses")
        materials = self._data.get("materials")
        if not isinstance(parameters, list) or not isinstance(lenses, list):
            raise ParameterDraftError("파라미터와 렌즈 목록이 필요합니다.")
        if (not isinstance(materials, list) or
                any(not isinstance(m, str) or not m for m in materials) or
                len(set(materials)) != len(materials)):
            raise ParameterDraftError("재질 목록 형식이 올바르지 않습니다.")
        self._lenses = {}
        for lens in lenses:
            if not isinstance(lens, dict) or not _integer(lens.get("index")) or lens["index"] < 0:
                raise ParameterDraftError("렌즈 번호 형식이 올바르지 않습니다.")
            if lens["index"] in self._lenses:
                raise ParameterDraftError("중복 렌즈 번호입니다.")
            if not isinstance(lens.get("surface_type"), str) or lens["surface_type"] not in _SURFACE_TYPES:
                raise ParameterDraftError("지원하지 않는 면 종류입니다.")
            if lens.get("material") not in materials:
                raise ParameterDraftError("현재 렌즈 재질이 재질 목록에 없습니다.")
            self._lenses[lens["index"]] = lens
        self._parameters = {}
        self._capabilities = {}
        for p in parameters:
            self._validate_parameter(p)
            parameter_id = p["id"]
            if parameter_id in self._parameters:
                raise ParameterDraftError(f"중복 파라미터 ID: {parameter_id}")
            self._parameters[parameter_id] = p
            numeric = p["value"] is not None
            hidden_by_standard = (p.get("coefficient", False) and numeric and
                                  self._lenses[p["lens_index"]]["surface_type"] == "STANDARD")
            self._capabilities[parameter_id] = p["available"] or hidden_by_standard
        self._refresh_availability()

    def _validate_parameter(self, p):
        if not isinstance(p, dict):
            raise ParameterDraftError("파라미터 형식이 올바르지 않습니다.")
        for key in ("id", "label", "group", "unit"):
            if not isinstance(p.get(key), str) or (key == "id" and not p[key]):
                raise ParameterDraftError(f"파라미터 {key} 형식이 올바르지 않습니다.")
        if p.get("kind") != "number":
            raise ParameterDraftError("수치 파라미터만 범위를 편집할 수 있습니다.")
        if type(p.get("active")) is not bool or type(p.get("available")) is not bool:
            raise ParameterDraftError(f"{p['label']}: 활성 상태는 boolean이어야 합니다.")
        if type(p.get("coefficient", False)) is not bool:
            raise ParameterDraftError(f"{p['label']}: 계수 표시 형식이 올바르지 않습니다.")
        if "lens_index" in p and (not _integer(p["lens_index"]) or p["lens_index"] not in self._lenses):
            raise ParameterDraftError(f"{p['label']}: 존재하지 않는 렌즈입니다.")
        if p.get("coefficient", False) and "lens_index" not in p:
            raise ParameterDraftError(f"{p['label']}: 면 계수의 렌즈 번호가 필요합니다.")
        if any(key not in p for key in ("min", "max", "value")):
            raise ParameterDraftError(f"{p['label']}: 범위와 현재값이 필요합니다.")
        values = [p["min"], p["max"], p["value"]]
        if all(value is None for value in values):
            if p["available"] or p["active"]:
                raise ParameterDraftError(f"{p['label']}: 미제공 값은 활성화할 수 없습니다.")
            return
        for key in ("min", "max", "value"):
            _finite(p[key], p["label"])
        if p["min"] >= p["max"]:
            raise ParameterDraftError(f"{p['label']}: Min은 Max보다 작아야 합니다.")
        if not p["min"] <= p["value"] <= p["max"]:
            raise ParameterDraftError(f"{p['label']}: 현재값이 Min–Max 범위를 벗어났습니다.")

    def _parameter(self, parameter_id):
        try:
            return self._parameters[parameter_id]
        except (KeyError, TypeError) as exc:
            raise ParameterDraftError("존재하지 않는 파라미터입니다.") from exc

    def _lens(self, lens_index):
        if not _integer(lens_index) or lens_index not in self._lenses:
            raise ParameterDraftError("존재하지 않는 렌즈입니다.")
        return self._lenses[lens_index]

    def _refresh_availability(self):
        for p in self._parameters.values():
            supported = self._capabilities[p["id"]]
            if p.get("coefficient", False):
                supported = supported and self._lenses[p["lens_index"]]["surface_type"] == "EVEN_ASPHERE"
            p["available"] = bool(supported)

    def snapshot(self):
        return deepcopy(self._data)

    def set_numeric(self, parameter_id, *, minimum=_UNSET, maximum=_UNSET, value=_UNSET):
        p = self._parameter(parameter_id)
        if not p["available"]:
            raise ParameterDraftError(f"{p['label']}: 현재 면 종류에서 편집할 수 없습니다.")
        lo = p["min"] if minimum is _UNSET else _finite(minimum, "Min")
        hi = p["max"] if maximum is _UNSET else _finite(maximum, "Max")
        current = p["value"] if value is _UNSET else _finite(value, "Current")
        if lo >= hi:
            raise ParameterDraftError(f"{p['label']}: Min은 Max보다 작아야 합니다.")
        p.update(min=lo, max=hi, value=max(lo, min(hi, current)))

    def set_active(self, parameter_id, active):
        p = self._parameter(parameter_id)
        if type(active) is not bool:
            raise ParameterDraftError("활성 상태는 boolean이어야 합니다.")
        if not p["available"]:
            raise ParameterDraftError(f"{p['label']}: 현재 면 종류에서 활성화할 수 없습니다.")
        p["active"] = active

    def set_surface_type(self, lens_index, surface_type):
        lens = self._lens(lens_index)
        if not isinstance(surface_type, str) or surface_type not in _SURFACE_TYPES:
            raise ParameterDraftError("Standard와 Even Asphere만 지원합니다.")
        lens["surface_type"] = surface_type
        self._refresh_availability()

    def set_material(self, lens_index, material):
        lens = self._lens(lens_index)
        if material not in self._data["materials"]:
            raise ParameterDraftError("선택 가능한 재질을 지정하세요.")
        lens["material"] = material
