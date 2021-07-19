from typing import Dict, List, Optional, Tuple

from blspy import G2Element, G1Element, AugSchemeMPL

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import CoinSpend, SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution
from chia.util.ints import uint64
from chia.util.keychain import mnemonic_to_seed

from chia.wallet.hc_wallet.hc_utils import (
    HC_MOD,
    hc_puzzle_for_lineage_program,
    hc_puzzle_hash_for_lineage_hash,
    spend_bundle_for_spendable_hcs, SpendableHC,
)
from chia.wallet.util.debug_spend_bundle import disassemble

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


MNEMONIC1 = "mnemonic one"
MNEMONIC2 = "mnemonic two"
MNEMONIC3 = "mnemonic three"


def generate_test_keys(mnemonic):
    seed = mnemonic_to_seed(mnemonic, "passphrase")
    secret_key = AugSchemeMPL.key_gen(seed)
    public_key = secret_key.get_g1()
    return secret_key, public_key


def test_spend_to_two(mod_code):
    sk, pk = generate_test_keys(MNEMONIC1)
    sk2, pk2 = generate_test_keys(MNEMONIC2)
    sk3, pk3 = generate_test_keys(MNEMONIC3)

    output_values = [10, 20]
    total_minted = sum(output_values)

    lineage = Program.to([bytes(pk)])
    lineage_hash = lineage.get_tree_hash()
    spend_bundle = issue_hc_from_farmed_coin(
        mod_code, 1, lineage_hash, total_minted
    )

    puzzles_for_db = [hc_puzzle_for_lineage_program(mod_code, lineage)]
    add_puzzles_to_puzzle_preimage_db(puzzles_for_db)
    #spend_bundle.debug()

    # we know what the lineage should be
    # in the actual application wallets would be notified
    # when they are added to the lineage of a coin
    spendable_hc_list = []
    for coin_spend in spend_bundle.coin_spends:
        for coin in coin_spend.additions():
            spendable_hc_list.append(
                SpendableHC(
                    coin,
                    Program.to([bytes(pk)])
                )
            )

    receivers = [[pk2, pk3]]
    amounts = [output_values]
    outputs = Program.to( list(zip(receivers[0], amounts[0])) )

    msg = (
        outputs.get_tree_hash()
        + spendable_hc_list[0].coin.get_hash()
        + bytes.fromhex("0303030303030303030303030303030303030303030303030303030303030303")
    )

    signature = AugSchemeMPL.sign(sk, msg)

    spend_bundle = spend_bundle_for_spendable_hcs(
        mod_code,
        pk,
        spendable_hc_list,
        receivers,
        amounts,
        [signature]
    )

    spend_bundle.debug()

    output_puzzle_hashes = []
    for coin_spend in spend_bundle.coin_spends:

        puzzle_reveal = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
        solution = Program.from_bytes(bytes(coin_spend.solution))
        error, conditions, cost = conditions_dict_for_solution(
            puzzle_reveal, solution, INFINITE_COST
        )
        for _ in conditions.get(ConditionOpcode.CREATE_COIN, []):
            output_puzzle_hashes.append(_.vars[0])

    print(conditions)

    lineage1 = Program.to([bytes(pk), bytes(pk2)])
    lineage2 = Program.to([bytes(pk), bytes(pk3)])
    correct_puzzle_hash1 = bytes(hc_puzzle_hash_for_lineage_hash(mod_code, lineage1.get_tree_hash()))
    correct_puzzle_hash2 = bytes(hc_puzzle_hash_for_lineage_hash(mod_code, lineage2.get_tree_hash()))

    # order doesn't change in this case
    assert output_puzzle_hashes[0] == correct_puzzle_hash1
    assert output_puzzle_hashes[1] == correct_puzzle_hash2


def main():
    test_spend_to_two(HC_MOD)


if __name__ == "__main__":
    main()
