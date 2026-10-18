"""Sign-in page and dialogs (spec 4.10 and 5): browser, another device, API key.

Network work runs on workers; every widget change happens on the main thread
through the runtime's dispatcher.
"""

from __future__ import annotations

import threading

from ..core import links
from ..core.auth import parse_key_pair
from .common import copy_text, error_text, heading, link_label, message_label, open_url, show_message
from .qt import QtCore, QtWidgets, dpi


class SignInPage(QtWidgets.QWidget):
    """First-run page. ``signed_in`` fires once the session holds credentials."""

    signed_in = QtCore.Signal()

    def __init__(self, runtime, parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._cancel: threading.Event | None = None

        title = heading("Scenario", 1.6)
        tagline = QtWidgets.QLabel("Every Scenario model, inside Maya.")
        self.browser_button = QtWidgets.QPushButton("Sign in with Scenario")
        self.browser_button.setToolTip("Opens your browser to sign in to Scenario.")
        self.browser_button.setMinimumHeight(dpi(32))
        self.browser_button.setDefault(True)
        self.browser_button.clicked.connect(self.sign_in_browser)
        self.browser_note = QtWidgets.QLabel("Opens your browser.")
        others = link_label('<a href="device">Sign in on another device</a> &nbsp;·&nbsp; <a href="key">Use an API key</a>', self._on_link)
        account = link_label('<a href="signup">Create an account</a>', self._on_link)
        self.status = message_label()
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setToolTip("Stops waiting for the browser.")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        privacy = link_label(
            'Prompts and files you send go to Scenario. Nothing is sent until you press Generate or allow an agent to. <a href="privacy">Privacy</a>',
            self._on_link,
        )
        privacy.setStyleSheet("color: palette(mid);")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpi(16), dpi(24), dpi(16), dpi(16))
        layout.setSpacing(dpi(8))
        for widget in (title, tagline):
            layout.addWidget(widget, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(dpi(12))
        layout.addWidget(self.browser_button)
        layout.addWidget(self.browser_note, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(dpi(4))
        layout.addWidget(others, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(account, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.status)
        layout.addWidget(self.cancel_button, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        layout.addWidget(privacy)
        for label in (others, account):
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)

    # -- flows -----------------------------------------------------------

    def _on_link(self, href: str) -> None:
        if href == "device":
            self.sign_in_device()
        elif href == "key":
            self.sign_in_api_key()
        elif href == "signup":
            open_url(links.SIGN_UP)
        elif href == "privacy":
            open_url(links.PRIVACY)

    def _busy(self, text: str, cancellable: bool) -> None:
        self.browser_button.setEnabled(False)
        show_message(self.status, text)
        self.cancel_button.setVisible(cancellable)

    def _idle(self, text: str = "", tone: str = "") -> None:
        self._cancel = None
        self.browser_button.setEnabled(True)
        self.cancel_button.hide()
        show_message(self.status, text, tone)

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
        self._idle("Sign-in canceled.")

    def _done(self, _result=None) -> None:
        self._idle()
        self.signed_in.emit()

    def _failed(self, error: BaseException) -> None:
        if self._cancel is not None and self._cancel.is_set():
            return
        self._idle(error_text(error), "error")

    def sign_in_browser(self) -> None:
        if self._cancel is not None:
            return
        cancel = self._cancel = threading.Event()
        self._busy("Waiting for your browser... Approve the sign-in there, then come back to Maya.", True)
        dispatcher = self.runtime.dispatcher
        session = self.runtime.session
        self.runtime.background(
            lambda: session.sign_in_browser(lambda url: dispatcher.call_on_main(open_url, url), cancel=cancel),
            on_done=self._done,
            on_error=self._failed,
        )

    def sign_in_device(self) -> None:
        dialog = DeviceDialog(self.runtime, self)
        if dialog.run():
            self._done()

    def sign_in_api_key(self) -> None:
        dialog = ApiKeyDialog(self.runtime, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self._done()


class DeviceDialog(QtWidgets.QDialog):
    """Shows the one-time code; the sign-in finishes when the code is approved."""

    def __init__(self, runtime, parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.cancel_event = threading.Event()
        self.device = None
        self.setWindowTitle("Sign in on another device")
        self.code = heading("", 2.0)
        self.code.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.where = QtWidgets.QLabel("Asking Scenario for a code...")
        self.where.setWordWrap(True)
        self.where.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status = message_label()
        self.open_button = QtWidgets.QPushButton("Open the page here")
        self.open_button.clicked.connect(lambda: open_url(self.device.verification_uri_complete or self.device.verification_uri))
        self.copy_button = QtWidgets.QPushButton("Copy code")
        self.copy_button.clicked.connect(lambda: copy_text(self.device.user_code))
        for button in (self.open_button, self.copy_button):
            button.setEnabled(False)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.open_button)
        row.addWidget(self.copy_button)
        row.addStretch(1)
        row.addWidget(cancel)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.where)
        layout.addWidget(self.code, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.status)
        layout.addLayout(row)
        self.setMinimumWidth(dpi(380))

    def _show_code(self, device) -> None:
        self.device = device
        self.code.setText(device.user_code)
        self.where.setText(f"On any device, go to {device.verification_uri} and enter this code. This window closes once you approve.")
        for button in (self.open_button, self.copy_button):
            button.setEnabled(True)

    def _failed(self, error: BaseException) -> None:
        if not self.cancel_event.is_set():
            show_message(self.status, error_text(error), "error")

    def run(self) -> bool:
        dispatcher = self.runtime.dispatcher
        session = self.runtime.session
        self.runtime.background(
            lambda: session.sign_in_device(lambda device: dispatcher.call_on_main(self._show_code, device), cancel=self.cancel_event),
            on_done=lambda _r: self.accept(),
            on_error=self._failed,
        )
        accepted = self.exec() == QtWidgets.QDialog.DialogCode.Accepted
        self.cancel_event.set()
        return accepted


class ApiKeyDialog(QtWidgets.QDialog):
    """API key and secret. The secret goes to the system keychain, never to settings."""

    def __init__(self, runtime, parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.setWindowTitle("Use a Scenario API key")
        self.key = QtWidgets.QLineEdit()
        self.key.setPlaceholderText("api_...")
        self.key.textEdited.connect(self._split_pair)
        self.secret = QtWidgets.QLineEdit()
        self.secret.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        intro = link_label(
            'Create a key in Scenario\'s web app (API keys), then paste the key and its secret. <a href="app">Open Scenario</a>',
            lambda _href: open_url(links.APP),
        )
        self.status = message_label()
        form = QtWidgets.QFormLayout()
        form.addRow("Key", self.key)
        form.addRow("Secret", self.secret)
        store = runtime.session.credentials.store
        where = {"memory": "memory for this session only", "file": "a file only you can read"}.get(store.name, f"your {store.name}")
        stored = QtWidgets.QLabel(f"The secret is kept in {where}, never in the scene or Maya's preferences.")
        stored.setWordWrap(True)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Sign in")
        self.buttons.accepted.connect(self._submit)
        self.buttons.rejected.connect(self.reject)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(stored)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self.setMinimumWidth(dpi(420))

    def _split_pair(self, text: str) -> None:
        key_id, secret = parse_key_pair(text.strip())
        if key_id and secret:
            self.key.setText(key_id)
            self.secret.setText(secret)

    def _submit(self) -> None:
        key_id, secret = self.key.text().strip(), self.secret.text().strip()
        if not key_id or not secret:
            show_message(self.status, "Enter both the key and its secret.", "error")
            return
        self.buttons.setEnabled(False)
        show_message(self.status, "Checking the key with Scenario...")

        def failed(error: BaseException) -> None:
            self.buttons.setEnabled(True)
            show_message(self.status, error_text(error), "error")

        self.runtime.background(lambda: self.runtime.session.sign_in_api_key(key_id, secret), on_done=lambda _r: self.accept(), on_error=failed)
