import re, time
from collections import deque, defaultdict

# Пер-юзер хранилище временных меток (простая in-memory реализация)
_last_messages = defaultdict(lambda: deque(maxlen=10))

def rate_limit_ok(user_id: int, now: float, hard_every_sec=2.0, soft_n=5, soft_window=15.0):
    dq = _last_messages[user_id]
    # hard: не чаще одного обращения к LLM раз в 2 сек
    if dq and (now - dq[-1]) < hard_every_sec:
        return False, "fast"
    # soft: не более 5 сообщений за 15 секунд
    while dq and (now - dq[0]) > soft_window:
        dq.popleft()
    if len(dq) >= soft_n:
        return False, "burst"
    dq.append(now)
    return True, ""

def normalize_text(t: str) -> str:
    return re.sub(r"\s+", "", t.lower())

def is_duplicate(prev_text: str, curr_text: str) -> bool:
    if not prev_text: return False
    return normalize_text(prev_text) == normalize_text(curr_text)

def is_gibberish(t: str) -> bool:
    t = t.strip()
    if len(t) < 2:
        return True
    n = len(t)
    letters = sum(ch.isalpha() for ch in t)
    letters_ratio = letters / max(n,1)
    flag1 = letters_ratio < 0.6
    flag2 = bool(re.search(r'(.)\1{3,}', t))
    flag3 = bool(re.search(r'(йцукен|qwerty|asdfg|zxcvb)', t.lower()))
    unique_ratio = len(set(t)) / max(n,1)
    flag4 = (n >= 12 and unique_ratio < 0.2)
    common = ('я','ты','что','как','почему','привет','да','нет','хочу','могу')
    flag5 = not any(w in t.lower() for w in common)
    flags = sum([flag1, flag2, flag3, flag4, flag5])
    return flags >= 2
