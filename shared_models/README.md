# Shared Models

This repository contains shared SQLAlchemy models used across multiple services.

Currently shared:

- User model
- Base class
- Common Mixins
- Enums

Services using this package:

- RBAC Service
- Ticket Management Service

Installation

```bash
pip install -e .
```

Import Example

```python
from shared_models.models import User
```