"""Office-network (LAN) helpers: this PC's addresses, the links colleagues use, who may connect, firewall check.

The app runs on ONE PC (the host). Everyone else in the office opens  http://<host IP>:8080  in a browser - nothing is
installed on their PCs. The host's IP is found at start-up (it can change with DHCP), so no address is hard-coded."""
from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import sys

RULE_NAME = "MURAFLEX AUTOMATION"

# who may use the app: this PC and private office networks only (never the public internet)
DEFAULT_ALLOW = "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,::1/128,fe80::/10,fc00::/7"


def _private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.version == 4 and not a.is_loopback and not a.is_link_local and (a.is_private or a.is_global)


def lan_ips() -> list:
    """IPv4 addresses of this PC that other PCs can reach (office network first)."""
    found = []
    # the address of the network card that carries traffic (no packet is sent: UDP connect only picks a route)
    for probe in ("10.255.255.255", "192.168.255.255", "8.8.8.8"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.2)
            s.connect((probe, 1))
            found.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    try:
        found += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    out = []
    for ip in found:
        if _private(ip) and ip not in out:
            out.append(ip)
    # keep discovery order: the first one is the network card that actually carries office traffic
    # (so a VirtualBox / VPN adapter such as 192.168.56.1 never comes before 192.168.8.87)
    out.sort(key=lambda ip: not ipaddress.ip_address(ip).is_private)
    pinned = os.environ.get("GLASS_PUBLIC", "").strip()           # optional fixed address/name to show first
    return ([pinned] if pinned and pinned not in out else []) + out


def host_names() -> list:
    """This PC's network names (computer name and its full office-domain name)."""
    names = []
    for n in (socket.gethostname(), socket.getfqdn()):
        if n and n not in names and n.lower() not in ("localhost", "localhost.localdomain") and not n.startswith("127."):
            names.append(n)
    return names


def share_urls(port: int) -> list:
    """Links for colleagues: IP address(es) first, then the computer name."""
    return [f"http://{h}:{port}" for h in lan_ips() + host_names()]


def allowed_networks(spec: str | None = None) -> list:
    """GLASS_ALLOW: comma-separated networks that may connect (default: private office ranges). "*" = everyone.
    This PC's own addresses are always allowed."""
    spec = spec if spec is not None else os.environ.get("GLASS_ALLOW", DEFAULT_ALLOW)
    if spec.strip() == "*":
        return [ipaddress.ip_network("0.0.0.0/0"), ipaddress.ip_network("::/0")]
    nets = []
    for part in spec.replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                nets.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                pass
    for ip in lan_ips():                                          # this PC itself, whatever its address
        try:
            nets.append(ipaddress.ip_network(ip))
        except ValueError:
            pass
    return nets


def is_allowed(remote: str | None, nets: list) -> bool:
    if not remote:
        return False
    try:
        a = ipaddress.ip_address(remote.split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return any(a.version == n.version and a in n for n in nets)


def port_free(host: str, port: int) -> bool:
    """Nothing listening on the port and it can be bound (a just-closed port in TIME_WAIT counts as free, like the
    web server itself treats it)."""
    c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c.settimeout(0.5)
    try:
        if c.connect_ex(("127.0.0.1", port)) == 0:
            return False                                          # someone answers on it
    except OSError:
        pass
    finally:
        c.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if not sys.platform.startswith("win"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def firewall_rule_ok(port: int) -> bool | None:
    """Windows: is there an inbound allow rule for the port? None = cannot tell (not Windows / no netsh)."""
    if not sys.platform.startswith("win"):
        return None
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE_NAME}"],
                           capture_output=True, text=True, timeout=8,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return None
    out = r.stdout or ""
    if r.returncode != 0 or RULE_NAME not in out or "Allow" not in out:
        return False
    for line in out.splitlines():                                 # LocalPort: 8080-8109  (an old rule may be 5050-5079)
        if line.strip().lower().startswith("localport"):
            spec = line.split(":", 1)[1].strip()
            for part in spec.split(","):
                part = part.strip()
                if part.lower() == "any":
                    return True
                lo, _, hi = part.partition("-")
                if lo.isdigit() and int(lo) <= port <= int(hi or lo):
                    return True
            return False
    return True
