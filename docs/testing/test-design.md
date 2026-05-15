# Test Design Principles

This document defines how to decide what to test, how to structure test suites, and what makes a test valuable.

## The Test Pyramid

**Rule:** Maintain a test distribution shaped like a pyramid:
- **70% unit tests** — fast, isolated, test one function or class
- **20% integration tests** — test multiple components together
- **10% end-to-end tests** — test the full system from outside

**Why:** Unit tests are fast and pinpoint failures. E2E tests are slow but verify the whole system works. A balanced pyramid gives feedback at every level.

**Good distribution:**
```
        /\        E2E (10%)
       /  \       — full pipeline: user input → final code output
      /────\      
     /      \     Integration (20%)
    /        \    — agents call LLM pool, RAG retrieval, etc.
   /──────────\   
  /            \  Unit (70%)
 /              \ — individual functions, no external dependencies
/________________\
```

## What to Test

**Rule:** Test behavior, not implementation.

**Why:** Tests of behavior survive refactors. Tests of implementation break every time you change how something works.

**Good (tests behavior):**
```python
def test_pool_routes_coding_task_to_coder_node():
    pool = LLMPool(nodes=[CODER_NODE, REASONER_NODE])
    node = pool.pick_node(Capability.CODER)
    assert node.capability == Capability.CODER
```

**Bad (tests implementation):**
```python
def test_pool_calls_internal_filter_method():
    pool = LLMPool(...)
    spy = spy_on(pool._filter_by_capability)
    pool.pick_node(Capability.CODER)
    assert spy.was_called  # brittle: breaks if you refactor
```

## What NOT to Test

**Rule:** Do not test:
- Third-party libraries (trust they are tested by their authors)
- Trivial getters/setters with no logic
- Private methods directly (test them through the public API)
- Configuration constants

**Why:** These tests add maintenance burden without catching real bugs.

**Bad:**
```python
def test_int_addition():           # testing Python itself
    assert 1 + 1 == 2

def test_get_name_returns_name():  # trivial getter
    user = User(name="alice")
    assert user.get_name() == "alice"

def test_max_retries_constant():   # testing a constant
    assert MAX_RETRIES == 3
```

## Naming Tests: Use Behavior Descriptions

**Rule:** A test name should describe the behavior being verified, not just the function being called.

**Pattern:** `test_<unit>_<behavior>_<condition>` or `test_<expected_behavior>_when_<condition>`

**Why:** Behavior-based names act as living documentation. Reading the test names should reveal what the system does.

**Good:**
```python
def test_pool_returns_fallback_node_when_primary_unhealthy(): ...
def test_pool_raises_when_all_nodes_unhealthy(): ...
def test_calculator_handles_division_by_zero_with_error(): ...
def test_user_creation_sends_welcome_email_when_email_provided(): ...
```

**Bad:**
```python
def test_pool(): ...
def test_pick_node(): ...
def test_create_user_1(): ...
def test_division(): ...
```

## Test Data: Make It Obvious

**Rule:** Test inputs and expected outputs should be obvious to a reader. Avoid magic numbers; use values that signal intent.

**Why:** Cryptic test data makes failures hard to interpret.

**Good:**
```python
def test_apply_tax_adds_percentage_to_price():
    price = Decimal("100.00")
    tax_rate = Decimal("0.20")  # 20% — easy to verify

    result = apply_tax(price, tax_rate)

    assert result == Decimal("120.00")  # 100 + 20% = 120, obvious
```

**Bad:**
```python
def test_apply_tax():
    result = apply_tax(Decimal("87.43"), Decimal("0.0825"))
    assert result == Decimal("94.65")  # is this right? hard to tell
```

## Use Builders or Factories for Complex Objects

**Rule:** When tests need complex objects, use builder/factory helpers to keep test code focused on what is being tested.

**Why:** Test setup that mirrors production setup buries the actual assertion.

**Good:**
```python
# tests/factories.py
def make_user(**overrides) -> User:
    defaults = {
        "id": 1,
        "email": "alice@example.com",
        "name": "Alice",
        "is_active": True,
    }
    return User(**{**defaults, **overrides})


# tests/test_authorization.py
def test_inactive_user_cannot_access_admin():
    user = make_user(is_active=False)
    assert not can_access_admin(user)
```

**Bad:**
```python
def test_inactive_user_cannot_access_admin():
    user = User(
        id=1,
        email="alice@example.com",
        name="Alice",
        is_active=False,
        created_at=datetime.now(),
        last_login=None,
        role="user",
        # ... 10 more fields
    )
    assert not can_access_admin(user)
```

## Property-Based Testing (Hypothesis)

**Rule:** For algorithms with mathematical properties, use property-based tests with Hypothesis to generate random inputs.

**Why:** Property tests find edge cases you would not think to write by hand.

**Good:**
```python
from hypothesis import given, strategies as st

@given(st.lists(st.integers()))
def test_reverse_twice_is_identity(items):
    assert reverse(reverse(items)) == items


@given(st.integers(min_value=0), st.integers(min_value=0))
def test_gcd_divides_both_inputs(a, b):
    g = gcd(a, b)
    assert a % g == 0
    assert b % g == 0
```

## Snapshot/Golden Testing for Outputs

**Rule:** For tests of complex output (generated code, JSON structures, rendered text), use snapshot testing libraries like `pytest-snapshot` or `syrupy`.

**Why:** Snapshots are easy to update intentionally but signal unintended changes.

**Good:**
```python
def test_developer_agent_output_matches_snapshot(snapshot):
    code = developer.generate("Write a fibonacci function")
    snapshot.assert_match(code, "fibonacci_function.py")
```

## Integration Tests: Use Real Dependencies When Possible

**Rule:** Integration tests should use real (or test-grade) versions of dependencies, not mocks.

**Why:** Mocked integration tests prove that your mock works, not that the integration works.

**Good:**
```python
@pytest.fixture
def test_chroma_db(tmp_path):
    """Use real ChromaDB pointed at a temp directory."""
    return chromadb.PersistentClient(path=str(tmp_path))


def test_rag_ingest_and_retrieve_roundtrip(test_chroma_db):
    ingest_documents(test_chroma_db, ["doc1 about python", "doc2 about rust"])
    results = retrieve(test_chroma_db, "python", k=1)
    assert "python" in results[0].text.lower()
```

## End-to-End Tests: Cover Critical Paths Only

**Rule:** E2E tests are expensive. Cover the 3-5 most critical user journeys, not every feature.

**Why:** E2E tests are slow, flaky, and hard to maintain. They earn their place by catching integration bugs nothing else catches.

**Good (multi-agent system):**
```python
@pytest.mark.e2e
async def test_full_pipeline_generates_passing_code():
    workflow = build_workflow()

    result = await workflow.ainvoke({
        "task": "Write a function that returns the nth Fibonacci number",
        "mode": "generate",
    })

    assert "def fibonacci" in result["code"][next(iter(result["code"]))]
    assert result["test_results"]["passed"] == result["test_results"]["total"]
```

## Test Performance

**Rule:** Tests must run fast. Target: full unit suite in <30 seconds, full test suite in <5 minutes.

**Why:** Slow tests get skipped, which means bugs ship.

**Strategies:**
- Mark slow tests with `@pytest.mark.slow` and exclude by default
- Parallelize with `pytest-xdist` (`pytest -n auto`)
- Profile with `pytest --durations=10` to find slowest tests
- Replace network I/O in unit tests with mocks
- Use in-memory databases (SQLite) instead of real DB for most cases

## Flaky Tests

**Rule:** Flaky tests (sometimes pass, sometimes fail) must be fixed or quarantined. Never ignore them.

**Why:** A flaky test trains developers to ignore failures, masking real bugs.

**Common causes:**
- Time-dependent assertions (use `freezegun` to mock time)
- Order-dependent state (ensure fixture isolation)
- Random data (seed it)
- Network calls (mock or use deterministic test doubles)
- Concurrent state (use locks, deterministic schedulers)

## Test Smells

Watch for these signals that a test needs attention:
- **Test is longer than the code it tests** → extract helpers
- **Test has many mocks** → may be testing implementation, not behavior
- **Test fails intermittently** → fix the root cause, don't retry
- **Comments in test explaining what it does** → rename the test
- **Multiple unrelated assertions** → split into multiple tests
- **`time.sleep` in tests** → replace with deterministic synchronization
