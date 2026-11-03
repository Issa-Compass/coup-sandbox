"""Mostly truthful: rare light bluffs, survival Contessa, challenges only soft claims."""

from agents.examples.foundation import FoundationBot, Tendencies


class HonestBot(FoundationBot):
    TENDENCIES = Tendencies(
        challenge_only_impossible=False,
        challenge_p_max=0.12,
        spare_life_for_speculate=True,
        survival_contessa_bluff=True,
        bluff_tax=0.12,
        bluff_assassinate=0.05,
        bluff_steal=0.05,
        bluff_exchange=0.0,
        bluff_block_contessa_at_two=0.10,
        bluff_block_steal=0.08,
        bluff_block_duke_fa=0.05,
    )
