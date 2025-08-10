import os
import socketio
from aiohttp import web

# ---------- Socket.IO server (aiohttp) ----------
sio = socketio.AsyncServer(
    async_mode="aiohttp",
    cors_allowed_origins="*",
    ping_interval=25,
    ping_timeout=60,
)

app = web.Application()
sio.attach(app)

# room_id -> {"host": sid, "client": sid}
peers: dict[str, dict[str, str]] = {}
# room_id -> pin
pins: dict[str, str] = {}


# ----------------- Events -----------------
@sio.event
async def connect(sid, environ):
    print(f"[+] Connected: {sid}")


@sio.event
async def disconnect(sid):
    print(f"[-] Disconnected: {sid}")
    # find the room this sid belonged to
    for room_id, roles in list(peers.items()):
        # roles is like {"host": sid, "client": sid}
        if sid in roles.values():
            # notify remaining peer
            await sio.emit("peer_disconnected", room=room_id)
            # remove just this sid's role
            for role, r_sid in list(roles.items()):
                if r_sid == sid:
                    del roles[role]
            # if room now empty, drop state
            if not roles:
                peers.pop(room_id, None)
                pins.pop(room_id, None)
            # best-effort leave
            try:
                await sio.leave_room(sid, room_id)
            except Exception:
                pass
            break


@sio.event
async def join(sid, data):
    room_id = str(data["room"]).strip()
    role = data["role"]

    if room_id not in peers:
        peers[room_id] = {}

    peers[room_id][role] = sid
    await sio.enter_room(sid, room_id)
    print(f"[JOIN] {role} ({sid}) -> room {room_id}")

    # host can set PIN
    if role == "host" and "pin" in data and data["pin"] is not None:
        pins[room_id] = str(data["pin"])
        print(f"[PIN SET] room {room_id}: *****")

    # when both sides present, tell them to start
    if set(peers[room_id].keys()) == {"host", "client"}:
        await sio.emit("ready", room=room_id)
        print(f"[READY] room {room_id}")


@sio.event
async def verify_pin(sid, data):
    room_id = str(data.get("room")).strip()
    entered_pin = str(data.get("pin")) if data.get("pin") is not None else None
    ok = (entered_pin is not None and entered_pin == pins.get(room_id))
    await sio.emit("pin_verified", {"ok": ok}, to=sid)
    print(f"[PIN CHECK] room {room_id} -> {ok}")


@sio.event
async def signal(sid, data):
    """
    Relay SDP/ICE between peers in the same room.
    Payload example:
      { "room": "123", "role": "host",
        "data": {"sdp": "...", "type": "offer"} }
      or
      { "data": {"candidate": {...}} }  (or None for end-of-candidates)
    """
    room_id = str(data["room"]).strip()
    payload = data["data"]
    role = data["role"]
    other = "client" if role == "host" else "host"

    target_sid = peers.get(room_id, {}).get(other)
    if not target_sid:
        # other peer not present yet; drop or buffer if you want
        print(f"[SIGNAL DROP] room {room_id}: no '{other}' yet")
        return

    await sio.emit("signal", {"data": payload, "from": role}, to=target_sid)

    # Debug logs
    if isinstance(payload, dict) and "sdp" in payload:
        print(f"[SDP] {role} -> {other} room {room_id} type={payload.get('type')}, sdp_len={len(payload.get('sdp',''))}")
    elif isinstance(payload, dict) and "candidate" in payload:
        print(f"[ICE] {role} -> {other} room {room_id}: {('end' if payload['candidate'] is None else 'cand')}")


# ------------- Simple health & root routes -------------
async def health(request):
    return web.Response(text="ok")

async def index(request):
    return web.Response(text="Bravdesk signaling is running")


app.router.add_get("/", index)
app.router.add_get("/health", health)


# --------------- Entrypoint (Render) ---------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9999"))  # Render provides PORT
    print(f"[BOOT] Listening on 0.0.0.0:{port}")
    web.run_app(app, host="0.0.0.0", port=port)
