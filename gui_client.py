import sys
import socket
import ssl
import threading
import os
import platform
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QWidget, QTextEdit, QLineEdit, QPushButton,
    QVBoxLayout, QFileDialog, QInputDialog, QMessageBox, QTabWidget,
    QListWidget, QLabel, QGridLayout
)
from PyQt5.QtCore import pyqtSignal, QObject, Qt

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5555

class ChatTab(QWidget):
    def __init__(self, chat_name):
        super().__init__()
        self.chat_name = chat_name
        self.layout = QVBoxLayout()
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.layout.addWidget(self.output)
        self.setLayout(self.layout)

    def append_message(self, message):
        self.output.append(message)

class TicTacToeWindow(QWidget):
    def __init__(self, client, opponent):
        super().__init__()
        self.client = client
        self.opponent = opponent
        self.setWindowTitle(f"Tic-Tac-Toe vs {opponent}")
        self.setFixedSize(300, 300)
        self.buttons = [[None for _ in range(3)] for _ in range(3)]
        self.game_active = True

        layout = QGridLayout()
        for i in range(3):
            for j in range(3):
                btn = QPushButton(" ")
                btn.setFixedSize(80, 80)
                btn.clicked.connect(lambda checked, row=i, col=j: self.make_move(row, col))
                layout.addWidget(btn, i, j)
                self.buttons[i][j] = btn
        self.setLayout(layout)

    def make_move(self, row, col):
        if not self.game_active or self.buttons[row][col].text() != " ":
            return
        print(f"[DEBUG] Sending move: row={row}, col={col} to {self.opponent}")
        self.client.ssl_sock.sendall(f"[TIC_TAC_TOE]:MOVE:{self.opponent}:{row}:{col}".encode())
        self.setEnabled(False)  # Disable until server confirms next turn

    def update_board(self, board, current_player):
        print(f"[DEBUG] Updating board for {self.client.username}, current_player={current_player}, enabled={current_player == self.client.username}")
        for i in range(3):
            for j in range(3):
                self.buttons[i][j].setText(board[i][j])
        self.game_active = True
        self.setEnabled(current_player == self.client.username)

    def show_result(self, message):
        self.game_active = False
        self.setEnabled(False)
        print(f"[DEBUG] Game result: {message}")
        QMessageBox.information(self, "Game Result", message)
        self.close()

    def show_error(self, message):
        print(f"[DEBUG] Game error: {message}")
        QMessageBox.warning(self, "Game Error", message)

    def closeEvent(self, event):
        self.client.tic_tac_toe_windows.pop(self.opponent, None)
        event.accept()

class Communicator(QObject):
    message_received = pyqtSignal(str, str)  # chat_name, message
    general_message = pyqtSignal(str)
    file_received = pyqtSignal(str, str)  # path, filename
    invite_received = pyqtSignal(str)
    create_tab = pyqtSignal(str)
    userlist_signal = pyqtSignal(list)
    tictactoe_invite = pyqtSignal(str)
    tictactoe_start = pyqtSignal(str, str)  # opponent, symbol
    tictactoe_state = pyqtSignal(list, str, str)  # board, current_player, opponent
    tictactoe_result = pyqtSignal(str)
    tictactoe_error = pyqtSignal(str, str)  # message, opponent

class ChatClient(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chat Client")
        self.resize(600, 600)

        self.comm = Communicator()
        self.comm.message_received.connect(self.add_message_to_chat)
        self.comm.general_message.connect(self.append_to_general)
        self.comm.file_received.connect(self.handle_received_file)
        self.comm.invite_received.connect(self.handle_invite_gui)
        self.comm.create_tab.connect(self.create_chat_tab)
        self.comm.userlist_signal.connect(self.handle_user_list)
        self.comm.tictactoe_invite.connect(self.handle_tictactoe_invite)
        self.comm.tictactoe_start.connect(self.handle_tictactoe_start)
        self.comm.tictactoe_state.connect(self.handle_tictactoe_state)
        self.comm.tictactoe_result.connect(self.handle_tictactoe_result)
        self.comm.tictactoe_error.connect(self.handle_tictactoe_error)

        self.tab_widget = QTabWidget()
        self.user_list = QListWidget()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a message...")
        self.send_btn = QPushButton("Send")
        self.file_btn = QPushButton("Send File")
        self.dm_btn = QPushButton("Request DM (Invite)")
        self.gc_btn = QPushButton("Request GC (Invite)")
        self.tictactoe_btn = QPushButton("Request Tic-Tac-Toe")
        self.logout_btn = QPushButton("Logout")
        self.file_list_label = QLabel("\U0001F4C2 Received Files:")
        self.file_list = QListWidget()
        self.open_file_btn = QPushButton("Open Selected File")

        layout = QVBoxLayout()
        layout.addWidget(self.tab_widget)
        layout.addWidget(self.user_list)
        layout.addWidget(self.input)
        layout.addWidget(self.send_btn)
        layout.addWidget(self.file_btn)
        layout.addWidget(self.dm_btn)
        layout.addWidget(self.gc_btn)
        layout.addWidget(self.tictactoe_btn)
        layout.addWidget(self.logout_btn)
        layout.addWidget(self.file_list_label)
        layout.addWidget(self.file_list)
        layout.addWidget(self.open_file_btn)
        self.setLayout(layout)

        self.send_btn.clicked.connect(self.send_message)
        self.file_btn.clicked.connect(self.send_file)
        self.dm_btn.clicked.connect(self.request_dm)
        self.gc_btn.clicked.connect(self.request_gc)
        self.tictactoe_btn.clicked.connect(self.request_tictactoe)
        self.logout_btn.clicked.connect(self.logout)
        self.open_file_btn.clicked.connect(self.open_selected_file)

        self.received_files_tab = ChatTab("Received Files")
        self.tab_widget.addTab(self.received_files_tab, "📁 Received Files")
        self.received_files = []
        self.selected_targets = []
        self.sock = None
        self.ssl_sock = None
        self.username = ""
        self.tic_tac_toe_windows = {}  # Dictionary to track games by opponent

        self.connect_to_server()

    def connect_to_server(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            self.ssl_sock = context.wrap_socket(self.sock, server_hostname=SERVER_HOST)
            self.ssl_sock.connect((SERVER_HOST, SERVER_PORT))
            print("[DEBUG] Connected to server")
            self.authenticate_user()
            threading.Thread(target=self.receive_messages, daemon=True).start()
        except Exception as e:
            print(f"[DEBUG] Connection failed: {e}")
            QMessageBox.critical(self, "Connection Error", f"Failed to connect to server: {e}")
            sys.exit(1)

    def authenticate_user(self):
        while True:
            action, ok = QInputDialog.getText(self, "Login or Register", "Type 'r' to Register or 'l' to Login:")
            if not ok or action not in ['r', 'l']:
                continue

            username, ok1 = QInputDialog.getText(self, "Username", "Enter username:")
            password, ok2 = QInputDialog.getText(self, "Password", "Enter password:", QLineEdit.Password)
            if not (ok1 and ok2 and username and password):
                continue

            try:
                data = self.ssl_sock.recv(1024).decode()
                print(f"[DEBUG] Received: {data}")
                self.ssl_sock.sendall(action.encode())

                data = self.ssl_sock.recv(1024).decode()
                print(f"[DEBUG] Received: {data}")
                self.ssl_sock.sendall(username.encode())

                data = self.ssl_sock.recv(1024).decode()
                print(f"[DEBUG] Received: {data}")
                self.ssl_sock.sendall(password.encode())

                result = self.ssl_sock.recv(1024).decode()
                print(f"[DEBUG] Authentication result: {result}")
                QMessageBox.information(self, "Authentication", result)
                if "successfully" in result.lower():
                    self.username = username
                    self.setWindowTitle(f"Chat Client - {self.username}")
                    break
                else:
                    continue
            except Exception as e:
                print(f"[DEBUG] Authentication error: {e}")
                QMessageBox.critical(self, "Error", f"Authentication failed: {e}")
                return

    def send_message(self):
        message = self.input.text().strip()
        if message:
            active_tab = self.tab_widget.currentWidget()
            if active_tab and active_tab.chat_name != "Received Files":
                chat_name = active_tab.chat_name
                msg = f"{self.username}: {message}"
                self.ssl_sock.sendall(f"[{chat_name}_MSG]:{msg}".encode())
                self.comm.message_received.emit(chat_name, msg)
            elif self.selected_targets:
                msg_with_targets = f"/to:{','.join(self.selected_targets)}|{message}"
                self.ssl_sock.sendall(msg_with_targets.encode())
                self.comm.general_message.emit(f"\U0001F5E8 You → {', '.join(self.selected_targets)}: {message}")
            else:
                self.ssl_sock.sendall(f"{self.username}: {message}".encode())
                self.comm.general_message.emit(f"\U0001F5E8 You: {message}")
            self.input.clear()

        if message.lower() in ["[LOGOUT]", "/exit"]:
            self.logout()

    def send_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if not file_path:
            return

        filename = os.path.basename(file_path)
        filesize = os.path.getsize(file_path)

        try:
            self.ssl_sock.sendall(b"/file")
            meta = f"{filename}|{filesize}".encode()
            self.ssl_sock.sendall(meta)
            with open(file_path, "rb") as f:
                while True:
                    data = f.read(4096)
                    if not data:
                        break
                    self.ssl_sock.sendall(data)
            self.comm.general_message.emit(f"\U0001F4E4 File {filename} sent successfully.")
        except Exception as e:
            self.comm.general_message.emit(f"\u274C Failed to send file: {e}")

    def request_dm(self):
        target, ok = QInputDialog.getText(self, "Direct Message (Invite)", "Enter target username:")
        if ok and target:
            self.ssl_sock.sendall(f"[DM_REQUEST]:{target}".encode())

    def request_gc(self):
        participants, ok = QInputDialog.getText(self, "Group Chat (Invite)", "Enter usernames (comma separated):")
        if ok and participants:
            user_list = participants.replace(" ", "").split(",")
            msg = "[GC_REQUEST]:" + ":".join(user_list)
            self.ssl_sock.sendall(msg.encode())

    def request_tictactoe(self):
        target, ok = QInputDialog.getText(self, "Tic-Tac-Toe", "Enter opponent username:")
        if ok and target:
            if target in self.tic_tac_toe_windows:
                QMessageBox.warning(self, "Tic-Tac-Toe", f"You already have an active game with {target}.")
                return
            self.ssl_sock.sendall(f"[TIC_TAC_TOE]:REQUEST:{target}".encode())

    def receive_messages(self):
        while True:
            try:
                data = self.ssl_sock.recv(4096).decode(errors="ignore")
                print(f"[DEBUG] Received data: {data}")
                if not data:
                    break
                if data.startswith("/file"):
                    meta = self.ssl_sock.recv(1024).decode()
                    print(f"[DEBUG] File meta: {meta}")
                    filename, filesize = meta.split("|")
                    filesize = int(filesize)
                    saved_path = f"received_{filename}"
                    with open(saved_path, "wb") as f:
                        remaining = filesize
                        while remaining > 0:
                            chunk = self.ssl_sock.recv(min(4096, remaining))
                            if not chunk:
                                break
                            f.write(chunk)
                            remaining -= len(chunk)
                    self.received_files.append(saved_path)
                    self.comm.file_received.emit(saved_path, filename)
                elif data.startswith("[TIC_TAC_TOE]"):
                    parts = data.split(":", 2)
                    action = parts[1]
                    if action == "INVITE":
                        inviter = parts[2]
                        self.comm.tictactoe_invite.emit(inviter)
                    elif action == "START":
                        opponent, symbol = parts[2].split(":")
                        self.comm.tictactoe_start.emit(opponent, symbol)
                    elif action == "STATE":
                        board_and_player = parts[2].rsplit(":", 1)
                        board_str = board_and_player[0]
                        current_player = board_and_player[1]
                        board_rows = board_str.split("\n")
                        board = [row.split("|") for row in board_rows]
                        print(f"[DEBUG] Parsed board: {board}, current_player: {current_player}")
                        opponent = [opp for opp, win in self.tic_tac_toe_windows.items() if win.game_active]
                        opponent = opponent[0] if opponent else ""
                        self.comm.tictactoe_state.emit(board, current_player, opponent)
                    elif action == "RESULT":
                        result = parts[2]
                        self.comm.tictactoe_result.emit(result)
                    elif action == "ERROR":
                        opponent, message = parts[2].split(":", 1)
                        self.comm.tictactoe_error.emit(message, opponent)
                elif data.startswith("[INVITE]"):
                    self.comm.invite_received.emit(data)
                elif data.startswith("[FILE]:"):
                    parts = data.split(":")
                    if len(parts) < 4:
                        continue
                    filename, sender, filesize = parts[1], parts[2], int(parts[3])
                    remaining = filesize
                    file_data = b""
                    while remaining > 0:
                        chunk = self.ssl_sock.recv(min(4096, remaining))
                        if not chunk:
                            break
                        file_data += chunk
                        remaining -= len(chunk)
                    saved_path = f"received_{filename}"
                    with open(saved_path, "wb") as f:
                        f.write(file_data)
                    self.received_files.append(saved_path)
                    self.comm.file_received.emit(saved_path, filename)
                elif "ACTIVE USERS" in data:
                    users = data.replace("ACTIVE USERS: ", "").split(", ")
                    self.comm.userlist_signal.emit(users)
                elif "_MSG]:" in data:
                    chat_name, message = data.split("_MSG]:", 1)
                    self.comm.message_received.emit(chat_name.strip("["), message.strip())
                else:
                    self.comm.general_message.emit(data)
            except Exception as e:
                print(f"[DEBUG] Receive error: {e}")
                self.comm.general_message.emit(f"\u274C Disconnected from server: {str(e)}")
                break

    def create_chat_tab(self, chat_name):
        chat_tab = ChatTab(chat_name)
        self.tab_widget.addTab(chat_tab, chat_name)

    def add_message_to_chat(self, chat_name, message):
        found = False
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if tab.chat_name == chat_name:
                tab.append_message(message)
                found = True
                break
        if not found:
            self.create_chat_tab(chat_name)
            self.add_message_to_chat(chat_name, message)

    def append_to_general(self, message):
        self.add_message_to_chat("General", message)

    def handle_user_list(self, users):
        self.user_list.clear()
        self.user_list.addItems(users)

    def handle_received_file(self, path, filename):
        self.received_files_tab.append_message(f"Received: {filename}")
        self.file_list.addItem(filename)

    def open_selected_file(self):
        selected_items = self.file_list.selectedItems()
        if selected_items:
            selected_filename = selected_items[0].text()
            for path in self.received_files:
                if selected_filename in path:
                    try:
                        if platform.system() == "Windows":
                            os.startfile(path)
                        elif platform.system() == "Darwin":
                            subprocess.call(["open", path])
                        else:
                            subprocess.call(["xdg-open", path])
                    except Exception as e:
                        self.append_to_general(f"\u26A0\uFE0F Could not open file: {e}")
                    break

    def handle_invite_gui(self, msg):
        response = QMessageBox.question(self, "Invitation", msg, QMessageBox.Yes | QMessageBox.No)
        inviter = msg.split(" ")[1]
        reply = "yes" if response == QMessageBox.Yes else "no"
        self.ssl_sock.sendall(f"[INVITE_REPLY]:{inviter}:{reply}".encode())

    def handle_tictactoe_invite(self, inviter):
        if inviter in self.tic_tac_toe_windows:
            self.ssl_sock.sendall(f"[TIC_TAC_TOE]:REJECT:{inviter}".encode())
            self.comm.general_message.emit(f"\U0001F6AB Already in a game with {inviter}.")
            return
        response = QMessageBox.question(self, "Tic-Tac-Toe Invite",
                                       f"{inviter} wants to play Tic-Tac-Toe. Accept?",
                                       QMessageBox.Yes | QMessageBox.No)
        reply = "ACCEPT" if response == QMessageBox.Yes else "REJECT"
        self.ssl_sock.sendall(f"[TIC_TAC_TOE]:{reply}:{inviter}".encode())

    def handle_tictactoe_start(self, opponent, symbol):
        if opponent not in self.tic_tac_toe_windows:
            self.tic_tac_toe_windows[opponent] = TicTacToeWindow(self, opponent)
            self.tic_tac_toe_windows[opponent].show()
        self.comm.general_message.emit(f"\U0001F3B2 Tic-Tac-Toe started with {opponent}. You are {symbol}.")

    def handle_tictactoe_state(self, board, current_player, opponent):
        if opponent in self.tic_tac_toe_windows and self.tic_tac_toe_windows[opponent].game_active:
            self.tic_tac_toe_windows[opponent].update_board(board, current_player)

    def handle_tictactoe_error(self, message, opponent):
        if opponent in self.tic_tac_toe_windows and self.tic_tac_toe_windows[opponent].game_active:
            self.tic_tac_toe_windows[opponent].show_error(message)
        else:
            self.comm.general_message.emit(f"\U0001F6AB Tic-Tac-Toe error with {opponent}: {message}")

    def handle_tictactoe_result(self, result):
        for opponent, window in list(self.tic_tac_toe_windows.items()):
            if window.game_active:
                window.show_result(result)
        self.tic_tac_toe_windows.clear()

    def logout(self):
        confirm = QMessageBox.question(self, "Logout", "Are you sure you want to logout?",
                                       QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            try:
                self.ssl_sock.sendall("[LOGOUT]".encode())
            except:
                pass
            try:
                self.ssl_sock.close()
            except:
                pass
            QApplication.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    client = ChatClient()
    client.show()
    sys.exit(app.exec_())