import asyncio
import socketio
import json
import mss
import cv2
import numpy as np
import keyboard
import mouse
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, RTCDataChannel
from av import VideoFrame
import threading

# ------------------- CONFIG -------------------
SIGNALING_URL = "https://your-app-name.fly.dev"  # Replace with your actual deployed Fly.io server URL
# ---------------------------------------------

sio = socketio.AsyncClient()
pc = RTCPeerConnection()
dc = None

user_mode = tk.StringVar(value="host")
room_id = tk.StringVar()
pin_code = tk.StringVar()


# ----------------------- GUI ---------------------------
def start_gui():
    def run_backend():
        asyncio.run(main())

    def on_start():
        if not room_id.get().strip() or not pin_code.get().strip():
            messagebox.showerror("Missing Info", "Please enter Room ID and PIN.")
            return
        threading.Thread(target=run_backend, daemon=True).start()
        start_button.config(state=tk.DISABLED)

    root = tk.Tk()
    root.title("Remote Desktop Control")
    root.geometry("300x300")
    root.resizable(False, False)

    ttk.Label(root, text="Remote Desktop App", font=("Segoe UI", 14)).pack(pady=10)
    ttk.Label(root, text="Mode:").pack()
    ttk.Radiobutton(root, text="Host", variable=user_mode, value="host").pack()
    ttk.Radiobutton(root, text="Client", variable=user_mode, value="client").pack()
    ttk.Label(root, text="Room ID:").pack()
    ttk.Entry(root, textvariable=room_id).pack()
    ttk.Label(root, text="PIN:").pack()
    ttk.Entry(root, textvariable=pin_code, show="*").pack()

    global start_button
    start_button = ttk.Button(root, text="Start", command=on_start)
    start_button.pack(pady=10)

    ttk.Button(root, text="Exit", command=root.destroy).pack()
    root.mainloop()


# ------------------ HOST FUNCTIONS ---------------------
class ScreenStreamTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.sct = mss.mss()
        self.monitor = self.sct.monitors[1]

    async def recv(self):
        await asyncio.sleep(1 / 30)
        img = np.array(self.sct.grab(self.monitor))
        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts, video_frame.time_base = self.next_timestamp()
        return video_frame


def handle_input(message):
    import pyautogui
    try:
        event = json.loads(message)
        if event["type"] == "move":
            pyautogui.moveTo(event["x"], event["y"])
        elif event["type"] == "click":
            pyautogui.click()
        elif event["type"] == "keydown":
            pyautogui.keyDown(event["key"])
        elif event["type"] == "keyup":
            pyautogui.keyUp(event["key"])
    except Exception as e:
        print("Input error:", e)


# ------------------ CLIENT FUNCTIONS ---------------------
def send_input(data):
    global dc
    if dc and dc.readyState == "open":
        dc.send(json.dumps(data))


def start_input_capture():
    mouse.on_move(lambda: send_input({"type": "move", "x": mouse.get_position()[0], "y": mouse.get_position()[1]}))
    mouse.on_click(lambda: send_input({"type": "click"}))
    keyboard.on_press(lambda e: send_input({"type": "keydown", "key": e.name}))
    keyboard.on_release(lambda e: send_input({"type": "keyup", "key": e.name}))


@pc.on("track")
def on_track(track):
    print("[*] Receiving video...")
    async def recv():
        while True:
            frame = await track.recv()
            img = frame.to_ndarray(format="bgr24")
            cv2.imshow("Remote Desktop", img)
            if cv2.waitKey(1) == ord('q'):
                break
        cv2.destroyAllWindows()
    asyncio.ensure_future(recv())


# ------------------- SIGNALING ----------------------
@sio.event
async def connect():
    print("[+] Connected to signaling server")
    await sio.emit("verify_pin", {"room": room_id.get(), "pin": pin_code.get()})


@sio.event
async def pin_verified(data):
    if not data.get("ok"):
        print("[X] Incorrect PIN. Closing.")
        await sio.disconnect()
        return

    print("[✓] PIN verified")
    await sio.emit("join", {
        "room": room_id.get(),
        "role": user_mode.get(),
        "pin": pin_code.get() if user_mode.get() == "host" else None
    })


@sio.event
async def ready():
    if user_mode.get() == "host":
        pc.addTrack(ScreenStreamTrack())

        @pc.on("datachannel")
        def on_datachannel(channel: RTCDataChannel):
            print("[*] DataChannel open")
            channel.on("message", handle_input)

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        await sio.emit("signal", {
            "room": room_id.get(),
            "role": "host",
            "data": {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            }
        })
    else:
        global dc
        dc = pc.createDataChannel("control")
        start_input_capture()


@sio.event
async def signal(data):
    msg = data["data"]
    if "sdp" in msg:
        desc = RTCSessionDescription(**msg)
        await pc.setRemoteDescription(desc)
        if desc["type"] == "offer":
            await pc.setLocalDescription(await pc.createAnswer())
            await sio.emit("signal", {
                "room": room_id.get(),
                "role": user_mode.get(),
                "data": {
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type
                }
            })
    elif "candidate" in msg:
        await pc.addIceCandidate(msg)


@sio.event
async def peer_disconnected():
    print("[!] Other peer disconnected.")
    await pc.close()


async def main():
    await sio.connect(SIGNALING_URL)
    await sio.wait()


if __name__ == "__main__":
    start_gui()
