"""Wide native parameter configuration; accepted payloads are applied by the host."""
from copy import deepcopy
import math
import sys

from PySide6.QtCore import QLocale, QSize, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHeaderView, QHBoxLayout,
    QLabel, QLineEdit, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from optics_ui.services.parameter_draft import ParameterDraft, ParameterDraftError


def _number_text(value):
    # Python's shortest round-trip representation preserves all stored precision
    # without expanding 1e-5 into visually noisy 1.0000000000000001e-05.
    return "" if value is None else str(value)


class _LensControlsScroll(QScrollArea):
    """Preserve legible lens selectors without imposing their combined width.

    Reserve one horizontal scrollbar row so showing it does not clip controls
    or change the parameter table height on narrow/DPI-scaled displays.
    """

    def sizeHint(self):
        content = self.widget()
        height = content.minimumSizeHint().height() if content is not None else 0
        height += self.horizontalScrollBar().sizeHint().height() + 2 * self.frameWidth()
        return QSize(480, height)

    def minimumSizeHint(self):
        return QSize(120, self.sizeHint().height())


class ParameterDialog(QDialog):
    """Edit a copy; Apply validates before emitting ``accepted``.

    ``result_payload`` returns a detached revision-bound settings payload. The
    host must check that revision before applying it to the live workspace.
    An optional ``commit(payload, callback)`` keeps the dialog open until the
    host confirms success; failures preserve the draft and original revision.
    This widget does not load a model, write files, or execute a backend job.
    """

    def __init__(self, payload, parent=None, *, commit=None):
        super().__init__(parent)
        self._draft = ParameterDraft(payload)
        self._accepted_payload = None
        self._commit = commit
        self._commit_token = None
        self._committing = False
        self._shutting_down = False
        self._busy_controls = []
        self._rows = {}
        self._errors = {}
        self.setWindowTitle("Configure parameters")
        self.setObjectName("parameter-dialog")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        title = QLabel("Parameters & ranges")
        title.setStyleSheet("font-size:18px; font-weight:600;")
        layout.addWidget(title)
        description = QLabel("전체 렌즈와 System의 변수를 선택하세요. 비활성화하면 현재값을 유지합니다.")
        description.setWordWrap(True)
        layout.addWidget(description)

        lens_content = QWidget()
        lens_grid = QGridLayout(lens_content)
        lens_grid.setContentsMargins(0, 0, 0, 0)
        lens_grid.setHorizontalSpacing(12)
        snapshot = self._draft.snapshot()
        for column, lens in enumerate(snapshot["lenses"]):
            index = lens["index"]
            label = QLabel(f"Lens {index + 1} · 양면 공통")
            lens_grid.addWidget(label, 0, column * 2, 1, 2)
            materials = QComboBox()
            materials.setObjectName(f"lens-material-{index}")
            materials.setAccessibleName(f"Lens {index + 1} material")
            materials.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            materials.setMinimumContentsLength(6)
            materials.addItems(snapshot["materials"])
            materials.setCurrentText(lens["material"])
            materials.setToolTip(lens["material"])
            materials.currentTextChanged.connect(materials.setToolTip)
            materials.currentTextChanged.connect(lambda value, i=index: self._material_changed(i, value))
            lens_grid.addWidget(materials, 1, column * 2)
            surface_type = QComboBox()
            surface_type.setObjectName(f"lens-type-{index}")
            surface_type.setAccessibleName(f"Lens {index + 1} surface type for both faces")
            surface_type.addItem("Standard", "STANDARD")
            surface_type.addItem("Even Asphere", "EVEN_ASPHERE")
            surface_type.setCurrentIndex(surface_type.findData(lens["surface_type"]))
            surface_type.currentIndexChanged.connect(lambda _, c=surface_type, i=index: self._type_changed(i, c.currentData()))
            lens_grid.addWidget(surface_type, 1, column * 2 + 1)
        lens_scroll = _LensControlsScroll()
        lens_scroll.setObjectName("lens-controls-scroll")
        lens_scroll.setAccessibleName("Lens material and surface type controls")
        lens_scroll.setFrameShape(QScrollArea.NoFrame)
        lens_scroll.setWidgetResizable(True)
        lens_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lens_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        lens_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lens_scroll.setWidget(lens_content)
        layout.addWidget(lens_scroll)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("parameter-search")
        self.search.setPlaceholderText("파라미터 검색 · radius, thickness, A4 …")
        self.search.setAccessibleName("Search parameters")
        filters.addWidget(self.search, 1)
        self.group_filter = QComboBox()
        self.group_filter.setObjectName("parameter-group-filter")
        self.group_filter.setAccessibleName("Filter parameter group")
        self.group_filter.addItem("All groups", None)
        for group in dict.fromkeys(p["group"] for p in snapshot["parameters"]):
            self.group_filter.addItem(group or "System", group)
        filters.addWidget(self.group_filter)
        self.visible_count = QLabel()
        filters.addWidget(self.visible_count)
        layout.addLayout(filters)

        self.table = QTableWidget(len(snapshot["parameters"]), 7)
        self.table.setObjectName("parameter-table")
        self.table.setHorizontalHeaderLabels(["Use", "Parameter", "Unit", "Min", "Current", "Max", "Training support"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(29)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setStyleSheet("QLineEdit:disabled {color:#858a94;background:#eef0f3;} QTableWidget {gridline-color:#e1e5ec;}")
        header = self.table.horizontalHeader()
        for column, width in enumerate((46, 260, 68, 155, 155, 155, 150)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for row, parameter in enumerate(snapshot["parameters"]):
            self._create_row(row, parameter)
        self.search.textChanged.connect(self._filter_rows)
        self.group_filter.currentIndexChanged.connect(self._filter_rows)
        self._filter_rows()
        layout.addWidget(self.table, 1)

        self.error_label = QLabel("")
        self.error_label.setTextFormat(Qt.PlainText)
        self.error_label.setObjectName("parameter-error")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#b42318;")
        self.error_label.setMinimumHeight(18)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setObjectName("apply-parameters")
        self.apply_button.setText("Apply")
        self.apply_button.clicked.connect(self.accept)
        self.apply_button.setDefault(True)
        cancel = buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button = cancel
        cancel.setObjectName("cancel-parameters")
        cancel.setText("Cancel")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        screen = parent.screen() if parent is not None else self.screen()
        available = screen.availableGeometry()
        self.resize(min(1100, max(320, available.width() - 32)),
                    min(680, max(300, available.height() - 32)))
        self.setSizeGripEnabled(True)

    def _filter_rows(self, *_):
        text = self.search.text().strip().casefold()
        group = self.group_filter.currentData()
        visible = 0
        for row, parameter in enumerate(self._draft.snapshot()["parameters"]):
            matches = (group is None or parameter["group"] == group)
            matches = matches and text in " ".join(parameter[key] for key in ("id", "label", "group", "unit")).casefold()
            self.table.setRowHidden(row, not matches)
            visible += matches
        self.visible_count.setText(f"{visible} / {self.table.rowCount()}")

    def _create_row(self, row, p):
        parameter_id = p["id"]
        active = QCheckBox()
        active.setObjectName(f"parameter-active-{parameter_id}")
        active.setAccessibleName(f"Activate {p['group']} {p['label']}")
        container = QWidget()
        check_layout = QVBoxLayout(container)
        check_layout.setContentsMargins(10, 0, 0, 0)
        check_layout.addWidget(active)
        self.table.setCellWidget(row, 0, container)
        label = QTableWidgetItem(f"{p['group']} · {p['label']}" if p["group"] else p["label"])
        label.setToolTip(label.text())
        self.table.setItem(row, 1, label)
        self.table.setItem(row, 2, QTableWidgetItem(p["unit"]))
        support = QTableWidgetItem("학습영역 연결 전")
        support.setToolTip("선택 모델의 조건부 학습영역이 연결되면 표시합니다. 현재 수치를 추정하지 않습니다.")
        self.table.setItem(row, 6, support)
        controls = {"active": active, "row": row}
        for column, key in ((3, "min"), (4, "value"), (5, "max")):
            edit = QLineEdit(_number_text(p[key]))
            edit.setObjectName(f"parameter-{key}-{parameter_id}")
            edit.setAccessibleName(f"{p['group']} {p['label']} {key}")
            edit.setAlignment(Qt.AlignRight)
            edit.setMinimumWidth(95)
            validator = QDoubleValidator(-sys.float_info.max, sys.float_info.max, 100, edit)
            validator.setNotation(QDoubleValidator.ScientificNotation)
            locale = QLocale.c()
            locale.setNumberOptions(QLocale.RejectGroupSeparator)
            validator.setLocale(locale)
            edit.setValidator(validator)
            edit.editingFinished.connect(lambda pid=parameter_id: self._commit_row(pid))
            self.table.setCellWidget(row, column, edit)
            controls[key] = edit
        self._rows[parameter_id] = controls
        active.toggled.connect(lambda checked, pid=parameter_id: self._active_changed(pid, checked))
        self._refresh_row(p)

    def _refresh_row(self, p, *, update_numbers=True):
        controls = self._rows[p["id"]]
        available = p["available"]
        effective_active = available and p["active"]
        check = controls["active"]
        check.blockSignals(True)
        check.setChecked(effective_active)
        check.setEnabled(available)
        check.blockSignals(False)
        for key in ("min", "value", "max"):
            edit = controls[key]
            edit.setEnabled(effective_active)
            if update_numbers:
                edit.setText(_number_text(p[key]))
            edit.setToolTip("미제공 값" if p[key] is None else "" if available else "현재 면 종류에서는 고정·미사용")

    def _show_errors(self):
        self.error_label.setText(next(iter(self._errors.values()), ""))

    def _commit_row(self, parameter_id):
        controls = self._rows[parameter_id]
        p = next(p for p in self._draft.snapshot()["parameters"] if p["id"] == parameter_id)
        if not p["available"] or not p["active"]:
            return True
        try:
            values = {}
            for key in ("min", "value", "max"):
                raw = controls[key].text().strip()
                if not raw:
                    raise ParameterDraftError(f"{p['label']}: Min, Current, Max를 입력하세요.")
                try:
                    values[key] = float(raw)
                except ValueError as exc:
                    raise ParameterDraftError(f"{p['label']}: 유효한 숫자를 입력하세요.") from exc
                if not math.isfinite(values[key]):
                    raise ParameterDraftError(f"{p['label']}: 유한한 숫자를 입력하세요.")
            self._draft.set_numeric(parameter_id, minimum=values["min"],
                                    maximum=values["max"], value=values["value"])
        except ParameterDraftError as exc:
            self._errors[parameter_id] = str(exc)
            self._show_errors()
            return False
        self._errors.pop(parameter_id, None)
        updated = next(p for p in self._draft.snapshot()["parameters"] if p["id"] == parameter_id)
        self._refresh_row(updated)
        self._show_errors()
        return True

    def _active_changed(self, parameter_id, checked):
        if not self._commit_row(parameter_id):
            self._rows[parameter_id]["active"].blockSignals(True)
            self._rows[parameter_id]["active"].setChecked(not checked)
            self._rows[parameter_id]["active"].blockSignals(False)
            return
        self._draft.set_active(parameter_id, checked)
        p = next(p for p in self._draft.snapshot()["parameters"] if p["id"] == parameter_id)
        self._refresh_row(p)

    def _material_changed(self, lens_index, material):
        self._draft.set_material(lens_index, material)

    def _type_changed(self, lens_index, surface_type):
        # Commit valid edits before type gating; invalid text remains visible
        # and prevents Apply rather than being silently discarded.
        for p in self._draft.snapshot()["parameters"]:
            if p.get("lens_index") == lens_index and not self._commit_row(p["id"]):
                combo = self.findChild(QComboBox, f"lens-type-{lens_index}")
                previous = next(l for l in self._draft.snapshot()["lenses"] if l["index"] == lens_index)
                combo.blockSignals(True)
                combo.setCurrentIndex(combo.findData(previous["surface_type"]))
                combo.blockSignals(False)
                return
        self._draft.set_surface_type(lens_index, surface_type)
        for p in self._draft.snapshot()["parameters"]:
            if p.get("lens_index") == lens_index:
                self._refresh_row(p)

    def accept(self):
        if self._committing or self._shutting_down:
            return
        valid = True
        for parameter_id in self._rows:
            if not self._commit_row(parameter_id):
                valid = False
        if not valid or self._errors:
            self._show_errors()
            return
        payload = self._draft.snapshot()
        if self._commit is None:
            self._accepted_payload = payload
            super().accept()
            return
        token = object()
        self._commit_token = token
        self._set_committing(True)
        self.error_label.setText("적용 결과를 확인하고 있습니다. 완료될 때까지 잠시 기다려 주세요.")
        def completed(ok, result):
            if self._shutting_down or self._commit_token is not token:
                return
            self._commit_token = None
            self._set_committing(False)
            if ok:
                self._accepted_payload = deepcopy(payload)
                super(ParameterDialog, self).accept()
            else:
                self._accepted_payload = None
                message = result.get("message", "적용 결과를 확인하지 못했습니다.") if isinstance(result, dict) else str(result or "적용 결과를 확인하지 못했습니다.")
                self.error_label.setText(message + "\n입력한 값은 보존했습니다. 작업대가 변경된 경우 값을 검토한 뒤 창을 닫고 다시 여세요.")
        try:
            self._commit(deepcopy(payload), completed)
        except Exception as error:
            completed(False, {"message": f"Parameter request failed: {error}"})

    def _set_committing(self, busy):
        self._committing = busy
        if busy:
            controls = [self.table, self.search, *self.findChildren(QComboBox), self.apply_button, self.cancel_button]
            self._busy_controls = [(widget, widget.isEnabled()) for widget in controls]
            for widget, _ in self._busy_controls:
                widget.setEnabled(False)
        else:
            for widget, enabled in self._busy_controls:
                widget.setEnabled(enabled)
            self._busy_controls = []

    def reject(self):
        if self._committing:
            self.error_label.setText("변경 사항의 적용 결과를 확인 중입니다. 완료 후 닫을 수 있습니다.")
            return
        super().reject()

    def closeEvent(self, event):
        if self._committing:
            event.ignore()
            self.error_label.setText("변경 사항의 적용 결과를 확인 중입니다. 완료 후 닫을 수 있습니다.")
            return
        super().closeEvent(event)

    def close_for_shutdown(self):
        """Abandon this UI on parent shutdown; never claim to roll back a request."""
        self._shutting_down = True
        self._commit_token = None
        self._committing = False
        self._commit = None
        super().reject()

    def result_payload(self):
        return deepcopy(self._accepted_payload) if self._accepted_payload is not None else self._draft.snapshot()
