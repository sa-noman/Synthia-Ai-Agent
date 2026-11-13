"""Synthia Cloud Bridge — 4G/Mobile Data বা ফায়ারওয়াল-ব্লকড নেটওয়ার্ক থেকে ফোনের কমান্ড সরাসরি পিসিতে পৌঁছে দেয়।"""
from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import uuid
from collections import deque
from typing import Any

import httpx

BROKERS = [
    ("broker.emqx.io", 1883),
    ("broker.hivemq.com", 1883),
]


def get_bridge_id(access_token: str) -> str:
    return hashlib.sha256(f"synthia_bridge_{access_token}".encode("utf-8")).hexdigest()[:24]


def _encode_varlen(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        if n > 0:
            b |= 0x80
        out.append(b)
        if n == 0:
            break
    return bytes(out)


def _encode_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _pkt_connect(client_id: str) -> bytes:
    var_hdr = _encode_str("MQTT") + bytes([4, 2, 0, 30])  # clean session, keepalive 30s
    payload = _encode_str(client_id)
    rem = var_hdr + payload
    return bytes([0x10]) + _encode_varlen(len(rem)) + rem


def _pkt_subscribe(pkt_id: int, topic: str) -> bytes:
    rem = struct.pack("!H", pkt_id) + _encode_str(topic) + bytes([0])
    return bytes([0x82]) + _encode_varlen(len(rem)) + rem


def _pkt_publish(topic: str, data: bytes) -> bytes:
    rem = _encode_str(topic) + data
    return bytes([0x30]) + _encode_varlen(len(rem)) + rem


async def _read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    hdr = await reader.readexactly(1)
    pkt_type = hdr[0] >> 4
    mul = 1
    rem_len = 0
    while True:
        b = (await reader.readexactly(1))[0]
        rem_len += (b & 0x7F) * mul
        if (b & 0x80) == 0:
            break
        mul *= 128
    payload = await reader.readexactly(rem_len) if rem_len > 0 else b""
    return pkt_type, payload


class CloudBridge:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []
        self.connected_brokers: set[str] = set()
        self._seen_ids: deque[str] = deque(maxlen=300)
        self._app: Any = None
        self._bridge_id: str = ""
        self._stop = False

    def status(self) -> dict[str, Any]:
        return {
            "bridge_id": self._bridge_id,
            "connected": bool(self.connected_brokers),
            "brokers": sorted(self.connected_brokers),
        }

    def start(self, app: Any, access_token: str) -> None:
        if self.tasks:
            return
        self._app = app
        self._bridge_id = get_bridge_id(access_token)
        self._stop = False
        for host, port in BROKERS:
            self.tasks.append(asyncio.create_task(self._broker_loop(host, port)))

    async def stop(self) -> None:
        self._stop = True
        for t in self.tasks:
            t.cancel()
        self.tasks.clear()
        self.connected_brokers.clear()

    async def _handle_request(self, writer: asyncio.StreamWriter, write_lock: asyncio.Lock,
                              req_data: dict[str, Any]) -> None:
        req_id = str(req_data.get("req_id") or "").strip()
        if not req_id:
            return
        method = str(req_data.get("method") or "GET").upper()
        path = str(req_data.get("path") or "/api/mobile/ping")
        body_raw = req_data.get("body") or ""

        res_payload: dict[str, Any] = {"req_id": req_id, "ok": False, "status": 500, "body": "{}"}
        try:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765", timeout=120.0) as client:
                headers = {"host": "127.0.0.1:8765"}
                content = None
                if method in ("POST", "PUT", "PATCH") and body_raw:
                    headers["content-type"] = "application/json"
                    content = body_raw.encode("utf-8") if isinstance(body_raw, str) else json.dumps(body_raw).encode("utf-8")
                resp = await client.request(method, path, headers=headers, content=content)
                res_payload = {
                    "req_id": req_id,
                    "ok": 200 <= resp.status_code < 300,
                    "status": resp.status_code,
                    "body": resp.text,
                }
        except Exception as e:  # noqa: BLE001
            res_payload = {
                "req_id": req_id,
                "ok": False,
                "status": 500,
                "error": str(e),
                "body": json.dumps({"error": str(e)}),
            }

        res_topic = f"synthia/v1/{self._bridge_id}/res/{req_id}"
        pkt = _pkt_publish(res_topic, json.dumps(res_payload, ensure_ascii=False).encode("utf-8"))
        try:
            async with write_lock:
                writer.write(pkt)
                await writer.drain()
        except Exception:  # noqa: BLE001
            pass

    async def _broker_loop(self, host: str, port: int) -> None:
        req_topic = f"synthia/v1/{self._bridge_id}/req"
        while not self._stop:
            writer: asyncio.StreamWriter | None = None
            ping_task: asyncio.Task | None = None
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=8.0)
                cid = f"synthia_pc_{self._bridge_id[:8]}_{uuid.uuid4().hex[:6]}"
                writer.write(_pkt_connect(cid))
                await writer.drain()

                pkt_type, payload = await asyncio.wait_for(_read_packet(reader), timeout=8.0)
                if pkt_type != 2 or len(payload) < 2 or payload[1] != 0:
                    raise RuntimeError(f"MQTT CONNACK error: {pkt_type}")

                writer.write(_pkt_subscribe(1, req_topic))
                await writer.drain()
                self.connected_brokers.add(host)

                write_lock = asyncio.Lock()

                async def _keepalive() -> None:
                    while not self._stop:
                        await asyncio.sleep(20)
                        async with write_lock:
                            writer.write(bytes([0xC0, 0x00]))  # PINGREQ
                            await writer.drain()

                ping_task = asyncio.create_task(_keepalive())

                while not self._stop:
                    ptype, pdata = await asyncio.wait_for(_read_packet(reader), timeout=45.0)
                    if ptype == 3:  # PUBLISH
                        if len(pdata) < 2:
                            continue
                        tlen = struct.unpack("!H", pdata[:2])[0]
                        msg_bytes = pdata[2 + tlen:]
                        # QoS > 0 includes 2-byte packet id (skip if flags & 0x06, though QoS 0 doesn't)
                        try:
                            req_data = json.loads(msg_bytes.decode("utf-8"))
                        except Exception:
                            continue
                        rid = str(req_data.get("req_id") or "")
                        if not rid or rid in self._seen_ids:
                            continue
                        self._seen_ids.append(rid)
                        asyncio.create_task(self._handle_request(writer, write_lock, req_data))
                    elif ptype == 13:  # PINGRESP
                        continue
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                pass
            finally:
                self.connected_brokers.discard(host)
                if ping_task:
                    ping_task.cancel()
                if writer:
                    try:
                        writer.close()
                    except Exception:
                        pass
            if not self._stop:
                await asyncio.sleep(3.0)


cloud_bridge = CloudBridge()
