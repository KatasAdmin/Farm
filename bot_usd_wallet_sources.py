"""Source-aware USD funds in integer micro-dollars.

This module is a PURE, staged accounting core. It deliberately does not
touch existing UAH balances or authorize real bank/crypto payouts.

Deposits and promotional grants are spend-only; only advertiser-funded
work and confirmed advertising revenue can become eligible for cashout.
"""
from dataclasses import dataclass

EARNED_SOURCES = frozenset({"task_reward", "confirmed_ad_reward", "confirmed_referral"})
SPEND_ONLY_SOURCES = frozenset({"stars_purchase", "card_purchase", "promo", "daily_bonus", "game_purchase"})
ALL_SOURCES = EARNED_SOURCES | SPEND_ONLY_SOURCES

@dataclass(frozen=True)
class USDWallet:
    spend_only_micro: int = 0
    earned_micro: int = 0
    cashout_reserved_micro: int = 0

    def __post_init__(self):
        if any(type(x) is not int or x < 0 for x in (
            self.spend_only_micro, self.earned_micro, self.cashout_reserved_micro
        )):
            raise ValueError("Wallet micro-USD balances must be nonnegative integers")
        if self.cashout_reserved_micro > self.earned_micro:
            raise ValueError("Cashout reserves cannot exceed earned funds")

    @property
    def available_micro(self):
        return self.spend_only_micro + self.earned_micro - self.cashout_reserved_micro

    @property
    def cashout_available_micro(self):
        return self.earned_micro - self.cashout_reserved_micro

def credit(wallet, source, amount):
    if source not in ALL_SOURCES:
        raise ValueError("Unknown deposit origin, cannot assign cashout eligibility")
    if type(amount) is not int or amount <= 0:
        raise ValueError("Credit must be positive integer micro-USD")
    if source in EARNED_SOURCES:
        return USDWallet(wallet.spend_only_micro, wallet.earned_micro + amount, wallet.cashout_reserved_micro)
    return USDWallet(wallet.spend_only_micro + amount, wallet.earned_micro, wallet.cashout_reserved_micro)

def spend(wallet, amount):
    if type(amount) is not int or amount <= 0 or amount > wallet.available_micro:
        raise ValueError("Insufficient available funds")
    spend_only_used = min(wallet.spend_only_micro, amount)
    earned_used = amount - spend_only_used
    return USDWallet(wallet.spend_only_micro - spend_only_used,
                     wallet.earned_micro - earned_used, wallet.cashout_reserved_micro)

def reserve_cashout(wallet, amount):
    if type(amount) is not int or amount <= 0 or amount > wallet.cashout_available_micro:
        raise ValueError("Insufficient verified earnings for cashout")
    return USDWallet(wallet.spend_only_micro, wallet.earned_micro,
                     wallet.cashout_reserved_micro + amount)

def cancel_cashout(wallet, amount):
    if type(amount) is not int or amount <= 0 or amount > wallet.cashout_reserved_micro:
        raise ValueError("No matching reserved payout")
    return USDWallet(wallet.spend_only_micro, wallet.earned_micro,
                     wallet.cashout_reserved_micro - amount)

def complete_cashout(wallet, amount):
    if type(amount) is not int or amount <= 0 or amount > wallet.cashout_reserved_micro:
        raise ValueError("No matching reserved payout")
    return USDWallet(wallet.spend_only_micro, wallet.earned_micro - amount,
                     wallet.cashout_reserved_micro - amount)
