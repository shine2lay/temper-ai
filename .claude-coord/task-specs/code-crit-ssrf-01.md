# Task: Fix SSRF DNS rebinding vulnerability in WebScraper

## Summary

Create SSRFProtectionTransport(httpx.HTTPTransport) that validates resolved IPs before request. The current implementation only validates URLs before DNS resolution, allowing attackers to bypass protection via DNS rebinding attacks where the DNS server returns a safe IP during pre-check but a malicious IP (internal network, cloud metadata) during actual connection.

**Estimated Effort:** 4.0 hours
**Module:** tools

---

## Files to Create

_None_

---

## Files to Modify

- `src/tools/web_scraper.py` - Implement IP validation after connection establishment using httpx transport hooks

---

## Acceptance Criteria

### Core Functionality
- [ ] Validate resolved IPs AFTER connection using httpx transport hooks
- [ ] Block private IPs, localhost, cloud metadata endpoints
- [ ] Add dual-validation (pre-check + post-connection)

### Security Controls
- [ ] Cannot bypass via DNS rebinding
- [ ] All SSRF test vectors blocked
- [ ] Cloud metadata endpoints unreachable (169.254.169.254, fd00:ec2::254)

### Testing
- [ ] Unit tests for DNS rebinding scenarios
- [ ] Integration tests with mock DNS server
- [ ] Penetration test with time-delayed DNS responses
- [ ] Test with all blocked network ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)

---

## Implementation Details

```python
import httpx
import ipaddress
from typing import Tuple

class SSRFProtectionTransport(httpx.HTTPTransport):
    """Custom transport that validates resolved IPs before connection"""

    BLOCKED_NETWORKS = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),  # Cloud metadata
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fd00::/8"),
    ]

    def handle_request(self, request):
        # Get the peername (actual IP after DNS resolution)
        response = super().handle_request(request)
        sock = getattr(response, '_transport', None)
        if sock:
            ip_str = sock.peername()[0]
            ip = ipaddress.ip_address(ip_str)

            # Check against blocked networks
            for network in self.BLOCKED_NETWORKS:
                if ip in network:
                    raise SecurityError(f"SSRF: Resolved IP {ip} is in blocked network {network}")

        return response

# Usage in WebScraper
client = httpx.Client(transport=SSRFProtectionTransport())
```

**Integration Point:** Modify WebScraper.__init__() to use SSRFProtectionTransport instead of default httpx transport.

---

## Test Strategy

1. **DNS Rebinding Test:**
   - Create mock DNS server that returns 1.1.1.1 on first lookup, 127.0.0.1 on second
   - Verify WebScraper blocks the request after resolution

2. **Cloud Metadata Test:**
   - Attempt to access http://169.254.169.254/latest/meta-data/
   - Verify request is blocked

3. **Private Network Test:**
   - Test all RFC1918 ranges (10.x, 172.16-31.x, 192.168.x)
   - Verify all are blocked

4. **Performance Test:**
   - Measure overhead of IP validation (<5ms acceptable)

---

## Success Metrics

- [ ] All SSRF bypass attempts fail
- [ ] No internal network access via DNS tricks
- [ ] Security tests pass
- [ ] Performance overhead <5ms per request

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** WebScraper, validate_url_safety

---

## Design References

- `.claude-coord/reports/code-review-20260128-224245.md#1-ssrf-vulnerability`

---

## Notes

**Critical security issue** - SSRF can expose AWS credentials and internal services. This vulnerability allows attackers to:
- Access AWS metadata service (steal IAM credentials)
- Scan internal networks
- Access internal APIs and databases
- Bypass firewall protections

**Remediation Priority:** Must fix before any deployment.
