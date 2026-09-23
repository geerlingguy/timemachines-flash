#!/usr/bin/env python3
"""
tmflash.py - cross-platform replacement for TimeMachines TM-Flash (v1.7)
for Tiva-based clocks (tested design target: WiFi clock, serial "C", fw 3.7).

Protocol (reverse engineered from tmflash.exe 1.7 + clock firmware 3.7):
  1. Discovery (optional): UDP A1 04 B2 -> clock:7372, reply to host:7372.
     reply[0]=product kind, reply[5:11]=MAC, reply[11]=hw revision.
  2. GET  http://clock/var/www/update.html  (Authorization: Basic <md5hex(pw)>)
     -> body is a numeric challenge. 401 = bad password.
  3. POST http://clock/etc/update_code  body = "%d"*8 of
     out[i] = "TMachine"[i] ^ challenge[len-1-i]   (out[7] = ord('e'))
  4. UDP magic packet -> clock:9 : 0xAA*6 + MAC*4 (TI swupdate). Clock
     reboots into the TI Tiva Ethernet bootloader.
  5. Bootloader BOOTP request (sname "tiva") -> we reply on :68 with
     yiaddr=clock IP, siaddr=our IP, file "firmware.bin".
  6. Bootloader TFTP RRQ -> we serve the .bin in 512-byte blocks from :69.

Needs root (ports 67/69). Clock must be on WIRED Ethernet (bootloader is
Ethernet-only). Stop any local DHCP/BOOTP/TFTP servers first.
Unofficial; use at your own risk.
"""
import argparse, hashlib, http.client, socket, struct, sys, time

KINDS = {1: "PoE", 2: "WiFi", 3: "DotMatrix", 4: "kind4", 5: "TM1000A"}
# Last byte of firmware file -> (kind, hw rev) it targets (from tmflash.exe)
FW_TARGETS = {"A": (1, 4), "C": (2, 2), "E": (4, None), "G": (3, None),
              "H": (1, 5), "I": (2, 3)}
FW_NAMES = {"A": "PoE Type B", "C": "WiFi Type B", "E": "kind 4",
            "G": "DotMatrix", "H": "PoE Type C", "I": "WiFi Type C"}


def log(*a):
    print("[tmflash]", *a, flush=True)


def local_ip_for(dest):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((dest, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def discover(ip, timeout=2.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 7372))
    s.settimeout(timeout)
    try:
        s.sendto(bytes([0xA1, 0x04, 0xB2]), (ip, 7372))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                break
            if addr[0] == ip and len(data) in (35, 40, 80):
                return data
    finally:
        s.close()
    return None


def auth_header(password):
    return "Basic " + hashlib.md5(password.encode()).hexdigest()


def http_req(ip, method, path, password, body=None):
    c = http.client.HTTPConnection(ip, 80, timeout=10)
    headers = {"Authorization": auth_header(password),
               "Content-Type": "text/plain;charset=UTF-8"}
    c.request(method, path, body=body, headers=headers)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


def challenge_response(challenge):
    key = b"TMachine"
    ch = challenge.strip()
    out = []
    for i in range(len(key)):
        if i == 7:
            out.append(ord("e"))  # tmflash.exe hardcodes this byte
            continue
        j = len(ch) - 1 - i
        out.append(key[i] ^ (ch[j] if j >= 0 else 0))
    return "".join(str(b) for b in out)


def magic_packet(ip, mac):
    pkt = b"\xAA" * 6 + mac * 4
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(3):
        s.sendto(pkt, (ip, 9))
        time.sleep(0.1)
    s.close()


def build_bootp_reply(req, client_ip, server_ip, mac):
    r = bytearray(300)
    r[0:4] = b"\x02\x01\x06\x00"
    r[4:8] = req[4:8]                      # xid
    r[16:20] = socket.inet_aton(client_ip)  # yiaddr
    r[20:24] = socket.inet_aton(server_ip)  # siaddr
    r[28:34] = mac                          # chaddr
    r[44:48] = b"tiva"                      # sname
    r[108:120] = b"firmware.bin"            # file
    return bytes(r)


def serve(fw, client_ip, server_ip, mac, bootp_port=67, tftp_port=69,
          reply_port=68, timeout=90, broadcast_fallback=True):
    bs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    bs.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bs.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    bs.bind(("0.0.0.0", bootp_port))
    ts = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ts.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ts.bind(("0.0.0.0", tftp_port))
    bs.settimeout(0.5)
    ts.settimeout(0.5)

    log(f"waiting for BOOTP from {mac.hex(':')} (up to {timeout}s)...")
    deadline = time.time() + timeout
    replies = 0
    peer = None
    while time.time() < deadline and peer is None:
        try:
            req, _ = bs.recvfrom(1500)
            if (len(req) >= 236 and req[0] == 1 and req[28:34] == mac
                    and req[44:48] == b"tiva"):
                rep = build_bootp_reply(req, client_ip, server_ip, mac)
                dst = client_ip
                if broadcast_fallback and replies % 2 == 1:
                    dst = "255.255.255.255"
                bs.sendto(rep, (dst, reply_port))
                replies += 1
                log(f"BOOTP request seen, reply #{replies} -> {dst}:{reply_port}")
        except socket.timeout:
            pass
        try:
            pkt, addr = ts.recvfrom(1500)
            if pkt[:2] == b"\x00\x01":
                fname = pkt[2:].split(b"\0")[0].decode(errors="replace")
                log(f"TFTP RRQ '{fname}' from {addr[0]}:{addr[1]}")
                peer = addr
        except socket.timeout:
            pass
    bs.close()
    if peer is None:
        ts.close()
        raise SystemExit("timed out waiting for bootloader (BOOTP/TFTP)")

    nblocks = len(fw) // 512 + 1   # final short (possibly empty) block
    t0 = time.time()
    for blk in range(1, nblocks + 1):
        chunk = fw[(blk - 1) * 512: blk * 512]
        pkt = struct.pack(">HH", 3, blk & 0xFFFF) + chunk
        for attempt in range(20):
            ts.sendto(pkt, peer)
            acked = False
            end = time.time() + 1.0
            while time.time() < end:
                try:
                    ack, addr = ts.recvfrom(1500)
                except socket.timeout:
                    break
                if addr != peer or len(ack) < 4:
                    continue
                op, n = struct.unpack(">HH", ack[:4])
                if op == 5:
                    raise SystemExit(f"TFTP error from clock: {ack[4:]!r}")
                if op == 4 and n == blk & 0xFFFF:
                    acked = True
                    break
            if acked:
                break
        else:
            raise SystemExit(f"no ACK for block {blk}")
        pct = 100 * blk // nblocks
        print(f"\r[tmflash] sent block {blk}/{nblocks} ({pct}%)", end="", flush=True)
    print()
    ts.close()
    log(f"transfer done in {time.time() - t0:.1f}s; clock should reboot into new firmware")


def main():
    ap = argparse.ArgumentParser(description="TimeMachines Tiva clock firmware updater")
    ap.add_argument("ip", help="clock IP address")
    ap.add_argument("firmware", help="firmware .bin (e.g. wificlockMB_3_7_revCHW.bin)")
    ap.add_argument("-p", "--password", default="tmachine")
    ap.add_argument("--mac", help="clock MAC (aa:bb:..); default: discover it")
    ap.add_argument("--server-ip", help="this host's IP on the clock's LAN")
    ap.add_argument("--skip-trigger", action="store_true",
                    help="don't do HTTP/magic packet; just serve BOOTP/TFTP")
    ap.add_argument("--dry-run", action="store_true",
                    help="discover + challenge only, no magic packet")
    ap.add_argument("--force", action="store_true", help="skip firmware/device match check")
    ap.add_argument("--timeout", type=int, default=90)
    a = ap.parse_args()

    fw = open(a.firmware, "rb").read()
    tag = chr(fw[-1])
    log(f"firmware {len(fw)} bytes, target tag '{tag}' ({FW_NAMES.get(tag, 'unknown')})")

    info = discover(a.ip)
    if info:
        kind, rev = info[0], info[11]
        log(f"discovered {KINDS.get(kind, kind)} rev {rev}, MAC {info[5:11].hex(':')}")
        want = FW_TARGETS.get(tag)
        if want and not a.force and (want[0] != kind or (want[1] and want[1] != rev)):
            raise SystemExit("firmware does not match this device (use --force to override)")
    else:
        log("no discovery reply")

    if a.mac:
        mac = bytes.fromhex(a.mac.replace(":", "").replace("-", ""))
    elif info:
        mac = info[5:11]
    else:
        raise SystemExit("couldn't discover MAC; pass --mac")

    server_ip = a.server_ip or local_ip_for(a.ip)
    log(f"using host IP {server_ip}")

    if not a.skip_trigger:
        status, body = http_req(a.ip, "GET", "/var/www/update.html", a.password)
        if status == 401:
            raise SystemExit("401 Unauthorized - wrong password")
        if status == 200:
            code = challenge_response(body)
            log(f"challenge {body.strip().decode(errors='replace')!r} -> code {code}")
            if a.dry_run:
                return
            try:
                status, body = http_req(a.ip, "POST", "/etc/update_code", a.password, code)
                log(f"update_code POST -> HTTP {status} (a normal reply may mean the code was rejected)")
            except (ConnectionResetError, http.client.RemoteDisconnected,
                    http.client.BadStatusLine, socket.timeout) as e:
                # Firmware drops the connection without replying when the code is accepted
                log(f"update_code accepted (connection closed: {type(e).__name__})")
        elif status == 404:
            log("update.html 404 (older firmware?); sending magic packet directly")
        else:
            raise SystemExit(f"unexpected HTTP {status} from update.html")
        if a.dry_run:
            return
        magic_packet(a.ip, mac)
        log("magic packet sent; clock should reboot into bootloader")

    serve(fw, a.ip, server_ip, mac, timeout=a.timeout)


if __name__ == "__main__":
    main()
