"""
UI related code for dialogs used by Mu.

Copyright (c) 2015-2017 Nicholas H.Tollervey and others (see the AUTHORS file).

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import os
import sys
import logging
import csv
import shutil
import re
from PyQt5 import QtCore
from PyQt5.QtCore import QSize, QProcess, QTimer, Qt, QIODevice
from PyQt5.QtSerialPort import QSerialPort
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QGridLayout,
    QListWidget,
    QLabel,
    QListWidgetItem,
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QTabWidget,
    QWidget,
    QCheckBox,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QGroupBox,
    QComboBox,
    QMessageBox,
)
from PyQt5.QtGui import QTextCursor
from mu.resources import load_icon
from multiprocessing import Process
from mu.logic import MODULE_DIR
from mu.contrib import sbfs

logger = logging.getLogger(__name__)


class ModeItem(QListWidgetItem):
    """
    Represents an available mode listed for selection.
    """

    def __init__(self, name, description, icon, parent=None):
        super().__init__(parent)
        self.name = name
        self.description = description
        self.icon = icon
        text = "{}\n{}".format(name, description)
        self.setText(text)
        self.setIcon(load_icon(self.icon))


class ModeSelector(QDialog):
    """
    Defines a UI for selecting the mode for Mu.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

    def setup(self, modes, current_mode):
        self.setMinimumSize(600, 400)
        self.setWindowTitle(_("Select Mode"))
        widget_layout = QVBoxLayout()
        label = QLabel(
            _(
                'Please select the desired mode then click "OK". '
                'Otherwise, click "Cancel".'
            )
        )
        label.setWordWrap(True)
        widget_layout.addWidget(label)
        self.setLayout(widget_layout)
        self.mode_list = QListWidget()
        self.mode_list.itemDoubleClicked.connect(self.select_and_accept)
        widget_layout.addWidget(self.mode_list)
        self.mode_list.setIconSize(QSize(48, 48))
        for name, item in modes.items():
            if not item.is_debugger:
                litem = ModeItem(
                    item.name, item.description, item.icon, self.mode_list
                )
                if item.icon == current_mode:
                    self.mode_list.setCurrentItem(litem)
        self.mode_list.sortItems()
        instructions = QLabel(
            _(
                "Change mode at any time by clicking "
                'the "Mode" button containing Mu\'s logo.'
            )
        )
        instructions.setWordWrap(True)
        widget_layout.addWidget(instructions)
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        widget_layout.addWidget(button_box)

    def select_and_accept(self):
        """
        Handler for when an item is double-clicked.
        """
        self.accept()

    def get_mode(self):
        """
        Return details of the newly selected mode.
        """
        if self.result() == QDialog.Accepted:
            return self.mode_list.currentItem().icon
        else:
            raise RuntimeError("Mode change cancelled.")


class LogWidget(QWidget):
    """
    Used to display Mu's logs.
    """

    def setup(self, log):
        widget_layout = QVBoxLayout()
        self.setLayout(widget_layout)
        label = QLabel(
            _(
                "When reporting a bug, copy and paste the content of "
                "the following log file."
            )
        )
        label.setWordWrap(True)
        widget_layout.addWidget(label)
        self.log_text_area = QPlainTextEdit()
        self.log_text_area.setReadOnly(True)
        self.log_text_area.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_text_area.setPlainText(log)
        widget_layout.addWidget(self.log_text_area)


class EnvironmentVariablesWidget(QWidget):
    """
    Used for editing and displaying environment variables used with Python 3
    mode.
    """

    def setup(self, envars):
        widget_layout = QVBoxLayout()
        self.setLayout(widget_layout)
        label = QLabel(
            _(
                "The environment variables shown below will be "
                "set each time you run a Python 3 script.\n\n"
                "Each separate enviroment variable should be on a "
                "new line and of the form:\nNAME=VALUE"
            )
        )
        label.setWordWrap(True)
        widget_layout.addWidget(label)
        self.text_area = QPlainTextEdit()
        self.text_area.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text_area.setPlainText(envars)
        widget_layout.addWidget(self.text_area)


class MicrobitSettingsWidget(QWidget):
    """
    Used for configuring how to interact with the micro:bit:

    * Minification flag.
    * Override runtime version to use.
    """

    def setup(self, minify, custom_runtime_path):
        widget_layout = QVBoxLayout()
        self.setLayout(widget_layout)
        self.minify = QCheckBox(_("Minify Python code before flashing?"))
        self.minify.setChecked(minify)
        widget_layout.addWidget(self.minify)
        label = QLabel(
            _(
                "Override the built-in MicroPython runtime with "
                "the following hex file (empty means use the "
                "default):"
            )
        )
        label.setWordWrap(True)
        widget_layout.addWidget(label)
        self.runtime_path = QLineEdit()
        self.runtime_path.setText(custom_runtime_path)
        widget_layout.addWidget(self.runtime_path)
        widget_layout.addStretch()


class PackagesWidget(QWidget):
    """
    Used for editing and displaying 3rd party packages installed via pip to be
    used with Python 3 mode.
    """

    def setup(self, packages):
        widget_layout = QVBoxLayout()
        self.setLayout(widget_layout)
        self.text_area = QPlainTextEdit()
        self.text_area.setLineWrapMode(QPlainTextEdit.NoWrap)
        label = QLabel(
            _(
                "The packages shown below will be available to "
                "import in Python 3 mode. Delete a package from "
                "the list to remove its availability.\n\n"
                "Each separate package name should be on a new "
                "line. Packages are installed from PyPI "
                "(see: https://pypi.org/)."
            )
        )
        label.setWordWrap(True)
        widget_layout.addWidget(label)
        self.text_area.setPlainText(packages)
        widget_layout.addWidget(self.text_area)


class SBFirmwareFlasherWidget(QWidget):
    """
    Used for configuring how to interact with the ESP32:

    * Override MicroPython.
    """

    def setup(self):
        widget_layout = QVBoxLayout()
        self.setLayout(widget_layout)

        # Check whether esptool is installed, show error if not
        esptool_installed = os.path.exists(MODULE_DIR + "/esptool.py")
        if not esptool_installed:
            error_msg = _(
                "The ESP Firmware flasher requires the esptool "
                "package to be installed.\n"
                "Select \"Third Party Packages\", add 'esptool' "
                "and click 'OK'"
            )
            error_label = QLabel(error_msg)
            widget_layout.addWidget(error_label)
            return

        # Instructions
        grp_instructions = QGroupBox(
            _("How to flash MicroPython to your device")
        )
        grp_instructions_vbox = QVBoxLayout()
        grp_instructions.setLayout(grp_instructions_vbox)
        instructions = _(
            "&nbsp;1. Download firmware from the <br/>"
            '&nbsp;&nbsp;&nbsp;&nbsp;<a href="https://www.artec-kk.co.jp/artecrobo2/data/mp/micropython.bin">'
            "https://www.artec-kk.co.jp/artecrobo2/data/mp/micropython.bin</a><br/>"
            "&nbsp;2. Connect your device<br/>"
            "&nbsp;3. Load the .bin file below using the 'Browse' button<br/>"
            "&nbsp;4. Press 'Write firmware'"
        )
        label = QLabel(instructions)
        label.setTextFormat(Qt.RichText)
        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        label.setOpenExternalLinks(True)
        label.setWordWrap(True)
        grp_instructions_vbox.addWidget(label)
        widget_layout.addWidget(grp_instructions)

        # Device type, firmware path, flash button
        firmware_label = QLabel(_("Firmware (.bin):"))
        self.txtFolder = QLineEdit()
        self.btnFolder = QPushButton(_("Browse"))
        self.btnExec = QPushButton(_("Write firmware"))
        self.btnExec.setEnabled(False)
        form_set = QGridLayout()
        form_set.addWidget(firmware_label, 0, 0)
        form_set.addWidget(self.txtFolder, 0, 1)
        form_set.addWidget(self.btnFolder, 0, 2)
        form_set.addWidget(self.btnExec, 0, 3)
        widget_layout.addLayout(form_set)

        # Output area
        self.log_text_area = QPlainTextEdit()
        self.log_text_area.setReadOnly(True)
        form_set = QHBoxLayout()
        form_set.addWidget(self.log_text_area)
        widget_layout.addLayout(form_set)
        widget_layout.addStretch()

        # Connect events
        self.txtFolder.textChanged.connect(self.firmware_path_changed)
        self.btnFolder.clicked.connect(self.show_folder_dialog)
        self.btnExec.clicked.connect(self.update_firmware)

    def show_folder_dialog(self):
        # open dialog and set to foldername
        filename = QFileDialog.getOpenFileName(
            self,
            "Select MicroPython firmware (.bin)",
            os.path.expanduser("."),
            "Firmware (*.bin)",
        )
        if filename:
            filename = filename[0].replace("/", os.sep)
            self.txtFolder.setText(filename)

    def update_firmware(self):
        esptool = MODULE_DIR + "/esptool.py"
        write_command = (
            'python "{}" --baud 1500000 ' 'write_flash 0x20000 "{}"'
        ).format(esptool, self.txtFolder.text())

        self.commands = [write_command]
        self.run_esptool()

    def run_esptool(self):
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardError.connect(self.read_process)
        self.process.readyReadStandardOutput.connect(self.read_process)
        self.process.finished.connect(self.esptool_finished)
        self.process.errorOccurred.connect(self.esptool_error)

        command = self.commands.pop(0)
        self.log_text_area.appendPlainText(command + "\n")
        self.process.start(command)

    def esptool_error(self, error_num):
        self.log_text_area.appendPlainText(
            "Error occured: Error {}\n".format(error_num)
        )
        self.process = None

    def esptool_finished(self, exitCode, exitStatus):
        """
        Called when the subprocess that executes 'esptool.py is finished.
        """
        # Exit if a command fails
        if exitCode != 0 or exitStatus == QProcess.CrashExit:
            self.log_text_area.appendPlainText("Error on flashing. Aborting.")
            return
        if self.commands:
            self.process = None
            self.run_esptool()

    def read_process(self):
        """
        Read data from the child process and append it to the text area. Try
        to keep reading until there's no more data from the process.
        """
        msg = ""
        data = self.process.readAll()
        if data:
            try:
                msg = data.data().decode("utf-8")
                self.append_data(msg)
            except UnicodeDecodeError:
                pass
            QTimer.singleShot(2, self.read_process)

    def append_data(self, msg):
        """
        Add data to the end of the text area.
        """
        cursor = self.log_text_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(msg)
        cursor.movePosition(QTextCursor.End)
        self.log_text_area.setTextCursor(cursor)

    def firmware_path_changed(self):
        if len(self.txtFolder.text()) > 0:
            self.btnExec.setEnabled(True)
        else:
            self.btnExec.setEnabled(False)


class ESP32PackagesWidget(QWidget):
    """
    Used for editing and displaying 3rd party packages installed via pip to be
    used with Python 3 mode.
    """

    message = _("Could not find an attached device.")
    information = _(
        "Please make sure the device is plugged into this"
        " computer.\n\nIt must have a version of"
        " MicroPython (or CircuitPython) flashed onto it"
        " before the REPL will work.\n\nFinally, press the"
        " device's reset button and wait a few seconds"
        " before trying again."
    )

    def setup(self, target):
        widget_layout = QVBoxLayout()
        self.setLayout(widget_layout)

        # Instructions
        grp_instructions = QGroupBox(
            _("How to install MicroPython library to your device")
        )
        grp_instructions_vbox = QVBoxLayout()
        grp_instructions.setLayout(grp_instructions_vbox)
        instructions = _(
            "&nbsp;1. Connect your device<br/>"
            "&nbsp;2. Press 'Wi-Fi Scan' in Wi-Fi Connection area<br/>"
            "&nbsp;4. Select SSID from the combo box<br/>"
            "&nbsp;5. Write password in the text area<br/>"
            "&nbsp;6. Press 'Connect'<br/>"
            "&nbsp;7. Write libraries you want install in Update/Install libraries area<br/>"
            "&nbsp;8. Press 'Start'<br/>"
        )
        label = QLabel(instructions)
        label.setTextFormat(Qt.RichText)
        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        label.setOpenExternalLinks(True)
        label.setWordWrap(True)
        grp_instructions_vbox.addWidget(label)
        widget_layout.addWidget(grp_instructions)

        # WiFi area
        label_layout = QVBoxLayout()
        label_ssid = QLabel(_("SSID:"))
        label_pwd = QLabel(_("Password:"))
        label_layout.addWidget(label_ssid)
        label_layout.addWidget(label_pwd)

        setting_layout = QVBoxLayout()
        self.list_ssid = QComboBox()
        self.list_ssid.setEditable(True)
        self.line_pwd = QLineEdit()
        setting_layout.addWidget(self.list_ssid)
        setting_layout.addWidget(self.line_pwd)

        button_layout = QVBoxLayout()
        self.button_scan = QPushButton(_("Wi-Fi Scan"))
        self.button_scan.setEnabled(True)
        button_layout.addWidget(self.button_scan, alignment=Qt.AlignTop)

        conf_layout = QHBoxLayout()
        conf_layout.addLayout(label_layout)
        conf_layout.addLayout(setting_layout)
        conf_layout.addLayout(button_layout)

        self.button_conn = QPushButton(_("Connect"))
        self.button_conn.setCheckable(True)
        self.button_conn.setEnabled(False)

        wifi_layout = QVBoxLayout()
        wifi_layout.addLayout(conf_layout)
        wifi_layout.addWidget(self.button_conn)

        groupbox = QGroupBox(_("Wi-Fi Connection"))
        groupbox.setLayout(wifi_layout)
        widget_layout.addWidget(groupbox)

        # Install area
        libraries = (
            "micropython-artecrobo2.0\n" "micropython-studuinobit-iot\n"
        )
        self.text_area = QPlainTextEdit(libraries)
        self.text_area.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.button_inst = QPushButton(_("Start"))
        self.button_inst.setEnabled(False)

        inst_layout = QVBoxLayout()
        inst_layout.addWidget(self.text_area)
        inst_layout.addWidget(self.button_inst)

        self.groupbox_install = QGroupBox(_("Update/Install libraries"))
        self.groupbox_install.setLayout(inst_layout)
        self.groupbox_install.setEnabled(False)
        widget_layout.addWidget(self.groupbox_install)

        widget_layout.addStretch()

        # Set event
        self.button_scan.clicked.connect(self.scan)
        self.button_conn.toggled.connect(self.connect)
        self.button_inst.clicked.connect(self.install)

        # self.button_conn.installEventFilter(self)
        self.list_ssid.editTextChanged.connect(self.wifi_info_changed)
        self.line_pwd.textChanged.connect(self.wifi_info_changed)
        self.text_area.textChanged.connect(self.library_info_changed)

        self.target = target

    def open_serial_link(self, port):
        """
        Creates a new serial link instance.
        """
        self.input_buffer = []
        self.serial = QSerialPort()
        self.serial.setPortName(port)
        if self.serial.open(QIODevice.ReadWrite):
            self.serial.setDataTerminalReady(True)
            if not self.serial.isDataTerminalReady():
                # Using pyserial as a 'hack' to open the port and set DTR
                # as QtSerial does not seem to work on some Windows :(
                # See issues #281 and #302 for details.
                self.serial.close()
                pyser = serial.Serial(port)  # open serial port w/pyserial
                pyser.dtr = True
                pyser.close()
                self.serial.open(QIODevice.ReadWrite)
            self.serial.setBaudRate(115200)
        else:
            msg = _("Cannot connect to device on port {}").format(port)
            raise IOError(msg)

    def close_serial_link(self):
        """
        Close and clean up the currently open serial link.
        """
        if self.serial:
            self.serial.close()
            self.serial = None

    def scan(self):
        # Clear
        self.list_ssid.clear()

        try:
            # Initialize Studuino:bit
            self.target.initialize()
        except Exception as e:
            if e.args[0] == _("Open Serial Error"):
                self.target.view.show_message(self.message, self.information)
            else:
                self.target.view.show_message(
                    e.args[0], _("Please connect the USB cable again.")
                )
            return

        # Serial port open
        try:
            device_port, serial_number = self.target.find_device()
            self.open_serial_link(device_port)
        except Exception as e:
            self.target.view.show_message(self.message, self.information)
            return

        # Get AP Informations
        command = [
            "import network",
            "sta = network.WLAN(network.STA_IF)",
            "sta.active(True)",
            "print(sta.scan())",
        ]
        try:
            out, err = sbfs.send_cmd(command, self.serial)
        except IOError as e:
            logger.exception("Error in scan: %s", e)
            self.target.view.show_message(
                _("Scan Error"), _("Please connect the USB cable again.")
            )
            self.close_serial_link()
            return

        # Display SSIDs
        aps = re.findall(r"\((.*?)\)", str(out))
        logger.info(aps)
        for ap in aps:
            info = ap.split(",")
            ssid = re.sub(r"['\\]", "", info[0][1:])
            self.list_ssid.addItem(ssid)

        self.close_serial_link()

    def connect(self, connect):
        # Serial port open
        self.button_conn.setEnabled(False)
        try:
            device_port, serial_number = self.target.find_device()
            self.open_serial_link(device_port)
        except Exception as e:
            QMessageBox.critical(
                None,
                _("Open Serial Error"),
                _("{0}".format(e)),
                QMessageBox.Yes,
            )
            self.button_conn.setEnabled(True)
            return

        if connect:
            # Get AP Informations
            connect_command = (
                "sta.connect('"
                + self.list_ssid.currentText()
                + "', '"
                + self.line_pwd.text()
                + "')"
            )
            command = [
                connect_command,
                "while not sta.isconnected():\n pass",
                "print(sta.ifconfig())",
            ]
            try:
                out, err = sbfs.send_cmd(command, self.serial)
            except IOError as e:
                QMessageBox.critical(
                    None,
                    _("Wi-Fi Connect Error"),
                    _("{0}".format(e)),
                    QMessageBox.Yes,
                )
                self.close_serial_link()
                self.button_conn.setEnabled(True)
                return

            self.button_conn.setEnabled(True)
            self.button_conn.setText(_("Disconnect"))

            self.list_ssid.setEnabled(False)
            self.line_pwd.setEnabled(False)
            self.button_scan.setEnabled(False)

            self.groupbox_install.setEnabled(True)
            self.library_info_changed()
        else:
            # Get AP Informations
            connect_command = (
                "sta.connect('"
                + self.list_ssid.currentText()
                + "', '"
                + self.line_pwd.text()
                + "')"
            )
            command = [
                "sta.disconnect()",
                "while sta.isconnected():\n pass",
                "print(sta.ifconfig())",
            ]
            try:
                out, err = sbfs.send_cmd(command, self.serial)
            except IOError as e:
                QMessageBox.critical(
                    None,
                    _("Wi-Fi Connect Error"),
                    _("{0}".format(e)),
                    QMessageBox.Yes,
                )
                self.close_serial_link()
                self.button_conn.setEnabled(True)
                return

            self.button_conn.setText(_("Connect"))
            self.list_ssid.setEnabled(True)
            self.line_pwd.setEnabled(True)
            self.button_scan.setEnabled(True)
            self.groupbox_install.setEnabled(False)

        self.close_serial_link()

    def install(self):

        libs = self.text_area.toPlainText()
        libs = libs.split("\n")
        libs = [l for l in libs if l != ""]
        logger.info(libs)

        try:
            device_port, serial_number = self.target.find_device()
            self.open_serial_link(device_port)
        except Exception as e:
            QMessageBox.critical(
                None,
                _("Open Serial Error"),
                _("{0}".format(e)),
                QMessageBox.Yes,
            )
            self.button_conn.setEnabled(True)
            return

        # Get AP Informations
        result = {}
        for lib in libs:
            pip_command = "upip.install('" + lib + "')"
            command = ["import upip", pip_command]
            try:
                out, err = sbfs.send_cmd(command, self.serial)
            except IOError as e:
                QMessageBox.critical(
                    None,
                    _("Wi-Fi Connect Error"),
                    _("{0}".format(e)),
                    QMessageBox.Yes,
                )
                self.close_serial_link()
                self.button_conn.setEnabled(True)
                return

            if b"Error" in out:
                result.update({lib: "NG\n" + str(out) + "\n"})
            else:
                result.update({lib: "OK\n" + str(out) + "\n"})

        information = ""
        for key in result.keys():
            information += "[" + key + "]\n" + result[key] + "\n"

        self.target.view.show_message("UPIP Result", information)

        self.close_serial_link()

    def wifi_info_changed(self):
        if (len(self.line_pwd.text()) > 0) and (
            self.list_ssid.currentText() != ""
        ):
            self.button_conn.setEnabled(True)
        else:
            self.button_conn.setEnabled(False)

    def library_info_changed(self):
        if len(self.text_area.toPlainText().strip()) > 0:
            self.button_inst.setEnabled(True)
        else:
            self.button_inst.setEnabled(False)


class AdminDialog(QDialog):
    """
    Displays administrative related information and settings (logs, environment
    variables, third party packages etc...).
    """

    def __init__(self, parent=None):
        super().__init__(parent)

    def setup(self, log, settings, packages, mode):
        self.setMinimumSize(600, 400)
        self.setWindowTitle(_("Mu Administration"))
        widget_layout = QVBoxLayout()
        self.setLayout(widget_layout)
        self.tabs = QTabWidget()
        widget_layout.addWidget(self.tabs)
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        widget_layout.addWidget(button_box)
        # Tabs
        self.log_widget = LogWidget()
        self.log_widget.setup(log)
        self.tabs.addTab(self.log_widget, _("Current Log"))
        self.envar_widget = EnvironmentVariablesWidget()
        self.envar_widget.setup(settings.get("envars", ""))
        self.tabs.addTab(self.envar_widget, _("Python3 Environment"))
        self.log_widget.log_text_area.setFocus()

        self.esp32_widget = SBFirmwareFlasherWidget()
        self.esp32_widget.setup()
        self.microbit_widget = MicrobitSettingsWidget()
        self.microbit_widget.setup(
            settings.get("minify", False), settings.get("microbit_runtime", "")
        )

        if mode.name == "Artec Studuino:Bit MicroPython":
            self.tabs.addTab(self.esp32_widget, _("Firmware flasher"))

            self.esp32_package_widget = ESP32PackagesWidget()
            self.esp32_package_widget.setup(mode)
            self.tabs.addTab(
                self.esp32_package_widget,
                _("MicroPython Third Party Packages"),
            )
        else:
            self.tabs.addTab(self.microbit_widget, _("BBC micro:bit Settings"))
        self.package_widget = PackagesWidget()
        self.package_widget.setup(packages)
        self.tabs.addTab(self.package_widget, _("Third Party Packages"))

    def settings(self):
        """
        Return a dictionary representation of the raw settings information
        generated by this dialog. Such settings will need to be processed /
        checked in the "logic" layer of Mu.
        """
        return {
            "envars": self.envar_widget.text_area.toPlainText(),
            "minify": self.microbit_widget.minify.isChecked(),
            "microbit_runtime": self.microbit_widget.runtime_path.text(),
            "packages": self.package_widget.text_area.toPlainText(),
        }


class FindReplaceDialog(QDialog):
    """
    Display a dialog for getting:

    * A term to find,
    * An optional value to replace the search term,
    * A flag to indicate if the user wishes to replace all.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

    def setup(self, find=None, replace=None, replace_flag=False):
        self.setMinimumSize(600, 200)
        self.setWindowTitle(_("Find / Replace"))
        widget_layout = QVBoxLayout()
        self.setLayout(widget_layout)
        # Find.
        find_label = QLabel(_("Find:"))
        self.find_term = QLineEdit()
        self.find_term.setText(find)
        self.find_term.selectAll()
        widget_layout.addWidget(find_label)
        widget_layout.addWidget(self.find_term)
        # Replace
        replace_label = QLabel(_("Replace (optional):"))
        self.replace_term = QLineEdit()
        self.replace_term.setText(replace)
        widget_layout.addWidget(replace_label)
        widget_layout.addWidget(self.replace_term)
        # Global replace.
        self.replace_all_flag = QCheckBox(_("Replace all?"))
        self.replace_all_flag.setChecked(replace_flag)
        widget_layout.addWidget(self.replace_all_flag)
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        widget_layout.addWidget(button_box)

    def find(self):
        """
        Return the value the user entered to find.
        """
        return self.find_term.text()

    def replace(self):
        """
        Return the value the user entered for replace.
        """
        return self.replace_term.text()

    def replace_flag(self):
        """
        Return the value of the global replace flag.
        """
        return self.replace_all_flag.isChecked()


class PackageDialog(QDialog):
    """
    Display a dialog to indicate the status of the packaging related changes
    currently run by pip.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

    def setup(self, to_remove, to_add, module_dir):
        """
        Create the UI for the dialog.
        """
        self.to_remove = to_remove
        self.to_add = to_add
        self.module_dir = module_dir
        self.pkg_dirs = {}  # To hold locations of to-be-removed packages.
        self.process = None
        # Basic layout.
        self.setMinimumSize(600, 400)
        self.setWindowTitle(_("Third Party Package Status"))
        widget_layout = QVBoxLayout()
        self.setLayout(widget_layout)
        # Text area for pip output.
        self.text_area = QPlainTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setLineWrapMode(QPlainTextEdit.NoWrap)
        widget_layout.addWidget(self.text_area)
        # Buttons.
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
        self.button_box.accepted.connect(self.accept)
        widget_layout.addWidget(self.button_box)
        # Kick off processing of packages.
        if self.to_remove:
            self.remove_packages()
        if self.to_add:
            self.run_pip()

    def remove_packages(self):
        """
        Work out which packages need to be removed and then kick off their
        removal.
        """
        dirs = [
            os.path.join(self.module_dir, d)
            for d in os.listdir(self.module_dir)
            if d.endswith("dist-info") or d.endswith("egg-info")
        ]
        self.pkg_dirs = {}
        for pkg in self.to_remove:
            for d in dirs:
                # Assets on the filesystem use a normalised package name.
                pkg_name = pkg.replace("-", "_").lower()
                if os.path.basename(d).lower().startswith(pkg_name + "-"):
                    self.pkg_dirs[pkg] = d
        if self.pkg_dirs:
            # If there are packages to remove, schedule removal.
            QTimer.singleShot(2, self.remove_package)

    def remove_package(self):
        """
        Take a package from the pending packages to be removed, delete all its
        assets and schedule the removal of the remaining packages. If there are
        no packages to remove, move to the finished state.
        """
        if self.pkg_dirs:
            package, info = self.pkg_dirs.popitem()
            if info.endswith("dist-info"):
                # Modern
                record = os.path.join(info, "RECORD")
                with open(record) as f:
                    files = csv.reader(f)
                    for row in files:
                        to_delete = os.path.join(self.module_dir, row[0])
                        try:
                            os.remove(to_delete)
                        except Exception as ex:
                            logger.error("Unable to remove: " + to_delete)
                            logger.error(ex)
                shutil.rmtree(info, ignore_errors=True)
                # Some modules don't use the module name for the module
                # directory (they use a lower case variant thereof). E.g.
                # "Fom" vs. "fom".
                normal_module = os.path.join(self.module_dir, package)
                lower_module = os.path.join(self.module_dir, package.lower())
                shutil.rmtree(normal_module, ignore_errors=True)
                shutil.rmtree(lower_module, ignore_errors=True)
                self.append_data("Removed {}\n".format(package))
            else:
                # Egg
                try:
                    record = os.path.join(info, "installed-files.txt")
                    with open(record) as f:
                        files = f.readlines()
                        for row in files:
                            to_delete = os.path.join(info, row.strip())
                            try:
                                os.remove(to_delete)
                            except Exception as ex:
                                logger.error("Unable to remove: " + to_delete)
                                logger.error(ex)
                    shutil.rmtree(info, ignore_errors=True)
                    # Some modules don't use the module name for the module
                    # directory (they use a lower case variant thereof). E.g.
                    # "Fom" vs. "fom".
                    normal_module = os.path.join(self.module_dir, package)
                    lower_module = os.path.join(
                        self.module_dir, package.lower()
                    )
                    shutil.rmtree(normal_module, ignore_errors=True)
                    shutil.rmtree(lower_module, ignore_errors=True)
                    self.append_data("Removed {}\n".format(package))
                except Exception as ex:
                    msg = (
                        "UNABLE TO REMOVE PACKAGE: {} (check the logs for"
                        " more information.)"
                    ).format(package)
                    self.append_data(msg)
                    logger.error("Unable to remove package: " + package)
                    logger.error(ex)
            QTimer.singleShot(2, self.remove_package)
        else:
            # Clean any directories not containing files.
            dirs = [
                os.path.join(self.module_dir, d)
                for d in os.listdir(self.module_dir)
            ]
            for d in dirs:
                keep = False
                for entry in os.walk(d):
                    if entry[2]:
                        keep = True
                if not keep:
                    shutil.rmtree(d, ignore_errors=True)
            # Remove the bin directory (and anything in it) since we don't
            # use these assets.
            shutil.rmtree(
                os.path.join(self.module_dir, "bin"), ignore_errors=True
            )
            # Check for end state.
            if not (self.to_add or self.process):
                self.end_state()

    def end_state(self):
        """
        Set the UI to a valid end state.
        """
        self.append_data("\nFINISHED")
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(True)

    def run_pip(self):
        """
        Run a pip command in a subprocess and pipe the output to the dialog's
        text area.
        """
        package = self.to_add.pop()
        args = ["-m", "pip", "install", package, "--target", self.module_dir]
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyRead.connect(self.read_process)
        self.process.finished.connect(self.finished)
        logger.info("{} {}".format(sys.executable, " ".join(args)))
        self.process.start(sys.executable, args)

    def finished(self):
        """
        Called when the subprocess that uses pip to install a package is
        finished.
        """
        if self.to_add:
            self.process = None
            self.run_pip()
        else:
            if not self.pkg_dirs:
                self.end_state()

    def read_process(self):
        """
        Read data from the child process and append it to the text area. Try
        to keep reading until there's no more data from the process.
        """
        data = self.process.readAll()
        if data:
            self.append_data(data.data().decode("utf-8"))
            QTimer.singleShot(2, self.read_process)

    def append_data(self, msg):
        """
        Add data to the end of the text area.
        """
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(msg)
        cursor.movePosition(QTextCursor.End)
        self.text_area.setTextCursor(cursor)
