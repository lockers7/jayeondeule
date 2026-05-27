def factorial(n):
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result

assert factorial(5) == 120
assert factorial(0) == 1