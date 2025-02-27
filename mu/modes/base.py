"""
Contains the base classes for Mu editor modes.

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
import json
import os
import os.path
import csv
import time
import logging
import pkgutil
from serial import Serial
from PyQt5.QtSerialPort import QSerialPortInfo
from PyQt5.QtCore import QObject, pyqtSignal
from mu.logic import HOME_DIRECTORY, WORKSPACE_NAME, get_settings_path
from mu.contrib import microfs


logger = logging.getLogger(__name__)


# List of supported board USB IDs.  Each board is a tuple of unique USB vendor
# ID, USB product ID.
BOARD_IDS = set(
    [
        (0x0D28, 0x0204),  # micro:bit USB VID, PID
        (0x239A, 0x800B),  # Adafruit Feather M0 CDC only USB VID, PID
        (0x239A, 0x8016),  # Adafruit Feather M0 CDC + MSC USB VID, PID
        (0x239A, 0x8014),  # metro m0 PID
        (0x239A, 0x8019),  # circuitplayground m0 PID
        (0x239A, 0x8015),  # circuitplayground m0 PID prototype
        (0x239A, 0x801B),  # feather m0 express PID
    ]
)


# Cache module names for filename shadow checking later.
MODULE_NAMES = set([name for _, name, _ in pkgutil.iter_modules()])
MODULE_NAMES.add("sys")
MODULE_NAMES.add("builtins")


def get_default_workspace():
    """
    Return the location on the filesystem for opening and closing files.

    The default is to use a directory in the users home folder, however
    in some network systems this in inaccessible. This allows a key in the
    settings file to be used to set a custom path.
    """
    sp = get_settings_path()
    workspace_dir = os.path.join(HOME_DIRECTORY, WORKSPACE_NAME)
    settings = {}
    try:
        with open(sp) as f:
            settings = json.load(f)
    except FileNotFoundError:
        logger.error("Settings file {} does not exist.".format(sp))
    except ValueError:
        logger.error("Settings file {} could not be parsed.".format(sp))
    else:
        if "workspace" in settings:
            if os.path.isdir(settings["workspace"]):
                workspace_dir = settings["workspace"]
            else:
                logger.error(
                    "Workspace value in the settings file is not a valid"
                    "directory: {}".format(settings["workspace"])
                )
    return workspace_dir


class BaseMode(QObject):
    """
    Represents the common aspects of a mode.
    """

    name = "UNNAMED MODE"
    description = "DESCRIPTION NOT AVAILABLE."
    icon = "help"
    repl = None
    plotter = None
    is_debugger = False
    has_debugger = False
    save_timeout = 5  #: Number of seconds to wait before saving work.
    builtins = None  #: Symbols to assume as builtins when checking code style.
    file_extensions = []
    module_names = MODULE_NAMES
    code_template = _("# Write your code here :-)")

    def __init__(self, editor, view):
        self.editor = editor
        self.view = view
        super().__init__()

    def stop(self):
        """
        Called if/when the editor quits when in this mode. Override in child
        classes to clean up state, stop child processes etc.
        """
        pass  # Default is to do nothing

    def actions(self):
        """
        Return an ordered list of actions provided by this module. An action
        is a name (also used to identify the icon) , description, and handler.
        """
        return NotImplemented

    def workspace_dir(self):
        """
        Return the location on the filesystem for opening and closing files.

        The default is to use a directory in the users home folder, however
        in some network systems this in inaccessible. This allows a key in the
        settings file to be used to set a custom path.
        """
        return get_default_workspace()

    def assets_dir(self, asset_type):
        """
        Determine (and create) the directory for a set of assets

        This supports the [Images] and [Sounds] &c. buttons in pygamezero
        mode and possibly other modes, too.

        If a tab is current and has an active file, the assets directory
        is looked for under that path; otherwise the workspace directory
        is used.

        If the assets directory does not exist it is created
        """
        if self.view.current_tab and self.view.current_tab.path:
            base_dir = os.path.dirname(self.view.current_tab.path)
        else:
            base_dir = self.workspace_dir()
        assets_dir = os.path.join(base_dir, asset_type)
        os.makedirs(assets_dir, exist_ok=True)
        return assets_dir

    def api(self):
        """
        Return a list of API specifications to be used by auto-suggest and call
        tips.
        """
        return NotImplemented

    def set_buttons(self, **kwargs):
        """
        Given the names and boolean settings of buttons associated with actions
        for the current mode, toggles them into the boolean enabled state.
        """
        for k, v in kwargs.items():
            if k in self.view.button_bar.slots:
                self.view.button_bar.slots[k].setEnabled(bool(v))

    def return_focus_to_current_tab(self):
        """
        After, eg, stopping the plotter or closing the REPL return the focus
        to the currently-active tab is there is one.
        """
        if self.view.current_tab:
            self.view.current_tab.setFocus()

    def add_plotter(self):
        """
        Mode specific implementation of adding and connecting a plotter to
        incoming streams of data tuples.
        """
        return NotImplemented

    def remove_plotter(self):
        """
        If there's an active plotter, hide it.

        Save any data captured while the plotter was active into a directory
        called 'data_capture' in the workspace directory. The file contains
        CSV data and is named with a timestamp for easy identification.
        """
        data_dir = os.path.join(get_default_workspace(), "data_capture")
        if not os.path.exists(data_dir):
            logger.debug("Creating directory: {}".format(data_dir))
            os.makedirs(data_dir)
        # Save the raw data as CSV
        filename = "{}.csv".format(time.strftime("%Y%m%d-%H%M%S"))
        f = os.path.join(data_dir, filename)
        with open(f, "w") as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerows(self.view.plotter_pane.raw_data)
        self.view.remove_plotter()
        self.plotter = None
        logger.info("Removing plotter")
        self.return_focus_to_current_tab()

    def on_data_flood(self):
        """
        Handle when the plotter is being flooded by data (which usually causes
        Mu to become unresponsive). In this case, remove the plotter and
        display a warning dialog to explain what's happened and how to fix
        things (usually, put a time.sleep(x) into the code generating the
        data).
        """
        logger.error("Plotting data flood detected.")
        self.view.remove_plotter()
        self.plotter = None
        msg = _("Data Flood Detected!")
        info = _(
            "The plotter is flooded with data which will make Mu "
            "unresponsive and freeze. As a safeguard, the plotter has "
            "been stopped.\n\n"
            "Flooding is when chunks of data of more than 1024 bytes are "
            "repeatedly sent to the plotter.\n\n"
            "To fix this, make sure your code prints small tuples of "
            "data between calls to 'sleep' for a very short period of "
            "time."
        )
        self.view.show_message(msg, info)

    def open_file(self, path):
        """
        Some files are not plain text and each mode can attempt to decode them.

        When overridden, should return the text and newline convention for the
        file.
        """
        return None, None


class MicroPythonMode(BaseMode):
    """
    Includes functionality that works with a USB serial based REPL.
    """

    valid_boards = BOARD_IDS
    force_interrupt = True

    def find_device(self, with_logging=True):
        """
        Returns the port and serial number for the first MicroPython-ish device
        found connected to the host computer. If no device is found, returns
        the tuple (None, None).
        """
        available_ports = QSerialPortInfo.availablePorts()
        for port in available_ports:
            pid = port.productIdentifier()
            vid = port.vendorIdentifier()
            # Look for the port VID & PID in the list of known board IDs
            if (vid, pid) in self.valid_boards or (
                vid,
                None,
            ) in self.valid_boards:
                port_name = port.portName()
                serial_number = port.serialNumber()
                if with_logging:
                    logger.info("Found device on port: {}".format(port_name))
                    logger.info("Serial number: {}".format(serial_number))
                return (self.port_path(port_name), serial_number)
        if with_logging:
            logger.warning("Could not find device.")
            logger.debug("Available ports:")
            logger.debug(
                [
                    "PID:0x{:04x} VID:0x{:04x} PORT:{}".format(
                        p.productIdentifier(),
                        p.vendorIdentifier(),
                        p.portName(),
                    )
                    for p in available_ports
                ]
            )
        return (None, None)

    def port_path(self, port_name):
        if os.name == "posix":
            # If we're on Linux or OSX reference the port is like this...
            return "/dev/{}".format(port_name)
        elif os.name == "nt":
            # On Windows simply return the port (e.g. COM0).
            return port_name
        else:
            # No idea how to deal with other OS's so fail.
            raise NotImplementedError('OS "{}" not supported.'.format(os.name))

    def toggle_repl(self, event):
        """
        Toggles the REPL on and off.
        """
        if self.repl:
            self.remove_repl()
            logger.info("Toggle REPL off.")
        else:
            self.add_repl()
            logger.info("Toggle REPL on.")

    def remove_repl(self):
        """
        If there's an active REPL, disconnect and hide it.
        """
        self.view.remove_repl()
        self.repl = False

    def add_repl(self):
        """
        Detect a connected MicroPython based device and, if found, connect to
        the REPL and display it to the user.
        """
        device_port, serial_number = self.find_device()
        if device_port:
            try:
                self.view.add_micropython_repl(
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

    def toggle_plotter(self, event):
        """
        Toggles the plotter on and off.
        """
        if self.plotter:
            self.remove_plotter()
            logger.info("Toggle plotter off.")
        else:
            self.add_plotter()
            logger.info("Toggle plotter on.")

    def add_plotter(self):
        """
        Check if REPL exists, and if so, enable the plotter pane!
        """
        device_port, serial_number = self.find_device()
        if device_port:
            try:
                self.view.add_micropython_plotter(device_port, self.name, self)
                logger.info("Started plotter")
                self.plotter = True
            except IOError as ex:
                logger.error(ex)
                self.plotter = False
                info = _(
                    "Click on the device's reset button, wait a few"
                    " seconds and then try again."
                )
                self.view.show_message(str(ex), info)
            except Exception as ex:
                logger.error(ex)
        else:
            message = _("Could not find an attached device.")
            information = _(
                "Please make sure the device is plugged into this"
                " computer.\n\nIt must have a version of"
                " MicroPython (or CircuitPython) flashed onto it"
                " before the Plotter will work.\n\nFinally, press"
                " the device's reset button and wait a few seconds"
                " before trying again."
            )
            self.view.show_message(message, information)

    def on_data_flood(self):
        """
        Ensure the REPL is stopped if there is data flooding of the plotter.
        """
        self.remove_repl()
        super().on_data_flood()


class FileManager(QObject):
    """
    Used to manage filesystem operations on connected MicroPython devices in a
    manner such that the UI remains responsive.

    Provides an FTP-ish API. Emits signals on success or failure of different
    operations.
    """

    # Emitted when the tuple of files on the device is known.
    on_list_files = pyqtSignal(tuple)
    # Emitted when the file with referenced filename is got from the device.
    on_get_file = pyqtSignal(str)
    # Emitted when the file with referenced filename is put onto the device.
    on_put_file = pyqtSignal(str)
    # Emitted when the file with referenced filename is deleted from the
    # device.
    on_delete_file = pyqtSignal(str)
    # Emitted when Mu is unable to list the files on the device.
    on_list_fail = pyqtSignal()
    # Emitted when the referenced file fails to be got from the device.
    on_get_fail = pyqtSignal(str)
    # Emitted when the referenced file fails to be put onto the device.
    on_put_fail = pyqtSignal(str)
    # Emitted when the referenced file fails to be deleted from the device.
    on_delete_fail = pyqtSignal(str)

    def __init__(self, port):
        """
        Initialise with a port.
        """
        super().__init__()
        self.port = port

    def on_start(self):
        """
        Run when the thread containing this object's instance is started so
        it can emit the list of files found on the connected device.
        """
        # Create a new serial connection.
        try:
            self.serial = Serial(self.port, 115200, timeout=1, parity="N")
            self.ls()
        except Exception as ex:
            logger.exception(ex)
            self.on_list_fail.emit()

    def ls(self):
        """
        List the files on the micro:bit. Emit the resulting tuple of filenames
        or emit a failure signal.
        """
        try:
            result = tuple(microfs.ls(self.serial))
            self.on_list_files.emit(result)
        except Exception as ex:
            logger.exception(ex)
            self.on_list_fail.emit()

    def get(self, device_filename, local_filename):
        """
        Get the referenced device filename and save it to the local
        filename. Emit the name of the filename when complete or emit a
        failure signal.
        """
        try:
            microfs.get(device_filename, local_filename, serial=self.serial)
            self.on_get_file.emit(device_filename)
        except Exception as ex:
            logger.error(ex)
            self.on_get_fail.emit(device_filename)

    def put(self, local_filename):
        """
        Put the referenced local file onto the filesystem on the micro:bit.
        Emit the name of the file on the micro:bit when complete, or emit
        a failure signal.
        """
        try:
            microfs.put(local_filename, target=None, serial=self.serial)
            self.on_put_file.emit(os.path.basename(local_filename))
        except Exception as ex:
            logger.error(ex)
            self.on_put_fail.emit(local_filename)

    def delete(self, device_filename):
        """
        Delete the referenced file on the device's filesystem. Emit the name
        of the file when complete, or emit a failure signal.
        """
        try:
            microfs.rm(device_filename, serial=self.serial)
            self.on_delete_file.emit(device_filename)
        except Exception as ex:
            logger.error(ex)
            self.on_delete_fail.emit(device_filename)


class StuduinoBitFileManager(FileManager):
    """
    Override on_start() and put() method for using to manage filesystem
    operations of Studuino:bit Mode.
    """

    def __init__(self, port):
        """
        Initialise with a port.
        """
        super().__init__(port)

    def on_start(self):
        """
        Run when the thread containing this object's instance is started so
        it can emit the tree of files found on the connected device.
        """
        # Create a new serial connection.
        try:
            self.serial = Serial(self.port, 115200, timeout=1, parity="N")
            self.tree()
        except Exception as ex:
            logger.exception(ex)
            self.on_list_fail.emit()

    def tree(self):
        """
        Tree the files on the Studuino:bit. Emit the resulting tuple of
        filenames or emit a failure signal.
        """
        try:
            result = tuple(microfs.tree(self.serial))
            self.on_list_files.emit(result)
        except Exception as ex:
            logger.exception(ex)
            self.on_list_fail.emit()

    def put(self, local_filename, dist):
        """
        Put the referenced local file onto the filesystem on the Studuino:bit.
        Emit the name of the file on the Studuino:bit when complete, or emit
        a failure signal.
        """
        try:
            filename = os.path.basename(local_filename)
            microfs.put(
                local_filename,
                target=dist + "/" + filename,
                serial=self.serial,
            )
            self.on_put_file.emit(filename)
        except Exception as ex:
            logger.error(ex)
            self.on_put_fail.emit(local_filename)
