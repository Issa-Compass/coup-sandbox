"""Seeds handed to agents are not the deck seed.

The tournament keeps a secret in the parent process and derives each deck
seed with HMAC. Agents only receive a personal RNG seed, so copying the
shuffle code does not reveal hidden cards.
"""

from __future__ import annotations

import hashlib
import hmac


def game_seed(secret: bytes, master_seed: int, index: int) -> int:
    digest = hmac.new(secret, f"{master_seed}:{index}".encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:16], "big")


def personal_seed(game_seed_value: int, seat: int, name: str) -> int:
    digest = hashlib.sha256(f"{game_seed_value}|{seat}|{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big")
