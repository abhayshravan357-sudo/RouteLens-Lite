# PacketLab API Contract

## Overview
The PacketLab provides a controlled virtual Linux router environment for packet transmission and capture verification. It is **distinct** from:
1. The routing decision API (RouteCore - `/lookup`)
2. Physical network routers

The PacketLab API must never present simulated results as equivalent to physical router behavior.

## Base URL
`/api/lab` (proxied through Vite to backend on port 8000)

## Endpoints

### 1. GET /api/lab/status
Check if the virtual router lab is available and ready.

**Response (200):**
```json
{
  "available": true,
  "state": "idle",
  "message": "Packet lab is ready",
  "router_info": {
    "interfaces": ["eth0", "eth1", "eth2"],
    "routing_table": [
      { "destination": "192.168.1.0/24", "next_hop": "10.0.0.1", "interface": "eth0" },
      { "destination": "10.0.0.0/8", "next_hop": null, "interface": "eth2" }
    ]
  }
}
```

**Response (503):**
```json
{
  "available": false,
  "state": "unavailable",
  "message": "Virtual router not running",
  "error": "Container not started"
}
```

### 2. POST /api/lab/simulate
Simulate a packet transmission through the virtual router.

**Request:**
```json
{
  "source_ip": "192.168.1.100",
  "destination_ip": "192.168.1.50",
  "protocol": "icmp",
  "ttl": 64,
  "length": 84,
  "route_matched": "192.168.1.0/25",
  "egress_interface": "eth1",
  "next_hop": "10.0.0.2"
}
```

**Response (200):**
```json
{
  "state": "completed",
  "message": "Packet transmitted and captured",
  "packet": {
    "source_ip": "192.168.1.100",
    "destination_ip": "192.168.1.50",
    "protocol": "icmp",
    "ttl": 63,
    "length": 84,
    "forwarding_info": {
      "ingress_interface": "eth0",
      "egress_interface": "eth1",
      "next_hop": "10.0.0.2",
      "route_matched": "192.168.1.0/25",
      "action": "forward"
    }
  },
  "capture_verified": true,
  "verification_details": {
    "ttl_decremented": true,
    "checksum_valid": true,
    "route_matched": true
  }
}
```

**Response (503):**
```json
{
  "state": "unavailable",
  "message": "Lab unavailable",
  "error": "Virtual router not responding"
}
```

**Response (408):**
```json
{
  "state": "timeout",
  "message": "Capture timeout",
  "error": "No response within 5s"
}
```

## State Machine
The lab progresses through these states:
`idle` → `ready` → `simulating` → `transmitting` → `capturing` → `verifying` → `completed`

Error states: `error`, `timeout`, `unavailable`

## Implementation Requirements

### Virtual Router Setup
- Use Linux network namespaces or containers (e.g., `ip netns`, Docker)
- Configure interfaces and routing table matching RouteCore's `SAMPLE_ROUTES`
- Run in isolated environment - no host network modification

### Packet Transmission
- Generate actual packets (e.g., using `scapy`, `ping`, `hping3`)
- Send through virtual router's ingress interface
- Capture on egress interface or next hop

### Capture Verification
- Verify TTL decremented by 1
- Verify checksum valid
- Verify packet followed expected route (ingress/egress interfaces, next hop)
- Return `capture_verified: true/false` with details

## Error Handling
- All errors must be honest - never fake success
- Distinguish between: lab unavailable, timeout, verification failed
- Return appropriate HTTP status codes

## Integration with Frontend
The frontend (JourneyUI) will:
1. Call `/api/lab/status` to check availability
2. On user action, call `/api/lab/simulate` with packet details from route lookup
3. Display state progression and verification results
4. Never claim physical router equivalence

## Testing Requirements
- Unit tests for each endpoint
- Integration test: route lookup → lab simulation → verification
- Test error cases: lab down, timeout, capture mismatch