"""Never claims a character it does not hold. Challenges only impossible claims."""

from agents.examples.foundation import FoundationBot, Tendencies


class HonestBot(FoundationBot):
    TENDENCIES = Tendencies(
        challenge_only_impossible=True,
        survival_contessa_bluff=False,
    )
