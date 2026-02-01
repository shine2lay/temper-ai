# Rate Limit Bypass Attack Scenarios - Visual Guide

## Scenario 1: Multi-Instance Bypass Attack

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ATTACKER INFRASTRUCTURE                       │
└─────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
    │ Instance 1   │   │ Instance 2   │   │ Instance 10  │
    │              │   │              │   │      ...     │
    │ Rate Limit:  │   │ Rate Limit:  │   │ Rate Limit:  │
    │ 50 calls/hr  │   │ 50 calls/hr  │   │ 50 calls/hr  │
    │              │   │              │   │              │
    │ [IN-MEMORY]  │   │ [IN-MEMORY]  │   │ [IN-MEMORY]  │
    │  ┌────────┐  │   │  ┌────────┐  │   │  ┌────────┐  │
    │  │ Bucket │  │   │  │ Bucket │  │   │  │ Bucket │  │
    │  │ 50/50  │  │   │  │ 50/50  │  │   │  │ 50/50  │  │
    │  └────────┘  │   │  └────────┘  │   │  └────────┘  │
    └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
           │                  │                  │
           │ 50 LLM calls     │ 50 LLM calls     │ 50 LLM calls
           │                  │                  │
           └──────────────────┼──────────────────┘
                              ▼
                    ┌──────────────────┐
                    │   LLM Provider   │
                    │                  │
                    │  ⚠️  RECEIVES:    │
                    │  500 calls/hour  │
                    │                  │
                    │  ✓ Expected:     │
                    │  50 calls/hour   │
                    └──────────────────┘

ATTACK RESULT: 10x rate limit bypass (500 vs 50 calls)
COST IMPACT: $1,500 instead of $150/month
ROOT CAUSE: No shared distributed state
```

---

## Scenario 2: Agent ID Case Sensitivity Bypass

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SINGLE INSTANCE - AGENT ID BYPASS                │
└─────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────┐
   │          RateLimiterPolicy (In-Memory)          │
   │                                                 │
   │  _operation_history = {                         │
   │    ("llm_call", "attacker"):  [t1, t2] ⚠️ FULL │
   │    ("llm_call", "Attacker"):  []       ✓ EMPTY │
   │    ("llm_call", "ATTACKER"):  []       ✓ EMPTY │
   │    ("llm_call", "aTtAcKeR"):  []       ✓ EMPTY │
   │  }                                              │
   └─────────────────────────────────────────────────┘
                        ▲
                        │
         ┌──────────────┼──────────────┐
         │              │              │
    Request 1      Request 2      Request 3
    agent_id:      agent_id:      agent_id:
    "attacker"     "Attacker"     "ATTACKER"
         │              │              │
         ▼              ▼              ▼
    ✓ Allowed      ✓ Allowed      ✓ Allowed
    (tokens: 1)    (tokens: 2)    (tokens: 2)

ATTACK RESULT: 6 calls instead of 2 (3x bypass)
ROOT CAUSE: No ID normalization to lowercase
FIX: entity_id = context.get("agent_id").lower()
```

---

## Scenario 3: Unicode Homoglyph Bypass

```
┌─────────────────────────────────────────────────────────────────────┐
│              UNICODE HOMOGLYPH BYPASS ATTACK                        │
└─────────────────────────────────────────────────────────────────────┘

Visual appearance:  admin   аdmin   admin
Actual Unicode:     Latin   Cyrillic  Latin+ZWS

┌────────────────────────────────────────────────────────┐
│           Token Bucket Manager (In-Memory)             │
│                                                        │
│  buckets = {                                           │
│    ("admin", "llm_call"):      TokenBucket(0/2) FULL  │
│    ("аdmin", "llm_call"):      TokenBucket(2/2) EMPTY │
│    ("admin\u200B", "llm_call"): TokenBucket(2/2) EMPTY │
│    ("ａｄｍｉｎ", "llm_call"):  TokenBucket(2/2) EMPTY │
│  }                                                     │
└────────────────────────────────────────────────────────┘
          ▲              ▲               ▲
          │              │               │
    Latin 'a'      Cyrillic 'а'    Zero-width space
    (U+0061)       (U+0430)        (U+200B)

LOOKS IDENTICAL TO HUMAN BUT DIFFERENT TO COMPUTER!

┌─────────────────────────────────────────────────────────┐
│ Attack Vector:                                          │
│                                                         │
│ agent_ids = [                                           │
│   "admin",           # ASCII - BLOCKED                  │
│   "аdmin",           # Cyrillic 'а' - ALLOWED ⚠️       │
│   "admin\u200B",     # Zero-width space - ALLOWED ⚠️   │
│   "ａｄｍｉｎ",      # Full-width - ALLOWED ⚠️          │
│ ]                                                       │
│                                                         │
│ Total: 8 calls instead of 2 (4x bypass)                │
└─────────────────────────────────────────────────────────┘

ROOT CAUSE: No Unicode normalization (NFC) or homoglyph detection
FIX: Apply unicodedata.normalize('NFC', entity_id.lower())
```

---

## Scenario 4: Clock Manipulation Attack

```
┌─────────────────────────────────────────────────────────────────────┐
│                 CLOCK MANIPULATION ATTACK                           │
└─────────────────────────────────────────────────────────────────────┘

NORMAL OPERATION:
════════════════════════════════════════════════════════════════════

Time: 00:00        Token Bucket: [▓▓▓▓▓▓▓▓▓▓] 10/10
         ↓ Consume 10 tokens
Time: 00:00        Token Bucket: [          ] 0/10
         ↓ Wait 1 hour for refill
Time: 01:00        Token Bucket: [▓▓▓▓▓▓▓▓▓▓] 10/10


ATTACK WITH CLOCK MANIPULATION:
════════════════════════════════════════════════════════════════════

Time: 00:00        Token Bucket: [▓▓▓▓▓▓▓▓▓▓] 10/10
         ↓ Consume 10 tokens
Time: 00:00        Token Bucket: [          ] 0/10

         ↓ ⚠️ ATTACKER: Set system clock +1 hour
         $ date -s '+1 hour'

Time: 01:00        Token Bucket: [▓▓▓▓▓▓▓▓▓▓] 10/10  ⚠️ INSTANT REFILL!
  (system clock)

         ↓ Consume 10 tokens again
Time: 01:00        Token Bucket: [          ] 0/10

         ↓ ⚠️ Set clock +1 hour again
         $ date -s '+1 hour'

Time: 02:00        Token Bucket: [▓▓▓▓▓▓▓▓▓▓] 10/10  ⚠️ INSTANT REFILL!

RESULT: 30 calls in 1 minute instead of 10 calls/hour

┌────────────────────────────────────────────────────────┐
│ Vulnerable Code:                                       │
│                                                        │
│ def _refill(self):                                     │
│     now = time.time()  # ⚠️ Uses system clock          │
│     elapsed = now - self.last_refill                   │
│     ...                                                │
└────────────────────────────────────────────────────────┘

ROOT CAUSE: Uses time.time() which reflects system clock changes
FIX: Use time.monotonic() which is immune to clock changes

┌────────────────────────────────────────────────────────┐
│ Fixed Code:                                            │
│                                                        │
│ def _refill(self):                                     │
│     now = time.monotonic()  # ✓ Monotonic clock        │
│     elapsed = now - self.last_refill                   │
│     if elapsed < 0:  # ✓ Handle clock going backwards  │
│         return                                         │
│     ...                                                │
└────────────────────────────────────────────────────────┘
```

---

## Scenario 5: Instance Restart Bypass

```
┌─────────────────────────────────────────────────────────────────────┐
│                   INSTANCE RESTART BYPASS ATTACK                    │
└─────────────────────────────────────────────────────────────────────┘

WITHOUT DISTRIBUTED STATE (CURRENT):
════════════════════════════════════════════════════════════════════

┌─────────────────┐
│   Instance A    │
│   [IN-MEMORY]   │
│                 │
│  agent-1: 0/50  │  ← Rate limit exhausted
└────────┬────────┘
         │
         ↓ Restart instance
         ↓
┌─────────────────┐
│   Instance A    │
│   [IN-MEMORY]   │
│                 │
│  agent-1: 50/50 │  ⚠️ RESET! Fresh state
└────────┬────────┘
         │
         ↓ Make another 50 calls
         ↓
   ✓ All allowed!

ATTACK: Restart instance every time rate limit hit
RESULT: Unlimited calls by restarting


WITH DISTRIBUTED STATE (REQUIRED):
════════════════════════════════════════════════════════════════════

┌─────────────────┐              ┌─────────────────┐
│   Instance A    │              │   Redis Store   │
│   [STATELESS]   │◄────────────►│                 │
│                 │              │ agent-1: 0/50   │
└────────┬────────┘              └─────────────────┘
         │
         ↓ Restart instance
         ↓
┌─────────────────┐              ┌─────────────────┐
│   Instance A    │              │   Redis Store   │
│   [STATELESS]   │◄────────────►│                 │
│                 │              │ agent-1: 0/50   │ ← State persists
└────────┬────────┘              └─────────────────┘
         │
         ↓ Try to make calls
         ↓
   ✗ Rate limited!

FIX: Store token bucket state in Redis, not memory
```

---

## Scenario 6: Race Condition Exploit

```
┌─────────────────────────────────────────────────────────────────────┐
│              CONCURRENT CONSUMPTION RACE CONDITION                  │
└─────────────────────────────────────────────────────────────────────┘

THREAD-SAFE (CURRENT - CORRECT):
════════════════════════════════════════════════════════════════════

Token Bucket: [▓] 1 token available

Thread 1                Thread 2                Thread 3
   │                       │                       │
   ├─ Lock acquired        │                       │
   │                       ├─ Waiting...           │
   │                       │                       ├─ Waiting...
   ├─ Check: 1 >= 1 ✓      │                       │
   ├─ Consume: 1           │                       │
   ├─ Tokens: 0            │                       │
   ├─ Lock released        │                       │
   │                       ├─ Lock acquired        │
   │                       ├─ Check: 0 >= 1 ✗      │
   │                       ├─ Return false         │
   │                       ├─ Lock released        │
   │                       │                       ├─ Lock acquired
   │                       │                       ├─ Check: 0 >= 1 ✗
   │                       │                       ├─ Return false
   │                       │                       └─ Lock released

RESULT: Only Thread 1 consumes (correct!)


POTENTIAL RACE WITHOUT LOCK (VULNERABLE):
════════════════════════════════════════════════════════════════════

Token Bucket: [▓] 1 token available

Thread 1                Thread 2                Thread 3
   │                       │                       │
   ├─ Check: 1 >= 1 ✓      ├─ Check: 1 >= 1 ✓      ├─ Check: 1 >= 1 ✓
   │    ⚠️ Race!           │    ⚠️ Race!           │    ⚠️ Race!
   ├─ Consume: 1           ├─ Consume: 1           ├─ Consume: 1
   │                       │                       │
   Tokens: -2 ⚠️ NEGATIVE!

RESULT: 3 threads consume 1 token (BAD!)

CURRENT STATUS: ✓ Protected by threading.Lock
DISTRIBUTED: ⚠️ Need Redis Lua script for atomicity
```

---

## Scenario 7: Distributed Systems - No Coordination

```
┌─────────────────────────────────────────────────────────────────────┐
│         PRODUCTION DEPLOYMENT - NO DISTRIBUTED COORDINATION         │
└─────────────────────────────────────────────────────────────────────┘

CURRENT ARCHITECTURE (VULNERABLE):

┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
│ Instance 1 │  │ Instance 2 │  │ Instance 3 │  │ Instance 4 │
│            │  │            │  │            │  │            │
│ IN-MEMORY: │  │ IN-MEMORY: │  │ IN-MEMORY: │  │ IN-MEMORY: │
│ agent-1:   │  │ agent-1:   │  │ agent-1:   │  │ agent-1:   │
│   50/50    │  │   50/50    │  │   50/50    │  │   50/50    │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      │               │               │               │
      │               │               │               │
      └───────────────┴───────────────┴───────────────┘
                            │
                    ┌───────▼────────┐
                    │  Load Balancer │
                    └───────┬────────┘
                            │
                    ┌───────▼────────┐
                    │   Attacker     │
                    │                │
                    │ Makes 200 calls│
                    │ = 50 per inst  │
                    └────────────────┘

EACH INSTANCE ALLOWS 50 CALLS = 200 TOTAL ⚠️
EXPECTED: 50 TOTAL


REQUIRED ARCHITECTURE (SECURE):

┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
│ Instance 1 │  │ Instance 2 │  │ Instance 3 │  │ Instance 4 │
│            │  │            │  │            │  │            │
│ STATELESS  │  │ STATELESS  │  │ STATELESS  │  │ STATELESS  │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      │               │               │               │
      └───────────────┴───────────────┴───────────────┘
                            │
                    ┌───────▼────────┐
                    │ Redis Cluster  │
                    │                │
                    │ agent-1: 50/50 │  ← SHARED STATE
                    │                │
                    │ Atomic ops via │
                    │ Lua scripts    │
                    └────────────────┘

ALL INSTANCES SHARE ONE BUCKET = 50 TOTAL ✓
```

---

## Attack Success Metrics

```
┌─────────────────────────────────────────────────────────────────────┐
│                    BYPASS EFFECTIVENESS MATRIX                      │
└─────────────────────────────────────────────────────────────────────┘

Attack Type              | Effort | Bypass Factor | Detectability
─────────────────────────┼────────┼───────────────┼──────────────────
Multi-instance           | LOW    | 10-100x       | LOW
Case sensitivity         | TRIVIAL| 3-5x          | VERY LOW
Unicode homoglyphs       | LOW    | 5-10x         | VERY LOW
Clock manipulation       | MEDIUM | Unlimited     | MEDIUM
Instance restart         | MEDIUM | Unlimited     | LOW
Race conditions          | HIGH   | 1.1-1.5x      | VERY LOW
Entity key collision     | MEDIUM | 2-3x          | LOW

OVERALL RISK: CRITICAL
Current implementation provides ZERO protection in distributed deployments
```

---

## Defense Strategy Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                        REQUIRED DEFENSES                            │
└─────────────────────────────────────────────────────────────────────┘

Defense Layer              | Priority | Implementation
───────────────────────────┼──────────┼─────────────────────────────────
Redis distributed state    | P0       | RedisTokenBucket with Lua scripts
Agent ID normalization     | P0       | lowercase + NFC + strip ZWS
Monotonic clock            | P1       | time.monotonic() instead of time()
LRU bucket cache           | P1       | OrderedDict with max_size
Alerting on violations     | P1       | Send alerts when rate limit hit
Homoglyph detection        | P2       | Reject confusable characters
Rate limit warming         | P2       | Gradual limit increases
Circuit breakers           | P2       | Auto-block after violations

┌────────────────────────────────────────────────────────────────────┐
│ CRITICAL PATH:                                                     │
│                                                                    │
│ 1. Implement Redis backend (P0)                                   │
│ 2. Add ID normalization (P0)                                      │
│ 3. Switch to monotonic clock (P1)                                 │
│ 4. Deploy and test with 100+ instances                            │
│ 5. Monitor and tune for production                                │
└────────────────────────────────────────────────────────────────────┘
```

---

## Timeline & Impact

**Current State**: CRITICAL VULNERABILITY
- Production deployments have NO rate limit enforcement
- Cost overruns: 10-100x expected
- API quotas: Easily exhausted by single attacker

**After P0 Fixes** (1-2 weeks):
- Redis-backed distributed rate limiting
- Agent ID normalization
- 95% of bypass attacks prevented

**After P1 Fixes** (3-4 weeks):
- Monotonic clock (immune to time manipulation)
- LRU cache (prevents memory exhaustion)
- Alerting (detect attacks in progress)

**After P2 Fixes** (5-8 weeks):
- Homoglyph detection
- Advanced defenses
- 99.9% attack prevention
