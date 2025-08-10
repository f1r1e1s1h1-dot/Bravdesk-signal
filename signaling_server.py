import os
import socketio
from aiohttp import web

# Async server (tuned keep-alives for Render)
sio = socketio.AsyncServer(
    cors_allowed_origins='*',
    async_mode='aiohttp',
    ping_interval=25,  # seconds between pings
    ping_timeout=60    # consider client dead after this many seconds
)
app = web.Application()
sio.attach(app)

# room_id -> {"host": sid, "client": sid}
peers = {}
# room_id -> pin string
pins = {}

@sio.event
async def connect(sid, environ):
    print(f"[+] Connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"[-] Disconnected: {sid}")
    # find and clean up the room this sid belonged to
    for room_id in list(peers.keys()):
        roles = peers[room_id]
        if sid in roles.values():
            # notify remaining peer (use room broadcast)
            await sio.emit("peer_disconnected", room=room_id)  # underscore to match client
            # leave room and cleanup
            try:
                await sio.leave_room(sid, room_id)
            except Exception:
                pass
            del peers[room_id]
            pins.pop(room_id, None)
            break

@sio.event
async def join(sid, data):
    room_id = data["room"]
    role = data["role"]

    if room_id not in peers:
        peers[room_id] = {}

    peers[room_id][role] = sid

    # IMPORTANT: await room join
    await sio.enter_room(sid, room_id)
    print(f"[JOIN] {role} ({sid}) -> room {room_id}")

    # host can set PIN
    if role == "host" and "pin" in data:
        pins[room_id] = data["pin"]
        print(f"[PIN SET] Room {room_id}: {data['pin']}")

    # when both sides are present, tell them to start
    if len(peers[room_id]) == 2:
        await sio.emit("ready", room=room_id)
        print(f"[READY] room {room_id}")

@sio.event
async def verify_pin(sid, data):
    room_id = data.get("room")
    entered_pin = data.get("pin")
    ok = (entered_pin == pins.get(room_id))
    await sio.emit("pin_verified", {"ok": ok}, to=sid)
    print(f"[PIN CHECK] room {room_id} -> {ok}")

@sio.event
async def signal(sid, data):
    """
    Relay SDP/ICE from one peer to the other peer in the same room.
    """
    room_id = data["room"]
    payload = data["data"]
    role = data["role"]
    other = "client" if role == "host" else "host"

    target_sid = peers.get(room_id, {}).get(other)
    if not target_sid:
        # other peer not present yet; ignore or buffer server-side if you wish
        print(f"[SIGNAL DROP] room {room_id}: no '{other}' yet")
        return

    await sio.emit("signal", {"data": payload, "from": role}, to=target_sid)

    # Optional debug:
    if "sdp" in payload:
        print(f"[SDP] {role} -> {other} room {room_id} type={payload.get('type')}, sdp_len={len(payload.get('sdp',''))}")
    elif "candidate" in payload:
        print(f"[ICE] {role} -> {other} room {room_id}: {('end' if payload['candidate'] is None else 'cand')}")

if __name__ == "__main__":
    # Use Render-provided port if present; fallback for local dev
    port = int(os.environ.get("PORT", 9999))
    print(f"[BOOT] Listening on 0.0.0.0:{port}")
    web.run_app(app, host="0.0.0.0", port=port)
