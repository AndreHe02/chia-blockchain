from typing import Dict, List, Optional, Tuple

from blspy import G2Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import CoinSpend, SpendBundle
from chia.util.ints import uint64

from chia.wallet.hc_wallet.hc_utils import (
    HC_MOD,
    hc_puzzle_for_lineage,
    hc_puzzle_hash_for_lineage_hash,
    bundle_for_spendable_hc_list,
    # spendable_hc_list_from_coin_spend,
)

CONDITIONS = dict((k, bytes(v)[0]) for k, v in ConditionOpcode.__members__.items())  # pylint: disable=E1101

NULL_SIGNATURE = G2Element()

ANYONE_CAN_SPEND_PUZZLE = Program.to(1)  # simply return the conditions

PUZZLE_TABLE: Dict[bytes32, Program] = dict((_.get_tree_hash(), _) for _ in [ANYONE_CAN_SPEND_PUZZLE])


def hash_to_puzzle_f(puzzle_hash: bytes32) -> Optional[Program]:
    return PUZZLE_TABLE.get(puzzle_hash)


def add_puzzles_to_puzzle_preimage_db(puzzles: List[Program]) -> None:
    for _ in puzzles:
        PUZZLE_TABLE[_.get_tree_hash()] = _


def int_as_bytes32(v: int) -> bytes32:
    return v.to_bytes(32, byteorder="big")


def generate_farmed_coin(
        block_index: int,
        puzzle_hash: bytes32,
        amount: int,
) -> Coin:
    """
    Generate a (fake) coin which can be used as a starting point for a chain
    of coin tests.
    """
    return Coin(int_as_bytes32(block_index), puzzle_hash, uint64(amount))


def issue_hc_from_farmed_coin(
        mod_code: Program,
        block_id: int,
        lineage_hash: bytes32,
        amount: int
) -> Tuple[Program, SpendBundle]:
    farmed_puzzle = ANYONE_CAN_SPEND_PUZZLE
    farmed_puzzle_hash = farmed_puzzle.get_tree_hash()
    farmed_coin = generate_farmed_coin(block_id, farmed_puzzle_hash, amount=uint64(amount))
    minted_hc_puzzle_hash = hc_puzzle_hash_for_lineage_hash(mod_code, lineage_hash)
    output_conditions = [[ConditionOpcode.CREATE_COIN, minted_hc_puzzle_hash, farmed_coin.amount]]
    # solution is just the conditions
    solution = Program.to(output_conditions)
    coin_spend = CoinSpend(farmed_coin, farmed_puzzle, solution)
    spend_bundle = SpendBundle([coin_spend], NULL_SIGNATURE)
    return spend_bundle


def solution_for_pay_to_any(puzzle_hash_amount_pairs: List[Tuple[bytes32, int]]) -> Program:
    output_conditions = [
        [ConditionOpcode.CREATE_COIN, puzzle_hash, amount] for puzzle_hash, amount in puzzle_hash_amount_pairs
    ]
    return Program.to(output_conditions)

# to get an ancestry object, use Program.parse( "(list xxx xxx)")


def main():
    issue_hc_from_farmed_coin(HC_MOD, )

if __name__ == "__main__":
    #Program.from_bytes(b"(c 1 (c 2 ()))")
    main()
