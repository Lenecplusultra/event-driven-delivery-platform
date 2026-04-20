"""
services/restaurant-service/tests/conftest.py
"""

import uuid
import pytest


@pytest.fixture
def sample_restaurant_payload():
    return {
        "name": "Test Pizzeria",
        "description": "Best pizza in Atlanta",
        "address": "789 Peachtree St NE, Atlanta, GA 30308",
        "menu": {
            "name": "Main Menu",
            "items": [
                {"name": "Margherita", "price": "12.99", "is_available": True},
                {"name": "Pepperoni", "price": "14.99", "is_available": True},
            ],
        },
    }
