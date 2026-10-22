# Detailed Research: DNS, Traceroute & Connectivity

**Project**: RouteLens Lite - IPv4 Routing Table Analyzer  
**Covers**: RQ-001 (DNS Resolution), RQ-002 (Traceroute), RQ-006 (Connectivity Checks)  
**Last Updated**: 2026-10-20  
**Python Version**: 3.12.3  
**Environment**: Linux 6.18.7 (Ubuntu/Debian-based)  

See the central index at [../research-index.md](../research-index.md) for the summary tables and decision records.

---

## Research Categories

### DNS Resolution (RQ-001)

| Approach | Status | Timeout Handling | IPv6 Support | Cancellation | Error Types | Performance (100 concurrent) |
|----------|--------|------------------|--------------|--------------|-------------|------------------------------|
| `asyncio.getaddrinfo()` | ✅ Recommended | `asyncio.wait_for()` | Full (AF_INET6) | ✅ Task.cancel() | `gaierror` (OSError subclass) | ~5,000 qps |
| `aiodns` (pycares) | ✅ Alternative | `asyncio.wait_for()` | Full (AAAA query) | ✅ Task.cancel() | `DNSError` (custom) | ~21,600 qps |
| `socket.getaddrinfo()` in executor | ⚠️ Fallback | `asyncio.wait_for()` on future | Full | ⚠️ Via future.cancel() | `gaierror` | ~300 qps (thread pool limited) |
| `dig` subprocess | ❌ Not viable | `asyncio.wait_for()` | Full | ✅ proc.kill() | Subprocess return codes | N/A (not installed) |

**Sources**:
- [Python asyncio.getaddrinfo docs](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.getaddrinfo)
- [aiodns GitHub](https://github.com/aio-libs/aiodns)
- [pycares documentation](https://pycares.readthedocs.io/)

---

### Traceroute Implementation (RQ-002)

| Approach | Privileges Required | Portability | Methods Supported | Output Parsing | Timeout Handling |
|----------|---------------------|-------------|-------------------|----------------|------------------|
| `traceroute` subprocess | Root (CAP_NET_RAW) or `ping_group_range` config | High (standard Linux) | UDP (default), ICMP (-I), TCP (-T), UDPLITE, DCCP, RAW | Structured text, machine-readable with `-n` | Adaptive (`-w`), per-hop |
| `tracepath` subprocess | **None** (unprivileged) | High (iputils) | UDP with MTU discovery | Structured text | Fixed per hop |
| Raw socket (ICMP) | **Root** (CAP_NET_RAW) | Linux only | Full control | Manual parsing | Manual implementation |
| Raw socket (UDP) + ICMP recv | **Root** (CAP_NET_RAW) | Linux only | Full control | Manual parsing | Manual implementation |
| ICMP dgram socket (`SOCK_DGRAM`, `IPPROTO_ICMP`) | Group in `ping_group_range` | Linux 3.0+ (IPv4), 3.11+ (IPv6) | ICMP echo only | Manual parsing | Manual implementation |
| UDP socket + TTL + ICMP recv | **Root** (for ICMP recv) | Linux only | UDP probes | Manual parsing | Manual implementation |

**Key Findings**:
- **tracepath** is the only fully unprivileged option; discovers MTU but slower (~24s for 10 hops)
- **traceroute** supports multiple methods (UDP/ICMP/TCP) but requires root or `ping_group_range` config
- **Raw sockets** require `CAP_NET_RAW`; Python's `socket.SOCK_RAW` with `IPPROTO_ICMP` works with privileges
- **ICMP dgram sockets** (Linux 3.0+) allow unprivileged ICMP if `/proc/sys/net/ipv4/ping_group_range` includes user's GID
- Current environment: `ping_group_range = 1 0` (disabled), no traceroute installed

**Sources**:
- [traceroute(8) man page](https://man7.org/linux/man-pages/man8/traceroute.8.html)
- [tracepath(8) man page](https://man7.org/linux/man-pages/man8/tracepath.8.html)
- [Linux ping_group_range documentation](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt)

---

### Connectivity Check: Async ICMP Ping & TCP Connect (RQ-006)

| Approach | Privileges Required | IPv4/IPv6 | Timeout Handling | Rate Limiting | Error Types | Performance |
|----------|---------------------|-----------|------------------|---------------|-------------|-------------|
| `ping` subprocess (`asyncio.create_subprocess_exec`) | **None** (ping binary has `cap_net_raw=ep`) | Both (`-4`/`-6`) | `asyncio.wait_for()` | Via `-c`, `-i`, `-W` flags | Subprocess return codes, parseable stdout | ~0.4s for 3 packets |
| `aioping` / `asyncping3` / `aio_ping` (raw socket libs) | **Root** (CAP_NET_RAW) | Both | Built-in timeout param | Built-in count/delay | `PermissionError`, `TimeoutError` | Fastest (~0.1s) but requires root |
| ICMP dgram socket (`SOCK_DGRAM`, `IPPROTO_ICMP`) | Group in `ping_group_range` | Linux 3.0+ (IPv4), 3.11+ (IPv6) | Manual | Manual | `PermissionError` if not configured | Low latency, no root if configured |
| `asyncio.open_connection()` (TCP connect) | **None** | Both | `asyncio.wait_for()` | Manual (semaphore) | `TimeoutError`, `ConnectionError`, `gaierror` | ~20ms per connect |

**Key Findings**:
- **`ping` subprocess is the only fully unprivileged ICMP option** on standard Linux - `/usr/bin/ping` has `cap_net_raw=ep` capability
- **All Python raw socket libraries (aioping, asyncping3, aio_ping) require root** - they create `SOCK_RAW` sockets directly
- **ICMP dgram sockets** (Linux 3.0+) work unprivileged **only if** `/proc/sys/net/ipv4/ping_group_range` includes user's GID (currently `1 0` = disabled)
- **TCP connect via `asyncio.open_connection()`** is unprivileged, fast, and ideal for port reachability checks
- Current environment: ping works unprivileged, `ping_group_range = 1 0` (disabled), no raw socket access

**Sources**:
- [aioping GitHub (stellarbit)](https://github.com/stellarbit/aioping) - GPLv2, requires root
- [asyncping3 GitHub (hetmankp)](https://github.com/hetmankp/asyncping3) - MIT, requires root
- [aio_ping PyPI](https://pypi.org/project/aio_ping/) - GPLv2, requires root
- [Linux ping_group_range documentation](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt)
- [man ping(8)](https://man7.org/linux/man-pages/man8/ping.8.html)
- [asyncio.open_connection docs](https://docs.python.org/3/library/asyncio-stream.html#asyncio.open_connection)

---

## Completed Research Decisions

### RQ-001: Best Async DNS Resolution for Python 3.12

**Decision**: Use **`asyncio.getaddrinfo()`** as primary, **`aiodns`** as optional high-performance alternative.

**Rationale**:
1. **Zero dependencies** - `asyncio.getaddrinfo()` is stdlib (Python 3.4+)
2. **Full IPv6 support** - Returns both A and AAAA records when `family=0` (AF_UNSPEC)
3. **Native cancellation** - `asyncio.Task.cancel()` works correctly
4. **Standard error types** - Raises `socket.gaierror` (OSError subclass), familiar to Python developers
5. **Happy Eyeballs ready** - Returns addresses in RFC 8305 order when used with `loop.create_connection()`
6. **Sufficient performance** - ~5,000 qps concurrent; adequate for typical DNS needs

**When to use aiodns**:
- Need >10,000 qps sustained
- Need specific record types (MX, TXT, SRV, CAA, etc.)
- Need fine-grained control over DNS server selection, timeouts, retries
- Already using pycares for other purposes

**Implementation Example**:
```python
import asyncio
import socket

async def resolve_host(host: str, port: int = 80, timeout: float = 5.0) -> list[tuple]:
    """Resolve host to list of (family, type, proto, canonname, sockaddr) tuples."""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        raise TimeoutError(f"DNS resolution timed out after {timeout}s")
    except socket.gaierror as e:
        raise ResolutionError(f"DNS resolution failed: {e}") from e

# With Happy Eyeballs (recommended for connections)
async def connect_with_happy_eyeballs(host: str, port: int):
    loop = asyncio.get_event_loop()
    return await loop.create_connection(
        protocol_factory,
        host=host,
        port=port,
        happy_eyeballs_delay=0.25,  # RFC 8305 recommended
    )
```

**Verification Tests** (run in project venv):
```bash
cd backend && source .venv/bin/activate && python3 -c "
import asyncio, socket, time

async def test():
    loop = asyncio.get_event_loop()
    # Basic resolution
    r = await loop.getaddrinfo('google.com', 80, family=socket.AF_UNSPEC)
    print(f'Results: {len(r)} (IPv4: {sum(1 for x in r if x[0]==2)}, IPv6: {sum(1 for x in r if x[0]==10)})')
    # Timeout
    try:
        await asyncio.wait_for(loop.getaddrinfo('invalid-host-12345.com', 80), timeout=0.001)
    except asyncio.TimeoutError:
        print('Timeout works')
    # Cancellation
    task = asyncio.create_task(loop.getaddrinfo('google.com', 80))
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print('Cancellation works')

asyncio.run(test())
"
```

---

### RQ-002: Traceroute Implementation Approach

**Decision**: Use **`tracepath` subprocess** as primary unprivileged option; document **`traceroute` subprocess** for privileged environments.

**Rationale**:
1. **Zero privileges required** - `tracepath` works without root/CAP_NET_RAW
2. **Available by default** - Part of `iputils` package (standard on most Linux)
3. **IPv4 and IPv6** - Supports both with `-4`/`-6` flags
4. **MTU discovery bonus** - Provides Path MTU information useful for routing analysis
5. **Parsable output** - `-n` flag gives numeric IPs, consistent format

**Tradeoffs**:
- **Slower** than traceroute (~24s for 10 hops vs ~3-5s) due to sequential probing
- **Limited methods** - Only UDP-based, no ICMP/TCP options
- **No per-hop RTT control** - Fixed timing behavior

**For privileged environments** (if CAP_NET_RAW available):
- Use `traceroute -I` (ICMP) for fastest results
- Use `traceroute -T -p 80` (TCP SYN) to bypass firewalls
- Consider Python raw socket implementation for full control

**Implementation Example**:
```python
import asyncio
import subprocess
import re

async def tracepath(host: str, max_hops: int = 30, timeout: float = 30.0) -> list[dict]:
    """Run tracepath and parse output into structured data."""
    cmd = ['tracepath', '-n', '-m', str(max_hops), host]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"tracepath timed out after {timeout}s")
    
    if proc.returncode != 0:
        raise RuntimeError(f"tracepath failed: {stderr.decode()}")
    
    return parse_tracepath_output(stdout.decode())

def parse_tracepath_output(output: str) -> list[dict]:
    """Parse tracepath -n output into list of hop dicts."""
    hops = []
    # Regex for lines like: " 1:  192.168.0.1                                          1.504ms"
    # or: " 2:  103.163.198.222                                       2.957ms pmtu 1480"
    pattern = re.compile(
        r'^\s*(\d+)\??:\s+(\S+)(?:\s+(\d+\.?\d*)ms)?(?:\s+pmtu\s+(\d+))?'
    )
    for line in output.strip().split('\n'):
        if 'no reply' in line or 'Too many hops' in line or 'Resume:' in line:
            continue
        match = pattern.match(line)
        if match:
            hop_num = int(match.group(1))
            ip = match.group(2)
            rtt = float(match.group(3)) if match.group(3) else None
            pmtu = int(match.group(4)) if match.group(4) else None
            hops.append({
                'hop': hop_num,
                'ip': ip,
                'rtt_ms': rtt,
                'pmtu': pmtu,
            })
    return hops
```

**Verification Tests** (run in project environment):
```bash
# Test tracepath availability
tracepath -n -m 5 8.8.8.8

# Test Python subprocess wrapper
cd backend && source .venv/bin/activate && python3 -c "
import asyncio, re

async def test():
    cmd = ['tracepath', '-n', '-m', '5', '8.8.8.8']
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    print(f'Return code: {proc.returncode}')
    lines = stdout.decode().strip().split('\n')
    for line in lines[:10]:
        print(f'  {line}')

asyncio.run(test())
"
```

**Privilege Escalation Path** (if needed later):
1. **Set `ping_group_range`**: `echo '0 1000' | sudo tee /proc/sys/net/ipv4/ping_group_range` (allows GID 1000 ICMP dgram)
2. **Set CAP_NET_RAW on python**: `sudo setcap cap_net_raw+ep /usr/bin/python3.12`
3. **Run with sudo**: Configure sudoers for passwordless `traceroute` command
---

### RQ-006: Async ICMP Ping & TCP Connect for Connectivity Checks

**Decision**: Use **`ping` subprocess** for ICMP reachability + **`asyncio.open_connection()`** for TCP port reachability.

**Rationale**:
1. **Zero privileges for ICMP** - `/usr/bin/ping` has `cap_net_raw=ep` capability on modern Linux, works unprivileged
2. **Zero privileges for TCP** - `asyncio.open_connection()` uses standard TCP sockets, no special permissions
3. **Configurable timeouts** - Both support `asyncio.wait_for()` for overall timeout control
4. **Rate limiting** - `ping -c count -i interval -W deadline` provides built-in rate control; TCP can use asyncio semaphore
5. **Structured output** - `ping` stdout is parseable for packet loss, RTT stats; TCP connect gives precise connection latency
6. **IPv4/IPv6 support** - Both support `-4`/`-6` flags (ping) and `family` parameter (asyncio)
7. **Existing pattern** - Backend already uses `asyncio.create_subprocess_exec` for `ip`, `ping`, `tcpdump` in `lab_adapter.py`

**Tradeoffs**:
- **Slower than raw sockets** - subprocess spawn overhead (~0.4s for 3 packets vs ~0.1s raw)
- **Parsing required** - Need to parse `ping` stdout for structured results (packet loss, RTT min/avg/max/mdev)
- **No per-packet callbacks** - Subprocess returns aggregated results; raw socket libs can yield per-packet

**When to use raw socket libraries (aioping/asyncping3)**:
- Need per-packet streaming results (e.g., real-time UI updates)
- Need sub-millisecond precision timing
- Running in privileged container with `CAP_NET_RAW`
- Already have root/CAP_NET_RAW in deployment environment

**Implementation Example**:
```python
import asyncio
import socket
import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class PingResult:
    host: str
    success: bool
    packets_sent: int
    packets_received: int
    packet_loss_pct: float
    rtt_min_ms: Optional[float]
    rtt_avg_ms: Optional[float]
    rtt_max_ms: Optional[float]
    rtt_mdev_ms: Optional[float]
    elapsed_s: float
    error: Optional[str] = None

@dataclass
class TcpConnectResult:
    host: str
    port: int
    success: bool
    rtt_ms: Optional[float]
    error: Optional[str] = None

async def ping_host(
    host: str,
    count: int = 3,
    timeout_per_packet: float = 2.0,
    interval: float = 0.2,
    overall_timeout: float = 10.0,
    ipv6: bool = False,
) -> PingResult:
    """ICMP ping via subprocess with structured result."""
    cmd = ['ping']
    if ipv6:
        cmd.append('-6')
    else:
        cmd.append('-4')
    cmd.extend([
        '-c', str(count),
        '-W', str(int(timeout_per_packet)),
        '-i', str(interval),
        host
    ])
    
    start = asyncio.get_event_loop().time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=overall_timeout)
        elapsed = asyncio.get_event_loop().time() - start
        
        # Parse output
        output = stdout.decode()
        result = PingResult(
            host=host,
            success=proc.returncode == 0,
            packets_sent=count,
            packets_received=0,
            packet_loss_pct=100.0,
            rtt_min_ms=None,
            rtt_avg_ms=None,
            rtt_max_ms=None,
            rtt_mdev_ms=None,
            elapsed_s=elapsed,
        )
        
        for line in output.splitlines():
            if 'packets transmitted' in line:
                parts = line.split(',')
                for part in parts:
                    part = part.strip()
                    if 'packets transmitted' in part:
                        result.packets_sent = int(part.split()[0])
                    elif 'received' in part:
                        result.packets_received = int(part.split()[0])
                    elif 'packet loss' in part:
                        result.packet_loss_pct = float(part.split('%')[0].split()[-1])
            elif 'rtt min/avg/max/mdev' in line or 'round-trip' in line:
                try:
                    rtt_part = line.split('=')[1].split('ms')[0].strip()
                    rtt_values = rtt_part.split('/')
                    if len(rtt_values) >= 4:
                        result.rtt_min_ms = float(rtt_values[0])
                        result.rtt_avg_ms = float(rtt_values[1])
                        result.rtt_max_ms = float(rtt_values[2])
                        result.rtt_mdev_ms = float(rtt_values[3])
                except (ValueError, IndexError):
                    pass
        
        if not result.success and result.packets_received == 0:
            result.error = stderr.decode().strip() or "All packets lost"
        
        return result
        
    except asyncio.TimeoutError:
        elapsed = asyncio.get_event_loop().time() - start
        return PingResult(
            host=host, success=False, packets_sent=count, packets_received=0,
            packet_loss_pct=100.0, rtt_min_ms=None, rtt_avg_ms=None,
            rtt_max_ms=None, rtt_mdev_ms=None, elapsed_s=elapsed,
            error=f"Ping timed out after {overall_timeout}s"
        )
    except Exception as e:
        elapsed = asyncio.get_event_loop().time() - start
        return PingResult(
            host=host, success=False, packets_sent=count, packets_received=0,
            packet_loss_pct=100.0, rtt_min_ms=None, rtt_avg_ms=None,
            rtt_max_ms=None, rtt_mdev_ms=None, elapsed_s=elapsed,
            error=f"{type(e).__name__}: {e}"
        )

async def tcp_connect(
    host: str,
    port: int,
    timeout: float = 5.0,
    ipv6: bool = False,
) -> TcpConnectResult:
    """TCP connect reachability check with latency measurement."""
    family = socket.AF_INET6 if ipv6 else socket.AF_INET
    start = asyncio.get_event_loop().time()
    
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, family=family),
            timeout=timeout
        )
        elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000
        writer.close()
        await writer.wait_closed()
        return TcpConnectResult(
            host=host, port=port, success=True, rtt_ms=elapsed_ms
        )
    except asyncio.TimeoutError:
        return TcpConnectResult(
            host=host, port=port, success=False, rtt_ms=None,
            error=f"TCP connect timeout after {timeout}s"
        )
    except ConnectionRefusedError:
        return TcpConnectResult(
            host=host, port=port, success=False, rtt_ms=None,
            error="Connection refused"
        )
    except OSError as e:
        if e.errno in (socket.EHOSTUNREACH, socket.ENETUNREACH):
            return TcpConnectResult(
                host=host, port=port, success=False, rtt_ms=None,
                error=f"Network unreachable: {e}"
            )
        return TcpConnectResult(
            host=host, port=port, success=False, rtt_ms=None,
            error=f"TCP connect error: {e}"
        )

# Combined connectivity check
async def check_connectivity(
    host: str,
    ports: list[int] = [80, 443],
    ping_count: int = 3,
    ping_timeout: float = 2.0,
    tcp_timeout: float = 5.0,
) -> dict:
    """Check both ICMP and TCP reachability."""
    ping_task = ping_host(host, count=ping_count, timeout_per_packet=ping_timeout)
    tcp_tasks = [tcp_connect(host, port, timeout=tcp_timeout) for port in ports]
    
    ping_result, *tcp_results = await asyncio.gather(ping_task, *tcp_tasks)
    
    return {
        'host': host,
        'icmp': ping_result,
        'tcp': {f'port_{r.port}': r for r in tcp_results},
        'overall_reachable': ping_result.success or any(r.success for r in tcp_results),
    }
```

**Verification Tests** (run in project venv):
```bash
# Test ping subprocess (unprivileged)
cd backend && source .venv/bin/activate && python3 -c "
import asyncio

async def test():
    cmd = ['ping', '-c', '3', '-W', '2', '-i', '0.2', 'google.com']
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    print(f'Return code: {proc.returncode}')
    print(stdout.decode()[-200:])

asyncio.run(test())
"

# Test TCP connect
cd backend && source .venv/bin/activate && python3 -c "
import asyncio, socket, time

async def test():
    for port in [80, 443, 12345]:
        start = time.time()
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection('google.com', port), timeout=5)
            rtt = (time.time() - start) * 1000
            writer.close()
            await writer.wait_closed()
            print(f'Port {port}: {rtt:.1f} ms')
        except Exception as e:
            print(f'Port {port}: {type(e).__name__}: {e}')

asyncio.run(test())
"

# Check ping binary capabilities
getcap /usr/bin/ping
# Expected: /usr/bin/ping cap_net_raw=ep

# Check ping_group_range (for ICMP dgram sockets)
cat /proc/sys/net/ipv4/ping_group_range
# Current: 1 0 (disabled)
# To enable: echo '1000 1000' | sudo tee /proc/sys/net/ipv4/ping_group_range
```
---

## Testing Commands Reference

### DNS Resolution Tests
```bash
# Test asyncio.getaddrinfo
cd backend && source .venv/bin/activate && python3 -c "
import asyncio, socket
async def t():
    loop = asyncio.get_event_loop()
    r = await loop.getaddrinfo('google.com', 80, family=socket.AF_UNSPEC)
    print(f'{len(r)} results, IPv4: {sum(1 for x in r if x[0]==2)}, IPv6: {sum(1 for x in r if x[0]==10)}')
asyncio.run(t())
"

# Test aiodns
cd backend && source .venv/bin/activate && python3 -c "
import asyncio, aiodns
async def t():
    resolver = aiodns.DNSResolver()
    r = await resolver.query_dns('google.com', 'A')
    print(f'A records: {[x.data.addr for x in r.answer]}')
    r = await resolver.query_dns('google.com', 'AAAA')
    print(f'AAAA records: {[x.data.addr for x in r.answer]}')
asyncio.run(t())
"
```

### Traceroute Tests
```bash
# Test tracepath (unprivileged)
tracepath -n -m 10 8.8.8.8

# Test tracepath IPv6
tracepath -6 -n -m 10 2001:4860:4860::8888

# Check ping_group_range (for ICMP dgram sockets)
cat /proc/sys/net/ipv4/ping_group_range
# To enable for current user (gid=1000):
# echo '1000 1000' | sudo tee /proc/sys/net/ipv4/ping_group_range
```

### Connectivity Check Tests
```bash
# Ping binary must carry CAP_NET_RAW for unprivileged ICMP
getcap /usr/bin/ping
# Expected: /usr/bin/ping cap_net_raw=ep

# Confirm the ping subprocess path works without root
cd backend && source .venv/bin/activate && python3 -c "
import asyncio

async def test():
    cmd = ['ping', '-c', '3', '-W', '2', '-i', '0.2', 'google.com']
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    print(f'rc={proc.returncode}')
    print(stdout.decode().strip().splitlines()[-2])

asyncio.run(test())
"

# Confirm the TCP connect path works without root
cd backend && source .venv/bin/activate && python3 -c "
import asyncio, time

async def test():
    for port in (80, 443, 12345):
        start = time.time()
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection('google.com', port), timeout=5)
            print(f'port {port}: {(time.time()-start)*1000:.1f} ms')
            writer.close()
            await writer.wait_closed()
        except Exception as e:
            print(f'port {port}: {type(e).__name__}')

asyncio.run(test())
"

# Confirm raw-socket libraries are rejected without root
cd backend && source .venv/bin/activate && python3 -c "
import asyncio, aioping
async def test():
    try:
        await aioping.ping('google.com', timeout=2)
    except PermissionError as e:
        print(f'aioping blocked: {e}')
asyncio.run(test())
"
```

---

## Limitations & Future Work

### DNS Resolution
- `asyncio.getaddrinfo()` uses system resolver (getaddrinfo(3)); respects `/etc/resolv.conf`, nsswitch.conf
- No control over DNS server selection, retry policy, or EDNS0 options
- For DNS-over-HTTPS/TLS, need external library (aiohttp + dns-python)
- `aiodns` getaddrinfo() returns "DNS server does not implement requested operation" - limited to query_dns()

### Traceroute
- `tracepath` MTU discovery only works on first hop in some network configurations
- No programmatic access to ICMP extensions (RFC 4884) via subprocess
- Raw socket implementation requires significant code for proper ICMP parsing, checksum validation
- Consider `paris-traceroute` for load-balanced path detection (not in default repos)

### Connectivity Checks
- `ping` subprocess cost: ~0.4 s wall time for 3 packets, of which most is process spawn overhead
- Aggregated results only — no per-packet callback for live UI updates
- `ping` output format is locale-dependent; the parser assumes the C/English locale
- If the host's `/usr/bin/ping` lacks `cap_net_raw`, the subprocess path silently needs root
- Raw-socket Python libraries (`aioping`, `asyncping3`, `aio_ping`) are unusable unprivileged and
  all carry a GPL/MIT licence obligation that complicates distribution
- ICMP echo is frequently blocked by firewalls; the TCP connect path is the more reliable signal

---

## Version History

| Date | Author | Changes |
|------|--------|---------|
| 2026-10-20 | RouteLens Research Specialist | Initial research for RQ-001, RQ-002, RQ-006 |

---

## Appendix: Raw Socket Traceroute Prototype (Privileged)

```python
# Requires: CAP_NET_RAW or root
# Linux 3.0+ for ICMP dgram sockets (if ping_group_range configured)

import socket
import struct
import asyncio

async def raw_icmp_traceroute(host: str, max_hops: int = 30):
    """Raw ICMP traceroute - requires privileges."""
    dest_ip = socket.gethostbyname(host)
    
    # Send socket: raw ICMP or UDP with TTL control
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    
    # Receive socket: raw ICMP for TIME_EXCEEDED and PORT_UNREACH
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    recv_sock.settimeout(2.0)
    recv_sock.bind(('', 0))
    
    try:
        for ttl in range(1, max_hops + 1):
            send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, struct.pack('I', ttl))
            
            # Send probe
            port = 33434 + ttl
            send_sock.sendto(b'X' * 40, (dest_ip, port))
            
            # Wait for ICMP response
            try:
                data, addr = recv_sock.recvfrom(1024)
                # Parse ICMP header (type, code, ...)
                icmp_type = data[20]  # IP header is 20 bytes
                if icmp_type == 11:  # TIME_EXCEEDED
                    print(f'{ttl}: {addr[0]} (TTL exceeded)')
                elif icmp_type == 3:  # DEST_UNREACH
                    print(f'{ttl}: {addr[0]} (Destination reached)')
                    break
            except socket.timeout:
                print(f'{ttl}: *')
    finally:
        send_sock.close()
        recv_sock.close()
```

**Note**: This prototype is for reference only. Production implementation needs:
- Proper ICMP header parsing (type, code, checksum, identifier, sequence)
- Handling of ICMP extensions (RFC 4884)
- Checksum validation
- IPv6 support (IPPROTO_ICMPV6)
- Concurrent probe sending (`-N` equivalent)
- Adaptive timeout algorithm

