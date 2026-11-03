"""Mostly uniform legal moves, with survival floors so it is not free food."""

from agents.examples.foundation import FoundationBot, Tendencies


class RandomBot(FoundationBot):
    TENDENCIES = Tendencies(
        challenge_only_impossible=False,
        # Floors: impossible challenges + last-life Contessa. Everything else noisy.
        challenge_p_max=0.05,
        challenge_noise=0.35,
        spare_life_for_speculate=True,
        survival_contessa_bluff=True,
        bluff_tax=0.25,
        bluff_assassinate=0.20,
        bluff_steal=0.20,
        bluff_exchange=0.20,
        bluff_block_contessa_at_two=0.30,
        bluff_block_steal=0.30,
        bluff_block_duke_fa=0.20,
        action_noise=0.85,
        response_noise=0.75,
    )
