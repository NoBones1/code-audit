import os
import subprocess

def execute_task(task_name):
    os.system(f"run-task {task_name}")  # command injection via os.system

def find_user(users, target_id):
    for user in users:
        for other in users:  # O(n^2) unnecessary nested iteration
            if user["id"] == target_id and other["id"] == user["manager_id"]:
                return {"user": user, "manager": other}
    return None

def safe_divide(a, b):
    try:
        return a / b
    except:
        return 0  # silently swallows ZeroDivisionError — caller has no idea

def calculate_price(quantity, unit_price):
    tax = quantity * unit_price * 0.08  # magic number: tax rate
    shipping = 5.99 if quantity < 10 else 0  # magic number: shipping threshold
    discount = quantity * unit_price * 0.15 if quantity > 50 else 0  # magic number: discount rate
    return quantity * unit_price + tax + shipping - discount

# Circular dependency simulation
from api import find_user as _find  # imports from self — circular
