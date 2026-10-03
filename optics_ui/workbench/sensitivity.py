"""Native Sobol report matrix and selected-output bars; no computation backend."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from optics_ui.services.sensitivity import (
    DEFAULT_OUTPUTS, SensitivityError, context_hash, load_sensitivity_report,
    validate_panel_snapshot,
)


def _label(text=""):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    return result


def _unknown(status="not_computed"):
    return {"estimate": None, "ci_low": None, "ci_high": None, "status": status}


def _parameter_label(parameter):
    """Identify repeated optical controls without changing their stored labels."""
    label = parameter.get("label", parameter["id"])
    group = parameter.get("group")
    return f"{group} · {label}" if isinstance(group, str) and group.strip() else label


def _tip(cell, output, parameter, marginal=None):
    value = cell["estimate"]
    low, high = cell["ci_low"], cell["ci_high"]
    text = [f'{output["label"]} [{output["unit"]}]',
            f'{_parameter_label(parameter)} [{parameter.get("unit", "")}]',
            f'Input ID: {parameter["id"]}',
            f'Index: {"unavailable" if value is None else format(value, ".8g")}',
            "CI: unavailable" if low is None else f"CI: [{low:.8g}, {high:.8g}]",
            f'Status: {cell["status"]}']
    if marginal:
        text.append("Distribution: " + json.dumps(marginal, ensure_ascii=False))
    if output.get("conditions"):
        text.append("Output conditions: " + json.dumps(output["conditions"], ensure_ascii=False))
    if value is not None and not 0 <= value <= 1:
        text.append("Warning: raw estimate outside [0, 1]; not clipped.")
    text.append("CI describes estimator sampling uncertainty, not surrogate accuracy.")
    return "\n".join(text)


class SobolBars(QWidget):
    """Paint exact signed estimates/CI endpoints; unknown is distinct from zero."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = []
        self._rows = []
        self.setMinimumWidth(280)
        self.setMouseTracking(True)

    def set_rows(self, rows):
        self._rows = rows
        self.values = [r["cell"]["estimate"] for r in rows]
        self.setMinimumHeight(max(145, 35 + len(rows) * 25))
        self.update()

    def mouseMoveEvent(self, event):
        index = int((event.position().y() - 26) // 25)
        self.setToolTip(self._rows[index]["tooltip"] if 0 <= index < len(self._rows) else "")
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        if not self._rows:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No independent inputs")
            return
        values = [0., 1.]
        for row in self._rows:
            values.extend(v for k, v in row["cell"].items()
                          if k in {"estimate", "ci_low", "ci_high"} and v is not None)
        minimum, maximum = min(values), max(values)
        # Scale before subtraction to avoid overflow for valid large finite estimates.
        scale = max(1., abs(minimum), abs(maximum))
        lo, hi = minimum / scale, maximum / scale
        left, right = min(132., self.width() * .4), max(180., self.width() - 64.)

        def x(value):
            return left + ((value / scale - lo) / (hi - lo)) * (right - left)

        zero = x(0.)
        painter.setPen(QColor("#94a3b8"))
        painter.drawLine(int(zero), 23, int(zero), self.height() - 6)
        painter.drawText(QRectF(left, 0, 60, 20), Qt.AlignmentFlag.AlignLeft, f"{minimum:.3g}")
        painter.drawText(QRectF(right - 60, 0, 60, 20), Qt.AlignmentFlag.AlignRight, f"{maximum:.3g}")
        metrics = painter.fontMetrics()
        for index, row in enumerate(self._rows):
            y = 26 + index * 25
            painter.setPen(QColor("#334155"))
            label = metrics.elidedText(row["label"], Qt.TextElideMode.ElideRight, int(left - 10))
            painter.drawText(QRectF(0, y, left - 8, 21), Qt.AlignmentFlag.AlignVCenter, label)
            cell = row["cell"]
            value = cell["estimate"]
            if value is None:
                painter.setPen(QColor("#94a3b8"))
                painter.drawText(QRectF(left + 5, y, right - left + 50, 21),
                                 Qt.AlignmentFlag.AlignVCenter, "— unavailable")
                continue
            end = x(value)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#bd7b20" if not 0 <= value <= 1 else "#378fa3"))
            painter.drawRoundedRect(QRectF(min(zero, end), y + 4, max(2., abs(end - zero)), 13), 3, 3)
            if cell["ci_low"] is not None:
                a, b = x(cell["ci_low"]), x(cell["ci_high"])
                painter.setPen(QPen(QColor("#334155"), 1.3))
                painter.drawLine(int(a), y + 10, int(b), y + 10)
                for edge in (a, b):
                    painter.drawLine(int(edge), y + 5, int(edge), y + 15)
            painter.setPen(QColor("#334155"))
            painter.drawText(QRectF(right + 6, y, 57, 21), Qt.AlignmentFlag.AlignVCenter, f"{value:.3g}")


class SensitivityPanel(QWidget):
    """Import-only panel. Failed import/restore leaves the current result intact.

    snapshot embeds a validated report, not a filesystem promise. restore does
    not restore the workspace context: the caller sets that context, and stale
    status is always derived from it rather than trusted from saved state.
    """
    statusMessage = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._context = {}
        self._context_hash = context_hash(self._context)
        self._context_error = None
        self._report = None
        self._report_path = None
        self._outputs = []
        self._inputs = []
        self._cells = []
        self._marginals = {}
        self.setObjectName("sensitivityPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        header = QHBoxLayout()
        title = _label("Sensitivity matrix")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(_label("Sobol indices"))
        self.index_combo = QComboBox()
        self.index_combo.setObjectName("sobolIndexCombo")
        self.index_combo.addItem("S1 · First order", "S1")
        self.index_combo.addItem("ST · Total order", "ST")
        self.index_combo.setToolTip("S1: main effect. ST: includes interactions; its row sum is not normalized.")
        header.addWidget(self.index_combo)
        self.import_button = QPushButton("Import report…")
        self.import_button.setObjectName("sobolImportButton")
        header.addWidget(self.import_button)
        self.clear_button = QPushButton("Clear report")
        self.clear_button.setObjectName("sobolClearButton")
        self.clear_button.setToolTip("Unload the displayed report. The source file and current design are preserved.")
        self.clear_button.clicked.connect(self.clear_report)
        header.addWidget(self.clear_button)
        self.calculate_button = QPushButton("Calculate · TBU")
        self.calculate_button.setEnabled(False)
        self.calculate_button.setToolTip("Evaluator integration is unavailable. No Sobol calculation or DB inference runs.")
        header.addWidget(self.calculate_button)
        layout.addLayout(header)
        self.status_label = _label()
        self.status_label.setObjectName("sobolStatus")
        layout.addWidget(self.status_label)
        self.provenance_label = _label()
        self.provenance_label.setObjectName("sobolProvenance")
        self.provenance_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.provenance_label)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget()
        self.table.setObjectName("sobolMatrix")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(185)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(94)
        self.table.verticalHeader().setDefaultSectionSize(26)
        splitter.addWidget(self.table)
        bars = QWidget()
        bars_layout = QVBoxLayout(bars)
        bars_layout.setContentsMargins(9, 0, 0, 0)
        self.response_label = _label()
        self.response_label.setStyleSheet("font-weight: 600;")
        bars_layout.addWidget(self.response_label)
        self.chart = SobolBars()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.chart)
        bars_layout.addWidget(scroll)
        splitter.addWidget(bars)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        self.interpretation_label = _label(
            "Variance contribution over the declared distribution; no increase/decrease direction. "
            "Missing ≠ 0. CI is estimator uncertainty, not model accuracy. ST sums are not normalized.")
        self.interpretation_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.interpretation_label)
        self.index_combo.currentIndexChanged.connect(self._refresh)
        self.table.currentCellChanged.connect(self._select_response)
        self.import_button.clicked.connect(self._choose_report)
        self._refresh()

    def set_context(self, context: dict):
        try:
            new_hash = context_hash(context)
        except SensitivityError as exc:
            self._context_error = exc.message
            self._refresh()
            self.statusMessage.emit(f"Sensitivity context rejected: {exc.message}")
            return False
        recovered = self._context_error is not None
        self._context_error = None
        if self._context_hash == new_hash and not recovered:
            return True
        self._context = copy.deepcopy(context)
        self._context_hash = new_hash
        self._refresh()
        return True

    def load_report(self, path) -> bool:
        try:
            candidate = load_sensitivity_report(path)
            candidate_path = str(Path(path).resolve())
        except (SensitivityError, OSError, ValueError, TypeError) as exc:
            self.statusMessage.emit(f"Sensitivity report rejected: {getattr(exc, 'message', 'Invalid report path.')}")
            return False
        self._report, self._report_path = candidate, candidate_path
        self._refresh()
        self.statusMessage.emit("Sobol report imported. " + self.status_label.text())
        return True

    def _choose_report(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Sobol sensitivity report", "", "Sobol report (*.json)")
        if path:
            self.load_report(path)

    def clear_report(self):
        self._report = None
        self._report_path = None
        self._refresh()
        self.statusMessage.emit("Sensitivity report unloaded; source file and design preserved.")

    def _stale(self):
        return self._report is not None and (self._context_error is not None or
                                            self._report["study"]["context_hash"] != self._context_hash)

    def snapshot(self) -> dict:
        row = self.table.currentRow()
        return validate_panel_snapshot({"format": "optics-sensitivity-panel", "schema_version": 1,
                "report": copy.deepcopy(self._report), "report_path": self._report_path,
                "metric": self.index_combo.currentData(),
                "output_id": self._outputs[row]["id"] if 0 <= row < len(self._outputs) else None,
                "stale": self._stale()})

    def restore(self, snapshot: dict) -> bool:
        try:
            candidate = validate_panel_snapshot(snapshot)
        except (SensitivityError, TypeError) as exc:
            self.statusMessage.emit(f"Sensitivity restore rejected: {getattr(exc, 'message', 'Invalid snapshot.')}")
            return False
        self._report = candidate["report"]
        self._report_path = candidate.get("report_path")
        self.index_combo.blockSignals(True)
        self.index_combo.setCurrentIndex(0 if candidate["metric"] == "S1" else 1)
        self.index_combo.blockSignals(False)
        self._refresh(selected=candidate.get("output_id"))
        return True

    def request_preview(self) -> dict:
        """Typed future request only; no distribution or execution is invented."""
        if self._context_error is not None:
            return {"schema_version": 1, "method": "sobol_sensitivity", "status": "unavailable",
                    "reason": "invalid_context", "message": self._context_error, "executed": False,
                    "context_hash": None, "context": None, "outputs": copy.deepcopy(list(DEFAULT_OUTPUTS)),
                    "distribution": None, "sampling": None}
        return {"schema_version": 1, "method": "sobol_sensitivity", "status": "unavailable",
                "reason": "evaluator_not_connected", "executed": False,
                "context_hash": context_hash(self._context), "context": copy.deepcopy(self._context),
                "outputs": copy.deepcopy(list(DEFAULT_OUTPUTS)), "distribution": None, "sampling": None}

    def _refresh(self, *_args, selected=None):
        self.clear_button.setEnabled(self._report is not None)
        if selected is None and self._outputs and 0 <= self.table.currentRow() < len(self._outputs):
            selected = self._outputs[self.table.currentRow()]["id"]
        self._outputs = copy.deepcopy(list(DEFAULT_OUTPUTS))
        report_rows = {}
        self._marginals = {}
        if self._report:
            self._inputs = self._report["inputs"]
            report_rows = {row["id"]: i for i, row in enumerate(self._report["outputs"])}
            for i, output in enumerate(self._outputs):
                if output["id"] in report_rows:
                    self._outputs[i] = self._report["outputs"][report_rows[output["id"]]]
            known = {row["id"] for row in self._outputs}
            self._outputs.extend(row for row in self._report["outputs"] if row["id"] not in known)
            self._marginals = {m["input_id"]: m for m in self._report["distribution"]["marginals"]}
            stale = self._stale()
            count = len(self._report["warnings"])
            self.status_label.setText(
                ("Stale · current context cannot be validated. Report retained for reference. " + self._context_error
                 if self._context_error is not None else
                 "Stale · workspace settings differ from this report. Retained for reference. " if stale
                 else "Imported report · context matches. Producer claims are not independently verified. ")
                + (f"{count} estimator warning(s)." if count else ""))
            self.status_label.setStyleSheet("color: #9a6700;" if stale or count else "color: #286575;")
            evaluator, origin = self._report["evaluator"], self._report["origin"]
            self.provenance_label.setText(
                f'{origin["kind"]} · {evaluator["kind"]}: {evaluator["id"]} / {evaluator["version"]} · '
                f'Study {self._report["study"]["id"]}')
            self.provenance_label.setToolTip(json.dumps({key: self._report[key] for key in
                ("origin", "evaluator", "conditions", "distribution", "sampling", "warnings")},
                ensure_ascii=False, indent=2))
        else:
            raw = self._context.get("parameters", [])
            self._inputs = [p for p in raw if isinstance(p, dict) and isinstance(p.get("id"), str)] if isinstance(raw, list) else []
            self.status_label.setText(
                "Not computed · current context cannot be validated. " + self._context_error
                if self._context_error is not None else
                "Not computed · evaluator unavailable. Import an explicitly designed Sobol report.")
            self.status_label.setStyleSheet("color: #64748b;")
            self.provenance_label.setText("No sensitivity results. Existing DB rows are not used to infer Sobol indices.")
            self.provenance_label.setToolTip("")
        self.table.blockSignals(True)
        self.table.clear()
        self.table.setRowCount(len(self._outputs))
        self.table.setColumnCount(len(self._inputs))
        self.table.setVerticalHeaderLabels([o["label"] for o in self._outputs])
        self.table.setHorizontalHeaderLabels([_parameter_label(p) for p in self._inputs])
        self._cells = []
        key = "first_order" if self.index_combo.currentData() == "S1" else "total_order"
        for row, output in enumerate(self._outputs):
            if output["id"] in report_rows:
                cells = self._report[key][report_rows[output["id"]]]
            else:
                cells = [_unknown("unavailable" if p.get("available") is False else
                                  "fixed" if p.get("active") is False else "not_computed") for p in self._inputs]
            self._cells.append(cells)
            for column, (parameter, cell) in enumerate(zip(self._inputs, cells)):
                value = cell["estimate"]
                item = QTableWidgetItem("—" if value is None else f"{value:.3f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.UserRole, copy.deepcopy(cell))
                param = {"label": parameter.get("label", parameter["id"]), **parameter}
                item.setToolTip(_tip(cell, output, param, self._marginals.get(parameter["id"])))
                if value is None:
                    color, foreground = QColor("#f1f4f7"), QColor("#8795a4")
                elif not 0 <= value <= 1:
                    color, foreground = QColor("#fff0d4"), QColor("#83590b")
                else:
                    color = QColor.fromRgbF(.94 - .58 * value, .98 - .35 * value, .98 - .27 * value)
                    foreground = QColor("#153942")
                item.setBackground(color)
                item.setForeground(foreground)
                self.table.setItem(row, column, item)
        row = next((i for i, output in enumerate(self._outputs) if output["id"] == selected), 0)
        if self._inputs:
            self.table.setCurrentCell(row, 0)
        self.table.blockSignals(False)
        self._select_response(row)

    def _select_response(self, row, *_args):
        if not 0 <= row < len(self._outputs):
            return
        output = self._outputs[row]
        self.response_label.setText(f'{output["label"]} · {self.index_combo.currentData()}')
        rows = []
        for parameter, cell in zip(self._inputs, self._cells[row]):
            param = {"label": parameter.get("label", parameter["id"]), **parameter}
            rows.append({"label": _parameter_label(param), "cell": cell,
                         "tooltip": _tip(cell, output, param, self._marginals.get(parameter["id"]))})
        self.chart.set_rows(rows)
