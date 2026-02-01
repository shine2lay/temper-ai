# Tiered Planning System - Implementation Plan

## Problem Statement

**Current inefficiency:**
```
create-task-spec skill → spawns agents → creates spec
Agent picks up task → spawns MORE agents → finally does work
```

This creates unnecessary agent nesting and re-planning of already-planned work.

## Solution: Tiered Approach

**Core principle:** The spec IS the plan. Executing agents follow specs directly without re-planning.

### Tier 1: Quick Tasks (category: `quick`)
- **Spec:** None - just task description in coord DB
- **Execution:** Agent reads task, does it immediately
- **Agent calls:** 0 (agent works autonomously)
- **Use for:** Bug fixes, typos, minor tweaks

### Tier 2: Standard Tasks (category: `med`, `low`)
- **Spec:** Lightweight implementation notes (optional)
- **Execution:** Agent reads notes, figures out details autonomously
- **Agent calls:** 0 (agent plans internally, no subprocess agents)
- **Use for:** Standard features, refactors, tests

### Tier 3: Complex Tasks (category: `high`, `crit`)
- **Spec:** Detailed step-by-step implementation plan
- **Execution:** Agent follows plan exactly, no re-planning
- **Agent calls:** 0 during execution (agents used during spec creation only)
- **Use for:** Complex features, system changes, critical work

### Tier 4: Multi-Agent Tasks (large `high`/`crit`)
- **Spec:** Implementation plan + subtask breakdown
- **Execution:** Spec auto-creates multiple coordinated subtasks
- **Agent calls:** 0 per agent (coordination via task dependencies)
- **Use for:** Large features requiring parallel work

## Implementation Phases

### Phase 1: Define Spec Templates

**Goal:** Create clear templates for each tier

#### 1.1 Quick Task (No Spec File)
```yaml
# Stored in coord DB only
task_id: test-quick-typo-1
subject: Fix typo in README
description: Change "recieve" to "receive" in installation section
acceptance_criteria:
  - Typo corrected
  - No other changes
```

**Agent execution:**
```
1. Read task from coord DB
2. Find file (README.md)
3. Make change directly
4. Complete task
```

#### 1.2 Standard Task (Lightweight Spec)
```markdown
# Task: code-med-user-validation-1

## Goal
Add email validation to user registration

## Acceptance Criteria
- Email format validated before saving
- Error message shown for invalid emails
- Existing tests still pass

## Implementation Notes
**Files to modify:**
- `src/models/user.py` - Add validation method
- `src/api/register.py` - Call validation before save
- `tests/test_user.py` - Add validation tests

**Approach:**
- Use regex pattern for email validation
- Raise ValueError on invalid email
- Catch in API handler and return 400

**Pattern to follow:**
Similar to phone number validation in `src/models/profile.py:45`
```

**Agent execution:**
```
1. Read spec
2. Follow implementation notes
3. Agent decides exact implementation details
4. No additional agent calls
```

#### 1.3 Complex Task (Detailed Implementation Plan)
```markdown
# Task Specification: code-high-oauth-integration-1

## Problem Statement
Users need OAuth login to reduce friction and improve security.

## Acceptance Criteria
- Google OAuth integration working
- GitHub OAuth integration working
- OAuth tokens securely stored
- Existing password login still works
- Session management updated

## Implementation Plan

### Step 1: Add OAuth dependencies
**File:** `requirements.txt`
**Changes:**
```
+ authlib==1.3.0
+ httpx==0.27.0
```

**File:** `src/config.py`
**Changes:**
```python
+ OAUTH_GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
+ OAUTH_GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
+ OAUTH_GITHUB_CLIENT_ID = os.getenv('GITHUB_CLIENT_ID')
+ OAUTH_GITHUB_CLIENT_SECRET = os.getenv('GITHUB_CLIENT_SECRET')
```

### Step 2: Create OAuth service
**File:** `src/auth/oauth.py` (new file)
**Complete implementation:**
```python
from authlib.integrations.flask_client import OAuth

oauth = OAuth()

def init_oauth(app):
    oauth.init_app(app)

    oauth.register(
        name='google',
        client_id=app.config['OAUTH_GOOGLE_CLIENT_ID'],
        client_secret=app.config['OAUTH_GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

    oauth.register(
        name='github',
        client_id=app.config['OAUTH_GITHUB_CLIENT_ID'],
        client_secret=app.config['OAUTH_GITHUB_CLIENT_SECRET'],
        access_token_url='https://github.com/login/oauth/access_token',
        authorize_url='https://github.com/login/oauth/authorize',
        api_base_url='https://api.github.com/',
        client_kwargs={'scope': 'user:email'}
    )

    return oauth
```

### Step 3: Add OAuth routes
**File:** `src/api/auth.py`
**Add these routes:**
```python
@app.route('/auth/oauth/<provider>')
def oauth_login(provider):
    redirect_uri = url_for('oauth_callback', provider=provider, _external=True)
    return oauth.create_client(provider).authorize_redirect(redirect_uri)

@app.route('/auth/oauth/<provider>/callback')
def oauth_callback(provider):
    client = oauth.create_client(provider)
    token = client.authorize_access_token()
    user_info = client.parse_id_token(token)

    # Find or create user
    user = User.query.filter_by(email=user_info['email']).first()
    if not user:
        user = User(
            email=user_info['email'],
            name=user_info.get('name'),
            oauth_provider=provider,
            oauth_id=user_info['sub']
        )
        db.session.add(user)
        db.session.commit()

    # Create session
    login_user(user)
    return redirect('/')
```

### Step 4: Update database model
**File:** `src/models/user.py`
**Add to User model:**
```python
class User(db.Model):
    # ... existing fields ...
+   oauth_provider = db.Column(db.String(20), nullable=True)
+   oauth_id = db.Column(db.String(255), nullable=True)
+
+   __table_args__ = (
+       db.Index('idx_oauth', 'oauth_provider', 'oauth_id', unique=True),
+   )
```

### Step 5: Create migration
**Command to run:**
```bash
flask db migrate -m "Add OAuth fields to User model"
flask db upgrade
```

### Step 6: Add tests
**File:** `tests/test_oauth.py` (new file)
**Test cases:**
```python
def test_oauth_google_redirect():
    """Test Google OAuth redirect"""
    response = client.get('/auth/oauth/google')
    assert response.status_code == 302
    assert 'accounts.google.com' in response.location

def test_oauth_callback_new_user():
    """Test OAuth callback creates new user"""
    # Mock OAuth response
    with patch('src.auth.oauth.oauth.google.authorize_access_token') as mock_token:
        mock_token.return_value = {...}
        response = client.get('/auth/oauth/google/callback')
        assert response.status_code == 302

        user = User.query.filter_by(email='test@example.com').first()
        assert user is not None
        assert user.oauth_provider == 'google'
```

## Test Strategy
- Unit tests for oauth.py service initialization
- Integration tests for OAuth flow (mocked)
- Manual testing with real OAuth apps
- Security review of token handling

## Dependencies
- None (independent feature)

## Rollout Plan
1. Deploy to staging with test OAuth apps
2. Test all flows manually
3. Deploy to production
4. Monitor error rates
```

**Agent execution:**
```
1. Read spec
2. Follow steps 1-6 in exact order
3. Implement code as written (can adapt syntax but not logic)
4. Run tests as specified
5. No re-planning, no agent calls
```

#### 1.4 Multi-Agent Task (Subtask Breakdown)
```markdown
# Task Specification: code-crit-payment-system-1

## Problem Statement
Implement Stripe payment processing for subscription billing.

## Acceptance Criteria
[... standard criteria ...]

## Implementation Plan

**This task should be broken into subtasks:**

### Subtask 1: code-high-stripe-integration-1
**Purpose:** Core Stripe API integration
**Dependencies:** None
**Files:** src/payment/stripe_client.py, src/config.py
**Implementation:** [detailed steps...]

### Subtask 2: code-high-subscription-model-1
**Purpose:** Database models for subscriptions
**Dependencies:** None
**Files:** src/models/subscription.py, migrations/
**Implementation:** [detailed steps...]

### Subtask 3: code-high-webhook-handler-1
**Purpose:** Handle Stripe webhooks
**Dependencies:** subtask-1
**Files:** src/api/webhooks.py
**Implementation:** [detailed steps...]

### Subtask 4: code-med-payment-ui-1
**Purpose:** Frontend payment forms
**Dependencies:** subtask-1, subtask-2
**Files:** src/templates/subscribe.html, src/static/payment.js
**Implementation:** [detailed steps...]

### Subtask 5: test-high-payment-integration-1
**Purpose:** End-to-end payment tests
**Dependencies:** ALL above
**Files:** tests/test_payment_flow.py
**Implementation:** [detailed steps...]

## Subtask Creation
When this spec is approved, automatically create all 5 subtasks in coordination system with proper dependencies.
```

**Execution:**
```
1. Spec created for main task
2. Auto-create 5 subtasks with dependencies
3. Different agents can pick up different subtasks
4. Coordination via dependency system
5. Each agent follows their subtask's detailed plan
```

### Phase 2: Update create-task-spec Skill

**Current behavior:**
```python
def create_task_spec(task_id, description):
    # Always spawns multiple agents
    spawn_agent('solution-architect')
    spawn_agent('technical-product-manager')
    spawn_agent('database-architect')
    # ... etc
    return spec
```

**New behavior:**
```python
def create_task_spec(task_id, description):
    # Determine tier from category
    category = extract_category(task_id)  # e.g., 'quick', 'med', 'high'

    if category == 'quick':
        # No spec file needed - just create task in coord
        return create_coord_task_only(task_id, description)

    elif category in ['med', 'low']:
        # Lightweight spec - use template
        return create_lightweight_spec(task_id, description)

    elif category in ['high', 'crit']:
        # Detailed spec - may use agents BUT focused
        return create_detailed_spec(task_id, description)
```

**Key changes:**
1. Tier detection based on category
2. Quick tasks skip spec creation entirely
3. Standard tasks use templates (minimal/no agent calls)
4. Complex tasks can use agents but produce ACTIONABLE specs
5. Multi-agent tasks auto-create subtasks

### Phase 3: Agent Execution Guidelines

**Add to CLAUDE.md:**

```markdown
## Task Execution Guidelines

### Reading Task Specs

**When you claim a task:**

1. **Check for spec file:** `.claude-coord/task-specs/<task-id>.md`

2. **If NO spec file (quick tasks):**
   - Read task from `coord task-get <task-id>`
   - Understand the goal from description/acceptance criteria
   - Implement autonomously
   - No agent calls needed

3. **If LIGHTWEIGHT spec (med/low tasks):**
   - Read spec for implementation notes
   - Use as guidance, not strict instructions
   - Agent decides implementation details
   - No agent calls needed

4. **If DETAILED spec (high/crit tasks):**
   - Read spec completely
   - Follow step-by-step implementation plan
   - Code examples should be implemented as written (adapt syntax only)
   - File changes should match spec
   - **Do NOT re-plan or call other agents**
   - **Do NOT use Task tool to spawn agents for planning**
   - Your job is EXECUTION, not planning

### When to Follow vs Adapt

**Follow exactly:**
- File structure from spec
- Code logic and algorithms
- API contracts
- Database schemas
- Security patterns

**Can adapt:**
- Variable names (if clearer)
- Code formatting
- Error message wording
- Test assertion style

**Do NOT change:**
- Architecture decisions
- Technology choices
- Data models
- API endpoints

### If Spec is Unclear

**Do NOT spawn agents to clarify.**

Instead:
1. Make reasonable assumptions based on context
2. Leave TODO comments for unclear parts
3. Complete what you can
4. Document questions in task completion notes

### Multi-Agent Tasks

If spec says "This should be broken into subtasks":
1. Subtasks are already created in coord system
2. Just claim the subtask assigned to you
3. Follow your subtask's detailed plan
4. Dependencies ensure proper ordering
```

### Phase 4: Subtask Auto-Creation

**When spec includes subtask breakdown:**

```python
def create_spec_with_subtasks(main_task_id, spec_content):
    # Parse subtask definitions from spec
    subtasks = parse_subtask_definitions(spec_content)

    # Create main task
    coord task-create {main_task_id} "{subject}" "{description}"

    # Create each subtask with dependencies
    for subtask in subtasks:
        deps = ','.join(subtask.depends_on) if subtask.depends_on else None

        cmd = f"coord task-create {subtask.id} \"{subtask.subject}\" \"{subtask.description}\""
        if deps:
            cmd += f" --depends-on {deps}"

        run(cmd)

        # Create detailed spec for this subtask
        create_subtask_spec(subtask.id, subtask.implementation_plan)

    # Mark main task as "decomposed" (special status)
    # Main task serves as parent/tracker only
```

### Phase 5: Validation & Templates

**Create spec templates:**

```
.claude-coord/spec-templates/
├── quick.md           # Empty (no spec for quick)
├── standard.md        # Lightweight template
├── detailed.md        # Full implementation plan template
└── multi-agent.md     # Subtask breakdown template
```

**Validation rules:**

- Quick tasks: No validation (no spec)
- Standard tasks: Must have Goal, Acceptance Criteria, Implementation Notes
- Detailed tasks: Must have all sections including step-by-step plan
- Multi-agent: Must have subtask definitions with dependencies

## Success Metrics

**Efficiency:**
- Reduce agent nesting from 3 levels to 1 level
- 50% reduction in agent calls during task execution
- Specs are actionable without re-planning

**Quality:**
- Agents follow specs consistently
- Less variation in implementation approaches
- Faster task completion (no re-planning overhead)

**Clarity:**
- Clear tier boundaries
- Agents know when to follow vs adapt
- Subtask coordination works smoothly

## Migration Plan

**Phase 1 (Week 1): Templates & Validation**
- Create spec templates
- Update validation in validator.py
- Test with sample specs

**Phase 2 (Week 1-2): Update create-task-spec**
- Add tier detection
- Implement lightweight spec creation
- Test spec creation for all tiers

**Phase 3 (Week 2): Execution Guidelines**
- Update CLAUDE.md
- Add examples
- Document patterns

**Phase 4 (Week 2-3): Subtask System**
- Implement subtask parsing
- Auto-create coordinated subtasks
- Test multi-agent workflow

**Phase 5 (Week 3-4): Testing & Iteration**
- Run full workflows
- Gather feedback
- Refine templates and guidelines

## Open Questions

1. **Subtask naming convention?**
   - Proposal: `{main-task-id}-subtask-{n}` or semantic names?

2. **Spec update workflow?**
   - If agent finds spec wrong, what's the process?
   - Create a "spec-update" task?

3. **Spec review process?**
   - Should specs be reviewed before task creation?
   - Who reviews? User or another agent?

4. **Template customization?**
   - Can users/projects customize templates?
   - Where stored? `.claude-coord/spec-templates/custom/`?

5. **Metrics tracking?**
   - How to measure "spec following" vs "re-planning"?
   - Track agent calls per task execution?

## Next Steps

1. Review this plan with user
2. Answer open questions
3. Prioritize phases
4. Start with Phase 1 (templates)
