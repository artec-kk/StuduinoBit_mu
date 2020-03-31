"""
A mode for working with Studuino:bit running MicroPython.

Copyright (c) 2015-2019 Nicholas H.Tollervey and others (see the AUTHORS file).

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
import logging
import os
import time
from mu.modes.base import MicroPythonMode, StuduinoBitFileManager
from mu.modes.api import STUDUINOBIT_APIS, SHARED_APIS
from mu.interface.panes import CHARTS
from PyQt5.QtCore import (
    QIODevice,
    QThread,
    QTimer,
)
from PyQt5.QtWidgets import (
    QDialog,
    QGridLayout,
    QPushButton,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
)
from mu.contrib import sbfs
from mu.logic import HOME_DIRECTORY, WORKSPACE_NAME, save_and_encode

from serial import Serial
from PyQt5.QtSerialPort import QSerialPort

logger = logging.getLogger(__name__)


class StuduinoBitMode(MicroPythonMode):
    """
    Represents the functionality required for running
    MicroPython on Studuino:bit
    """

    name = _("Artec Studuino:Bit MicroPython")
    description = _("Write MicroPython on Studuino:bit.")
    icon = "studuinobit"
    fs = None

    message = _("Could not find an attached device.")
    information = _(
        "Please make sure the device is plugged into this"
        " computer.\n\nIt must have a version of"
        " MicroPython (or CircuitPython) flashed onto it"
        " before the REPL will work.\n\nFinally, press the"
        " device's reset button and wait a few seconds"
        " before trying again."
    )

    # There are many boards which use ESP microcontrollers but they often use
    # the same USB / serial chips (which actually define the Vendor ID and
    # Product ID for the connected devices.
    valid_boards = [
        # VID  , PID
        (0x20A0, 0x4269)  # Studuion:bit VID, PID
    ]

    def __init__(self, editor, view):
        super().__init__(editor, view)
        self.timer = QTimer()
        self.timer.timeout.connect(self.is_connecting)

    def actions(self):
        """
        Return an ordered list of actions provided by this module. An action
        is a name (also used to identify the icon) , description, and handler.
        """
        buttons = [
            {
                "name": "run",
                "display_name": _("Run"),
                "description": _(
                    "Run your code directly on the Studuino:bit"
                    " via the REPL."
                ),
                "handler": self.run,
                "shortcut": "F5",
            },
            {
                "name": "flash_sb",
                "display_name": _("Flash"),
                "description": _("Flash your code onto the Studuino:bit."),
                "handler": self.toggle_flash,
                "shortcut": "F3",
            },
            {
                "name": "files_sb",
                "display_name": _("Files"),
                "description": _("Access the file system on Studuino:bit."),
                "handler": self.toggle_files,
                "shortcut": "F4",
            },
            {
                "name": "repl",
                "display_name": _("REPL"),
                "description": _(
                    "Use the REPL to live-code on the " "Studuino:bit."
                ),
                "handler": self.toggle_repl,
                "shortcut": "Ctrl+Shift+I",
            },
        ]
        if CHARTS:
            buttons.append(
                {
                    "name": "plotter",
                    "display_name": _("Plotter"),
                    "description": _("Plot incoming REPL data."),
                    "handler": self.toggle_plotter,
                    "shortcut": "CTRL+Shift+P",
                }
            )
        return buttons

    def api(self):
        """
        Return a list of API specifications to be used by auto-suggest and call
        tips.
        """
        return SHARED_APIS + STUDUINOBIT_APIS

    def toggle_repl(self, event):
        if self.fs is None:
            if self.repl:
                # Remove REPL
                super().toggle_repl(event)

                if not (self.repl or self.plotter):
                    self.set_buttons(files_sb=True, flash_sb=True)
                    if self.timer.isActive():
                        self.timer.stop()

            elif not (self.repl):
                # Add REPL
                # time.sleep(1)
                super().toggle_repl(event)
                if self.repl:
                    self.set_buttons(files_sb=False, flash_sb=False)

                    #アップデート時間設定
                    if not self.timer.isActive():
                        self.timer.start(1000)    #1sごとにis_connectingを呼び出し

        else:
            message = _("REPL and file system cannot work at the same time.")
            information = _(
                "The REPL and file system both use the same USB "
                "serial connection. Only one can be active "
                "at any time. Toggle the file system off and "
                "try again."
            )
            self.view.show_message(message, information)

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

    def read_until(self, token, timeout=5000):
        buff = bytearray()
        while True:
            if not (self.serial.waitForReadyRead(timeout)):
                raise TimeoutError(_('waitForReadyRead method timeout'))

            data = bytes(self.serial.readAll())  # get all the available bytes.
            buff.extend(data)
            if token in buff:
                break

    def reboot(self, serial):
        serial.write(b"\x03")  # Ctrl+C
        self.read_until(b">>> ")  # Read until prompt.
        serial.write(b"\x01")  # Ctrl+A
        serial.write("import machine\r\n".encode("utf-8"))
        time.sleep(0.01)
        serial.write("machine.reset()\r\n".encode("utf-8"))
        time.sleep(0.01)
        serial.write(b"\x04")
        self.read_until(
            # b"Starting scheduler on PRO CPU"
            b"Execute last selected script."
        )

    def reboot_and_prompt(self, serial):
        self.reboot(serial)
        # display prompt
        serial.write(b"\x03")  # Ctrl+C
        self.read_until(b">>> ")  # Read until prompt.

    def toggle_flash(self, event):
        def save():
            # Display dialog
            regist_box = RegisterWindow(self.view)
            result = regist_box.exec()
            if result == 0:
                return None, None

            # Save file
            reg_info = regist_box.get_register_info()
            reg_num = reg_info[0]

            tab = self.view.current_tab
            usr_file = os.path.join(
                HOME_DIRECTORY,
                WORKSPACE_NAME,
                "studuinobit",
                "usr" + reg_num + ".py",
            )
            save_and_encode(tab.text(), usr_file, tab.newline)
            return reg_num, usr_file

        def upload(serial, usr_file):
            filename = os.path.basename(usr_file)
            sbfs.put(usr_file, "usr/" + filename, serial)

        def restart(serial, reg_num):
            set_start_index = [
                "import machine",
                'machine.nvs_setint("lastSelected", {0})'.format(reg_num),
            ]
            sbfs.execute(set_start_index, serial)
            self.reboot(serial)

        # Serial port open
        try:
            device_port, serial_number = self.find_device()
            self.open_serial_link(device_port)
        except Exception as e:
            self.view.show_message(self.message, self.information)
            return

        serial = self.serial

        # save usr*.py local
        try:
            reg_num, usr_file = save()
            if reg_num == None and usr_file == None:
                self.close_serial_link()
                return
        except Exception as e:
            logger.exception("Error reboot in transfer: %s", e)
            QMessageBox.critical(None, _("File Save Error."), _("Failed to save the file."), QMessageBox.Yes)
            self.close_serial_link()
            return

        # reboot
        try:
            # Reboot MicroPython and Prompt
            self.reboot_and_prompt(serial)
        except Exception as e:
            logger.exception("Error reboot in transfer: %s", e)
            QMessageBox.critical(None, _("Reboot Error"), _("Please connect the USB cable again."), QMessageBox.Yes)
            self.close_serial_link()
            return

        # send usr*.py target
        try:
            # # for simple debug
            # print('upload')
            # time.sleep(1)
            upload(serial, usr_file)
        except Exception as e:
            logger.exception("Error upload in transfer: %s", e)
            QMessageBox.critical(None, _("Uploade Error"), _("Please connect the USB cable again."), QMessageBox.Yes)
            self.close_serial_link()
            return

        # restart
        try:
            # # for simple debug
            # print('restart')
            # time.sleep(1)
            restart(serial, reg_num)
        except Exception as e:
            logger.exception("Error restart in transfer: %s", e)
            information = _(
                "Since the transfer is completed, it will work\n"
                " if you reconnect the USB cable."
            )
            QMessageBox.critical(None, _("Restart Error"), information, QMessageBox.Yes)
            self.close_serial_link()
            return

        self.editor.show_status_message(_("Transfer success"))
        self.close_serial_link()

    def toggle_plotter(self, event):
        """
        Check for the existence of the file pane before toggling plotter.
        """
        if self.fs is None:
            super().toggle_plotter(event)
            if self.plotter:
                self.set_buttons(files_sb=False, flash_sb=False)

                #アップデート時間設定
                if not self.timer.isActive():
                    self.timer.start(1000)    #1sごとにis_connectingを呼び出し
            elif not (self.repl or self.plotter):
                self.set_buttons(files_sb=True, flash_sb=True)
                if self.timer.isActive():
                    self.timer.stop()
        else:
            message = _(
                "The plotter and file system cannot work at the same " "time."
            )
            information = _(
                "The plotter and file system both use the same "
                "USB serial connection. Only one can be active "
                "at any time. Toggle the file system off and "
                "try again."
            )
            self.view.show_message(message, information)

    def initialize(self):
        # Get serial port
        try:
            device_port, serial_number = self.find_device()
            self.open_serial_link(device_port)
        except Exception as e:
            logger.exception("Error reboot in run: %s", e)
            raise RuntimeError(_('Open Serial Error')) from e

        serial = self.serial

        # Reboot and wait prompt
        try:
            # # for simple debug
            # print('restart')
            # time.sleep(1)
            self.reboot_and_prompt(serial)
        except Exception as e:
            logger.exception("Error reboot in run: %s", e)
            self.close_serial_link()
            raise RuntimeError(_('Reboot Error')) from e

        # Set start to send command
        command = [
            "import machine",
            'machine.nvs_setint("lastSelected", 99)',
        ]
        try:
            # # for simple debug
            # print('reset')
            # time.sleep(1)
            sbfs.execute(command, serial,)
        except IOError as e:
            logger.exception("Error reset slot in run: %s", e)
            self.close_serial_link()
            raise RuntimeError(_('Reset Error')) from e

        self.close_serial_link()

        return True

    def run(self):
        """
        Takes the currently active tab, compiles the Python script therein into
        a hex file and flashes it all onto the connected device.
        """
        if not self.repl:
            try:
                # Initialize Studuino:bit
                self.initialize()
            except Exception as e:
                if e.args[0] == _('Open Serial Error'):
                    self.view.show_message(self.message, self.information)
                else:
                    self.view.show_message(e.args[0], _("Please connect the USB cable again."))
                return

        logger.info("Running script.")
        # Grab the Python script.
        tab = self.view.current_tab
        if tab is None:
            # There is no active text editor.
            message = _("Cannot run anything without any active editor tabs.")
            information = _(
                "Running transfers the content of the current tab"
                " onto the device. It seems like you don't have "
                " any tabs open."
            )
            self.view.show_message(message, information)
            return

        python_script = tab.text().replace("\r\n", "\n")
        python_script = python_script.split("\n")

        print(python_script)

        if not self.repl:
            self.toggle_repl(None)
        if self.repl:
            self.view.repl_pane.send_commands(python_script)

    def toggle_files(self, event):
        """
        Check for the existence of the REPL or plotter before toggling the file
        system navigator for the MicroPython device on or off.
        """
        if self.repl:
            message = _(
                "File system cannot work at the same time as the "
                "REPL or plotter."
            )
            information = _(
                "The file system and the REPL and plotter "
                "use the same USB serial connection. Toggle the "
                "REPL and plotter off and try again."
            )
            self.view.show_message(message, information)
        else:
            if self.fs is None:
                # time.sleep(1)
                self.add_fs()
                if self.fs:
                    logger.info("Toggle filesystem on.")
                    self.set_buttons(
                        run=False, repl=False, plotter=False, flash_sb=False
                    )
            else:
                self.remove_fs()
                logger.info("Toggle filesystem off.")
                self.set_buttons(
                    run=True, repl=True, plotter=True, flash_sb=True
                )

    def add_fs(self):
        """
        Add the file system navigator to the UI.
        """

        # Find serial port the ESP8266/ESP32 is connected to
        device_port, serial_number = self.find_device()

        # Check for MicroPython device
        if not device_port:
            self.view.show_message(self.message, self.information)
            return

        self.file_manager_thread = QThread(self)
        self.file_manager = StuduinoBitFileManager(device_port)
        self.file_manager.moveToThread(self.file_manager_thread)
        self.file_manager_thread.started.connect(self.file_manager.on_start)
        self.fs = self.view.add_studuinobit_filesystem(
            self.workspace_dir(), self.file_manager
        )
        self.fs.set_message.connect(self.editor.show_status_message)
        self.fs.set_warning.connect(self.view.show_message)
        self.file_manager_thread.start()

    def remove_fs(self):
        """
        Remove the file system navigator from the UI.
        """
        self.view.remove_filesystem()
        self.file_manager = None
        self.file_manager_thread = None
        self.fs = None

    def on_data_flood(self):
        """
        Ensure the Files button is active before the REPL is killed off when
        a data flood of the plotter is detected.
        """
        self.set_buttons(files_sb=True)
        super().on_data_flood()

    def add_repl(self):
        """
        Detect a connected MicroPython based device and, if found, connect to
        the REPL and display it to the user.
        """
        device_port, serial_number = self.find_device()
        if device_port:
            try:
                self.view.add_studuionbit_repl(
                    device_port, self.name, self.force_interrupt
                )
                logger.info("Started REPL on port: {}".format(device_port))
                self.repl = True
            except IOError as ex:
                logger.error(ex)
                self.repl = False
                info = _(
                    "Click on the device's reset button, wait a few"
                    " seconds and then try again."
                )
                self.view.show_message(str(ex), info)
            except Exception as ex:
                logger.error(ex)
        else:
            self.view.show_message(self.message, self.information)

    def is_connecting(self):
        device_port, serial_number = self.find_device()
        if device_port:
            pass
        else:
            self.timer.stop()
            if self.repl:
                self.toggle_repl(None)
            if self.plotter:
                self.toggle_plotter(None)
            message = _("Could not find an attached device.")
            information = _(
                "Please make sure the device is plugged into this"
                " computer.\n\nIt must have a version of"
                " MicroPython (or CircuitPython) flashed onto it"
                " before the REPL will work.\n\nFinally, press the"
                " device's reset button and wait a few seconds"
                " before trying again."
            )
            self.view.show_message(message, information)


class RegisterWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.register_info = []

        grid = QGridLayout()
        grid.setSpacing(10)

        offset_v = 5
        offset_h = 3
        for i in range(10):
            reg_fname = QLabel("usr" + str(i) + ".py")
            button = QPushButton("Transfer")
            button.clicked.connect(self.on_click)
            hbox = QHBoxLayout()
            group_box = QGroupBox()
            group_box.setTitle(str(i))

            hbox.addWidget(reg_fname)
            hbox.addWidget(button)
            group_box.setLayout(hbox)

            if i > 4:
                grid.addWidget(group_box, i - offset_v, offset_h)
            else:
                grid.addWidget(group_box, i, 0)

        self.setLayout(grid)
        self.setWindowTitle("Select a slot to transfer.")

        self.parent = parent

    def on_click(self):
        sender = self.sender()
        reg_number = sender.parent().title()
        self.register_info.append(reg_number)
        self.accept()

    def get_register_info(self):
        """
        Return a selected slot number
        """
        return self.register_info
