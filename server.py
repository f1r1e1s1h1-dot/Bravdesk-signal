from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

rooms = {}

@app.get("/")
def health():
    return "OK"

@socketio.on("connect")
def handle_connect():
    print("[+] Client connected")

@socketio.on("disconnect")
def handle_disconnect():
    print("[-] Client disconnected")

@socketio.on("verify_pin")
def verify_pin(data):
    room = data.get("room")
    pin = data.get("pin")
    if room in rooms and rooms[room]["pin"] == pin:
        emit("pin_verified", {"ok": True})
    else:
        emit("pin_verified", {"ok": False})

@socketio.on("join")
def join(data):
    room = data.get("room")
    role = data.get("role")
    pin = data.get("pin")

    if role == "host":
        rooms[room] = {"pin": pin}
        join_room(room)
        print(f"[HOST JOINED] Room {room}")
    else:
        if room not in rooms:
            emit("error", {"msg": "Room does not exist"})
            return
        join_room(room)
        emit("ready", room=room)
        print(f"[CLIENT JOINED] Room {room}")

@socketio.on("signal")
def signaling(data):
    room = data.get("room")
    emit("signal", data, room=room, include_self=False)

if __name__ == "__main__":
    # harmless when running under gunicorn; only used if you run `python server.py` locally
    socketio.run(app, host="0.0.0.0", port=10000)
