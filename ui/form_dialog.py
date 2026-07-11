"""
Dialog for filling simple PDF form fields.
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTableWidget,
                             QTableWidgetItem, QDialogButtonBox,
                             QAbstractItemView)
from PyQt5.QtCore import Qt


class FormFillDialog(QDialog):
    def __init__(self, fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fill PDF Form")
        self.resize(760, 460)
        self.fields = fields

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Edit field values, then choose Apply. Use File > Save As to "
            "share the filled copy."))

        self.table = QTableWidget(len(fields), 5)
        self.table.setHorizontalHeaderLabels(
            ["Page", "Field", "Type", "Current value", "New value"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 210)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 160)
        self.table.setColumnWidth(4, 190)
        layout.addWidget(self.table)

        for row, field in enumerate(fields):
            values = [
                str(field["page"] + 1),
                field["name"],
                field["type_name"],
                field["value"],
                field["value"],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col < 4:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)

        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        updates = []
        for row, field in enumerate(self.fields):
            item = self.table.item(row, 4)
            value = item.text() if item else ""
            if value != field["value"]:
                updates.append((field, value))
        return updates
