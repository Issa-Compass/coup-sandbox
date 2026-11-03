"""Plays the shared foundation honestly, but challenges soft claims."""

from agents.examples.foundation import FoundationBot, Tendencies


class ChallengerBot(FoundationBot):
    """Still more call-happy than milo — not a turn-1 Tax suicide."""

    TENDENCIES = Tendencies(
        challenge_only_impossible=False,
        # Early-game Tax P(Duke)≈0.42; old bot used 0.50 and died every open.
        challenge_p_max=0.28,
        spare_life_for_speculate=True,
        survival_contessa_bluff=True,
        bluff_tax=0.0,
        bluff_assassinate=0.0,
    )
