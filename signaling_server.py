import socketio
from aiohttp import web

sio = socketio.AsyncServer(cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

peers = {}
pins = {}

@sio.event
async def connect(sid, environ):
    print(f"[+] Connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"[-] Disconnected: {sid}")
    for room_id in list(peers.keys()):
        if sid in peers[room_id].values():
            await sio.emit("peer-disconnected", room=room_id)
            del peers[room_id]
            if room_id in pins:
                del pins[room_id]

@sio.event
async def join(sid, data):
    room_id = data["room"]
    role = data["role"]

    if room_id not in peers:
        peers[room_id] = {}

    peers[room_id][role] = sid
    sio.enter_room(sid, room_id)
    print(f"{role} joined room: {room_id}")

    if role == "host" and "pin" in data:
        pins[room_id] = data["pin"]
        print(f"[PIN SET] Room {room_id}: {data['pin']}")

    if len(peers[room_id]) == 2:
        await sio.emit("ready", room=room_id)

@sio.event
async def verify_pin(sid, data):
    room_id = data.get("room")
    entered_pin = data.get("pin")
    correct_pin = pins.get(room_id)

    if entered_pin == correct_pin:
        await sio.emit("pin-verified", {"ok": True}, to=sid)
    else:
        await sio.emit("pin-verified", {"ok": False}, to=sid)

@sio.event
async def signal(sid, data):
    room_id = data["room"]
    payload = data["data"]
    role = data["role"]

    other = "client" if role == "host" else "host"
    if room_id in peers and other in peers[room_id]:
        await sio.emit("signal", {"data": payload, "from": role}, to=peers[room_id][other])

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=9999)
