"""
Basic import test for the shared-models package.
Run this file to verify that all shared models
can be imported without errors.
"""

from shared_models.database import Base
from shared_models.models import User, Role


def test_imports():
    assert Base is not None
    assert User is not None
    assert Role is not None


if __name__ == "__main__":
    print("✅ Base imported successfully.")
    print("✅ User model imported successfully.")
    print("✅ Role model imported successfully.")
    print("🎉 Shared Models package is working correctly.")