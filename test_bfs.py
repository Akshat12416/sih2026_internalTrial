from collections import deque
class Dummy: pass
wmap = Dummy()
wmap.grid = [[0]*15 for _ in range(15)]
wmap.neighbours = lambda c: [(c[0]-1, c[1]), (c[0]+1, c[1]), (c[0], c[1]-1), (c[0], c[1]+1)]

occupied = {(4, 9)}
peer_paths = {(4, 9), (4, 8), (4, 7), (4, 6)}

def bfs(start):
    seen = {start}
    q = deque([start])
    candidates = []
    while q:
        cur = q.popleft()
        if cur != start and cur not in occupied:
            if cur not in peer_paths:
                return cur
            else:
                candidates.append(cur)
        if cur == start or cur not in occupied:
            for n in wmap.neighbours(cur):
                if n not in seen:
                    seen.add(n)
                    q.append(n)
    return candidates[0] if candidates else None

print("BFS found:", bfs((4, 8)))
