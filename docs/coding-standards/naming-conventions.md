# Naming Conventions

Names are documentation. A well-chosen name eliminates the need for a comment. This document defines naming rules for all Python code in the project.

## Variables and Functions

**Rule:** Use `snake_case` for variables, functions, and method names.

**Why:** Standard Python convention (PEP 8). Lowercase letters with underscores are readable and unambiguous.

**Good:**
```python
user_count = 42
maximum_retries = 3

def fetch_user_data(user_id: int) -> User:
    ...

def calculate_total_price(items: list[Item]) -> Decimal:
    ...
```

**Bad:**
```python
userCount = 42           # camelCase
MaximumRetries = 3       # PascalCase
def fetchUserData(uid):  # camelCase + cryptic abbreviation
    ...
```

## Classes

**Rule:** Use `PascalCase` (also called `UpperCamelCase`) for class names.

**Why:** Distinguishes classes from instances and functions at a glance. PEP 8 standard.

**Good:**
```python
class UserRepository:
    pass

class HTTPConnectionPool:
    pass

class JSONEncoder:
    pass
```

**Bad:**
```python
class user_repository:    # snake_case
    pass

class httpConnectionPool: # camelCase
    pass
```

## Constants

**Rule:** Use `UPPER_SNAKE_CASE` for module-level constants and enum values.

**Why:** Visual signal that the value should not change at runtime. Easy to grep.

**Good:**
```python
MAX_BUFFER_SIZE = 4096
DEFAULT_TIMEOUT_SECONDS = 30
API_BASE_URL = "https://api.example.com"

class Status(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
```

## Private Members

**Rule:** Prefix internal/private attributes and methods with a single underscore `_`. Use double underscore `__` only when name mangling is required (rare).

**Why:** Single underscore is a clear convention that says "this is not part of the public API". Double underscore triggers Python's name mangling and should be avoided unless inheritance conflicts must be prevented.

**Good:**
```python
class Service:
    def __init__(self):
        self._client = self._create_client()  # internal

    def execute(self):                        # public API
        return self._client.call()

    def _create_client(self):                 # internal helper
        ...
```

**Bad:**
```python
class Service:
    def __init__(self):
        self.__client = self.__create_client()  # double underscore unnecessary

    def execute(self):
        return self.__client.call()
```

## Dunder Methods

**Rule:** Reserve double-underscore (dunder) names like `__init__`, `__str__`, `__call__` for Python's special methods only. Never invent your own dunder names.

**Why:** Inventing dunder names risks future collisions with Python language additions.

**Good:**
```python
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __repr__(self):
        return f"Point({self.x}, {self.y})"
```

**Bad:**
```python
class Point:
    def __my_custom_init__(self, x, y):  # not a real dunder
        ...
```

## Boolean Variables

**Rule:** Boolean variables and functions returning booleans must use `is_`, `has_`, `can_`, `should_` prefixes.

**Why:** Reading the name should reveal it is a boolean question, removing the need to check the type.

**Good:**
```python
is_active = True
has_admin_role = check_role(user)
can_delete = user.id == resource.owner_id
should_retry = response.status_code >= 500

def is_valid_email(email: str) -> bool:
    ...

def has_permission(user: User, action: str) -> bool:
    ...
```

**Bad:**
```python
active = True              # is it a flag or a count?
admin = check_role(user)   # is it a bool or the admin object?
delete = user.id == resource.owner_id  # confusing
```

## Counts and Quantities

**Rule:** Variables holding counts must use `_count`, `_total`, or `n_` prefix/suffix.

**Why:** Distinguishes a count from a collection holding the items.

**Good:**
```python
user_count = len(users)
total_price = sum(item.price for item in cart)
n_retries = 0

def get_active_user_count() -> int:
    ...
```

**Bad:**
```python
users = 42        # is this a list or a count?
price = sum(...)  # is this one price or total?
```

## Collections

**Rule:** Use plural nouns for collections (list, set, tuple, dict-of-values). For mappings, name based on what maps to what.

**Why:** Plural signals iterability. `users_by_id` immediately reveals dict structure.

**Good:**
```python
users: list[User] = []
allowed_roles: set[str] = {"admin", "editor"}
users_by_id: dict[int, User] = {}
emails_by_user: dict[User, str] = {}
```

**Bad:**
```python
user_list: list[User] = []       # redundant "_list" suffix
users: dict[int, User] = {}      # plural but dict, confusing
data: dict = {}                  # what kind of data?
```

## Avoid Generic Names

**Rule:** Avoid names like `data`, `info`, `value`, `result`, `temp`, `obj`, `item` unless the context is genuinely generic (e.g., inside a 3-line lambda).

**Why:** Generic names hide intent. The reader must trace usage to understand what the variable holds.

**Good:**
```python
def parse_response(raw_response: bytes) -> ParsedMessage:
    json_payload = json.loads(raw_response)
    user_records = json_payload["users"]
    return ParsedMessage(records=user_records)
```

**Bad:**
```python
def parse_response(data: bytes) -> ParsedMessage:
    obj = json.loads(data)
    items = obj["users"]
    return ParsedMessage(records=items)
```

## Avoid Cryptic Abbreviations

**Rule:** Spell out names. Acceptable abbreviations: `id`, `url`, `db`, `api`, `http`, `json`, `xml`, `i`/`j`/`k` (loop indices). Avoid `usr`, `cnt`, `flg`, `tmp`, `mngr`.

**Why:** A short name is not the same as a clear name. Modern editors auto-complete; you do not save real typing.

**Good:**
```python
user_count = len(users)
manager = get_user_manager()
temperature = read_sensor()
```

**Bad:**
```python
usr_cnt = len(users)
mngr = get_user_manager()
tmp = read_sensor()
```

## File and Module Names

**Rule:** Module filenames must be `lowercase_with_underscores.py`. Package directories use the same convention.

**Why:** Some filesystems are case-insensitive. Lowercase names avoid platform issues.

**Good:**
```
app/
├── user_service.py
├── http_client.py
└── data_models.py
```

**Bad:**
```
app/
├── UserService.py
├── HTTPClient.py
└── dataModels.py
```

## Test File Naming

**Rule:** Test files must be `test_<module>.py`. Test functions must start with `test_`.

**Why:** pytest auto-discovery relies on this convention.

**Good:**
```python
# test_user_service.py
def test_create_user_with_valid_email_succeeds():
    ...

def test_create_user_with_invalid_email_raises():
    ...
```

## Avoid Single-Letter Names

**Rule:** Single-letter names are allowed only for:
- Loop counters: `i`, `j`, `k`
- Coordinates: `x`, `y`, `z`
- Common math symbols inside math-heavy code
- Generic type variables: `T`, `K`, `V`

Everywhere else, use descriptive names.

**Good:**
```python
T = TypeVar("T")

def first(items: list[T]) -> T:
    return items[0]

for i, user in enumerate(users):
    process(i, user)
```

**Bad:**
```python
def f(u):           # what is f? what is u?
    return u.email
```
