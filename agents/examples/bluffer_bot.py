"""Claims Duke and Assassin often, including when it does not hold them."""

from agents.examples.foundation import FoundationBot, Tendencies


class BlufferBot(FoundationBot):
    TENDENCIES = Tendencies(
        challenge_only_impossible=False,
        challenge_p_max=0.16,
        challenge_noise=0.08,
        spare_life_for_speculate=True,
        survival_contessa_bluff=True,
        bluff_tax=0.70,
        bluff_assassinate=0.40,
        bluff_steal=0.15,
        bluff_exchange=0.10,
        bluff_block_contessa_at_two=0.55,
        bluff_block_steal=0.35,
        bluff_block_duke_fa=0.25,
        action_noise=0.05,
    )
