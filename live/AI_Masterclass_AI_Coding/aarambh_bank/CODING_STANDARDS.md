# CODING_STANDARDS.md — Aarambh Bank

These are the project's coding standards. All code must follow them.

## 1. Variable names — `snake_case`

Variables use lowercase words separated by underscores.

```python
# Good
account_balance = Decimal("0.00")
user_id = 42

# Bad
accountBalance = 0
UserId = 42
```

## 2. Function names — start with `fun_`

Every function name starts with the prefix `fun_`, followed by a `snake_case` description.

```python
# Good
def fun_create_account(user_id):
    ...

def fun_get_balance(account_id):
    ...

# Bad
def create_account(user_id):   # missing fun_ prefix
    ...

def fun_CreateAccount(user_id):  # not snake_case
    ...
```

## 3. Constants — ALL CAPS

Constant variables are written in uppercase, with words separated by underscores.

```python
# Good
MAX_WITHDRAWAL_LIMIT = Decimal("100000.00")
DEFAULT_CURRENCY = "INR"

# Bad
max_withdrawal_limit = 100000
DefaultCurrency = "INR"
```

## 4. Docstrings — required in every function

Every function must have a docstring that describes what it does. Include parameters and the return value.

```python
# Good
def fun_get_balance(account_id):
    """Return the current balance for the given account.

    Args:
        account_id: ID of the account to look up.

    Returns:
        Decimal: the account's current balance.
    """
    ...

# Bad
def fun_get_balance(account_id):   # no docstring
    ...
```
