import socket
import ssl
import threading
import json
import hashlib
import os

# --- Global Structures ---
clients = {}           # username -> conn
client_names = {}      # conn -> username
lock = threading.Lock()
received_dir = "received_files"
games = {}             # (player1, player2) -> game_state
pending_games = {}     # (inviter, target) -> {'inviter': inviter, 'target': target}

# --- File for storing users ---
USER_FILE = "users2.json"
if not os.path.exists(USER_FILE):
    with open(USER_FILE, "w") as f:
        json.dump({}, f)

# Ensure received files directory exists
os.makedirs(received_dir, exist_ok=True)

# --- Server Setup ---
HOST = '127.0.0.1'
PORT = 5555

# --- Helper Functions ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def load_users():
    try:
        with open(USER_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("[ERROR] Invalid JSON format.")
        return {}

def save_users(users):
    with open(USER_FILE, "w") as f:
        json.dump(users, f, indent=4)

def authenticate(conn):
    conn.sendall(b"[AUTH] Register or Login? (r/l):")
    choice = conn.recv(1024).decode().strip().lower()
    conn.sendall(b"[AUTH] Username:")
    username = conn.recv(1024).decode().strip()
    conn.sendall(b"[AUTH] Password:")
    password = conn.recv(1024).decode().strip()
    users = load_users()

    if choice == 'r':
        if username in users:
            conn.sendall(b"[AUTH] Username already exists.\n")
            return None
        users[username] = hash_password(password)
        save_users(users)
        conn.sendall(b"[AUTH] Registered successfully.\n")
        return username
    elif choice == 'l':
        if username not in users or users[username] != hash_password(password):
            conn.sendall(b"[AUTH] Invalid credentials.\n")
            return None
        conn.sendall(b"[AUTH] Logged in successfully.\n")
        return username
    else:
        conn.sendall(b"[AUTH] Invalid choice.\n")
        return None

def broadcast(message, exclude=None):
    for client in clients.values():
        if client != exclude:
            try:
                client.sendall(message)
            except:
                pass

def send_to_targets(message, targets, sender_socket):
    for target in targets:
        target = target.strip()
        if target in clients:
            try:
                clients[target].sendall(message)
            except:
                clients[target].close()
                del clients[target]

def send_invite(sender, target, chat_type):
    if target not in clients:
        clients[sender].sendall(f"[SERVER] User {target} not found.\n".encode())
        return
    invite = f"[INVITE] {sender} wants to start a {chat_type} chat with you. Accept? (yes/no):"
    clients[target].sendall(invite.encode())

def send_user_list():
    user_list = "ACTIVE USERS: " + ", ".join(clients.keys())
    broadcast(user_list.encode())

def receive_file(sock, sender_name, targets=None):
    try:
        meta = sock.recv(1024).decode()
        filename, filesize = meta.split("|")
        filesize = int(filesize)

        if filesize <= 0:
            print(f"[ERROR] Invalid filesize from {sender_name}")
            return

        file_path = os.path.join(received_dir, filename)
        print(f"[DEBUG] Receiving file: {filename} ({filesize} bytes) from {sender_name}")
        with open(file_path, "wb") as f:
            remaining = filesize
            while remaining > 0:
                chunk = sock.recv(min(4096, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)

        print(f"[INFO] File {filename} received from {sender_name}")

        recipients = targets if targets else [user for user, s in clients.items() if s != sock]
        for user in recipients:
            if user in clients:
                try:
                    print(f"[DEBUG] Forwarding file to {user}")
                    clients[user].sendall(b"/file")
                    clients[user].sendall(meta.encode())
                    with open(file_path, "rb") as f:
                        while True:
                            data = f.read(4096)
                            if not data:
                                break
                            clients[user].sendall(data)
                except Exception as e:
                    print(f"[ERROR] Sending file to {user}: {e}")
    except Exception as e:
        print(f"[ERROR] File reception error: {e}")

def initialize_game(player1, player2):
    return {
        'board': [[' ' for _ in range(3)] for _ in range(3)],
        'current_player': player1,
        'player1': player1,  # X
        'player2': player2,  # O
        'symbols': {player1: 'X', player2: 'O'},
        'turn_count': 0
    }

def check_winner(board, symbol):
    for row in board:
        if all(cell == symbol for cell in row):
            return True
    for col in range(3):
        if all(board[row][col] == symbol for row in range(3)):
            return True
    if all(board[i][i] == symbol for i in range(3)):
        return True
    if all(board[i][2-i] == symbol for i in range(3)):
        return True
    return False

def is_board_full(board):
    return all(cell != ' ' for row in board for cell in row)

def send_game_state(game, player1, player2):
    board_str = '\n'.join(['|'.join(row) for row in game['board']])
    message = f"[TIC_TAC_TOE]:STATE:{board_str}:{game['current_player']}"
    print(f"[DEBUG] Sending game state to {player1} and {player2}: {message}")
    try:
        if player1 in clients:
            clients[player1].sendall(message.encode())
        else:
            print(f"[DEBUG] {player1} not in clients")
        if player2 in clients:
            clients[player2].sendall(message.encode())
        else:
            print(f"[DEBUG] {player2} not in clients")
    except Exception as e:
        print(f"[ERROR] Sending game state: {e}")

def handle_client(conn, addr):
    username = None
    try:
        while not username:
            username = authenticate(conn)
        with lock:
            clients[username] = conn
            client_names[conn] = username

        conn.sendall(f"[SERVER] Welcome {username}!\n".encode())
        print(f"[+] {username} connected from {addr}")
        send_user_list()
        broadcast(f"[SERVER] {username} joined the chat.\n".encode(), exclude=conn)

        while True:
            data = conn.recv(4096)
            if not data:
                break

            msg = data.decode(errors="ignore")
            print(f"[DEBUG] Received from {username}: {msg}")
            if msg.startswith("[DM_REQUEST]"):
                _, target = msg.strip().split(":")
                send_invite(username, target, "DM")

            elif msg.startswith("[GC_REQUEST]"):
                participants = msg.strip().split(":")[1:]
                for user in participants:
                    send_invite(username, user, "Group Chat")

            elif msg.startswith("[INVITE_REPLY]"):
                _, sender, reply = msg.strip().split(":")
                if reply == "yes":
                    clients[sender].sendall(f"[SERVER] {username} accepted your invitation.\n".encode())
                else:
                    clients[sender].sendall(f"[SERVER] {username} rejected your invitation.\n".encode())

            elif msg.startswith("[TIC_TAC_TOE]"):
                parts = msg.split(":")
                action = parts[1]
                if action == "REQUEST":
                    target = parts[2]
                    if target not in clients:
                        clients[username].sendall(f"[SERVER] User {target} not found.\n".encode())
                        continue
                    game_key = tuple(sorted([username, target]))
                    if game_key in games or game_key in pending_games:
                        clients[username].sendall(f"[SERVER] Game already exists or pending with {target}.\n".encode())
                        continue
                    pending_games[game_key] = {'inviter': username, 'target': target}
                    invite = f"[TIC_TAC_TOE]:INVITE:{username}"
                    clients[target].sendall(invite.encode())
                elif action == "ACCEPT":
                    opponent = parts[2]
                    game_key = tuple(sorted([username, opponent]))
                    if game_key not in pending_games:
                        clients[username].sendall(f"[SERVER] No pending game invitation from {opponent}.\n".encode())
                        continue
                    games[game_key] = initialize_game(pending_games[game_key]['inviter'], username)
                    player1, player2 = games[game_key]['player1'], games[game_key]['player2']
                    clients[player1].sendall(f"[TIC_TAC_TOE]:START:{player2}:X".encode())
                    clients[player2].sendall(f"[TIC_TAC_TOE]:START:{player1}:O".encode())
                    send_game_state(games[game_key], player1, player2)
                    clients[username].sendall(f"[SERVER] Tic-Tac-Toe started with {opponent}. You are O.\n".encode())
                    clients[opponent].sendall(f"[SERVER] Tic-Tac-Toe started with {username}. You are X.\n".encode())
                    del pending_games[game_key]
                elif action == "REJECT":
                    opponent = parts[2]
                    game_key = tuple(sorted([username, opponent]))
                    if game_key in pending_games:
                        clients[opponent].sendall(f"[SERVER] {username} rejected your Tic-Tac-Toe invitation.\n".encode())
                        del pending_games[game_key]
                elif action == "MOVE":
                    opponent = parts[2]
                    row, col = int(parts[3]), int(parts[4])
                    game_key = tuple(sorted([username, opponent]))
                    if game_key not in games:
                        clients[username].sendall(f"[TIC_TAC_TOE]:ERROR:{opponent}:No active game with {opponent}.".encode())
                        continue
                    game = games[game_key]
                    if game['current_player'] != username:
                        clients[username].sendall(f"[TIC_TAC_TOE]:ERROR:{opponent}:Not your turn.".encode())
                        continue
                    if not (0 <= row < 3 and 0 <= col < 3) or game['board'][row][col] != ' ':
                        clients[username].sendall(f"[TIC_TAC_TOE]:ERROR:{opponent}:Invalid move.".encode())
                        continue
                    symbol = game['symbols'][username]
                    game['board'][row][col] = symbol
                    game['turn_count'] += 1
                    game['current_player'] = game['player2'] if game['current_player'] == game['player1'] else game['player1']
                    print(f"[DEBUG] Updated current_player to {game['current_player']}")
                    send_game_state(game, game['player1'], game['player2'])
                    if check_winner(game['board'], symbol):
                        clients[username].sendall(f"[TIC_TAC_TOE]:RESULT:You win!".encode())
                        clients[opponent].sendall(f"[TIC_TAC_TOE]:RESULT:{username} wins!".encode())
                        del games[game_key]
                    elif is_board_full(game['board']):
                        clients[username].sendall(f"[TIC_TAC_TOE]:RESULT:Draw!".encode())
                        clients[opponent].sendall(f"[TIC_TAC_TOE]:RESULT:Draw!".encode())
                        del games[game_key]

            elif msg.startswith("[FILE]"):
                _, filename, size = msg.strip().split(":")
                size = int(size)
                content = conn.recv(size)
                broadcast(f"[FILE]:{filename}:{username}:{size}".encode(), exclude=conn)
                broadcast(content, exclude=conn)

            elif msg.startswith("/file"):
                receive_file(conn, username)

            elif msg.startswith("/to:"):
                try:
                    target_line, msg_body = msg[4:].split("|", 1)
                    target_users = target_line.split(",")
                    formatted = f"[DM from {username}]: {msg_body}"
                    send_to_targets(formatted.encode(), target_users, conn)
                except Exception as e:
                    conn.sendall(f"[ERROR] Failed to send DM: {e}".encode())

            elif msg.startswith("["):
                if "_MSG]:" in msg:
                    chat_name, message = msg.split("_MSG]:", 1)
                    chat_name = chat_name.strip("[")
                    broadcast(f"[{chat_name}_MSG]:{message}".encode(), exclude=conn)
                else:
                    broadcast(msg.encode(), exclude=conn)

            elif msg == "[LOGOUT]" or msg == "/exit":
                break

            else:
                broadcast(f"{username}: {msg}".encode(), exclude=conn)

    except Exception as e:
        print(f"[-] Error with {username or addr}: {e}")
    finally:
        print(f"[-] {username} disconnected.")
        with lock:
            if username in clients:
                del clients[username]
            if conn in client_names:
                del client_names[conn]
            for game_key in list(games.keys()):
                if username in game_key:
                    opponent = game_key[0] if game_key[1] == username else game_key[1]
                    if opponent in clients:
                        clients[opponent].sendall(f"[TIC_TAC_TOE]:RESULT:{username} disconnected. Game ended.".encode())
                    del games[game_key]
            for game_key in list(pending_games.keys()):
                if username in game_key:
                    opponent = game_key[0] if game_key[1] == username else game_key[1]
                    if opponent in clients:
                        clients[opponent].sendall(f"[SERVER] {username} disconnected. Tic-Tac-Toe invitation canceled.\n".encode())
                    del pending_games[game_key]
        broadcast(f"[SERVER] {username} left the chat.\n".encode())
        send_user_list()
        conn.close()

# --- SSL Context ---
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

# --- Start Server ---
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind((HOST, PORT))
    s.listen()
    print(f"SSL Server running at {HOST}:{PORT}")

    with context.wrap_socket(s, server_side=True) as ssock:
        while True:
            conn, addr = ssock.accept()
            thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            thread.start()