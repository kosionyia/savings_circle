from app.models.payout import PayoutStatus


class IllegalTransition(Exception):
    """The payout is not in a state that allows this action."""


TRANSITIONS: dict[str, tuple[PayoutStatus, PayoutStatus]] = {
    # action:    (must currently be,       becomes)
    "approve": (PayoutStatus.SCHEDULED, PayoutStatus.APPROVED),
    "initiate": (PayoutStatus.APPROVED, PayoutStatus.INITIATED),
    "confirm": (PayoutStatus.INITIATED, PayoutStatus.CONFIRMED),
    "fail": (PayoutStatus.INITIATED, PayoutStatus.FAILED),
    "reverse": (PayoutStatus.FAILED, PayoutStatus.REVERSED),
}


def next_status(current: PayoutStatus, action: str) -> PayoutStatus:
    if action not in TRANSITIONS:
        raise IllegalTransition(f"Unknown payout action: {action}")

    required, becomes = TRANSITIONS[action]
    if current != required:
        raise IllegalTransition(
            f"Cannot {action} a payout that is {current.value}; "
            f"it must be {required.value}"
        )
    return becomes
