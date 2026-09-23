avoid_until = {(4, 7): 100}
occupied = {(4, 8)}
avoid_until = {c: exp for c, exp in avoid_until.items() if c in occupied}
print(avoid_until)
