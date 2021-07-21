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
    spend_bundle_for_spendable_hcs, SpendableHC, signed_spend_bundle,
)
from chia.wallet.util.debug_spend_bundle import disassemble

CONDITIONS = dict((k, bytes(v)[0]) for k, v in ConditionOpcode.__members__.items())  # pylint: disable=E1101

NULL_SIGNATURE = G2Element()

ANYONE_CAN_SPEND_PUZZLE = Program.to(1)  # simply return the conditions

PUZZLE_TABLE: Dict[bytes32, Program] = dict((_.get_tree_hash(), _) for _ in [ANYONE_CAN_SPEND_PUZZLE])

TEST_GENESIS_CHALLENGE = bytes.fromhex("0303030303030303030303030303030303030303030303030303030303030303")


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


def assert_output_lineages(coin_spend: CoinSpend, lineages: List[List[G1Element]]):
    puzzle_reveal = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
    solution = Program.from_bytes(bytes(coin_spend.solution))
    error, conditions, cost = conditions_dict_for_solution(
        puzzle_reveal, solution, INFINITE_COST
    )
    for _, lineage in zip(conditions.get(ConditionOpcode.CREATE_COIN, []), lineages):
        output_puzzle_hash = _.vars[0]
        lineage_puzzle = Program.to([bytes(_) for _ in lineage])
        correct_puzzle_hash = bytes(hc_puzzle_hash_for_lineage_hash(HC_MOD, lineage_puzzle.get_tree_hash()))
        assert output_puzzle_hash == correct_puzzle_hash


def test_spend_to_two():
    mod_code = HC_MOD
    sk, pk = generate_test_keys(MNEMONIC1)
    sk2, pk2 = generate_test_keys(MNEMONIC2)
    sk3, pk3 = generate_test_keys(MNEMONIC3)

    total_minted = 30

    lineage = Program.to([pk])
    lineage_hash = lineage.get_tree_hash()
    spend_bundle = issue_hc_from_farmed_coin(
        mod_code, 1, lineage_hash, total_minted
    )

    # we know what the lineage should be
    # in the actual application wallets would be notified
    # when they are added to the lineage of a coin
    coin = spend_bundle.coin_spends[0].additions()[0]
    spendable_hc_list = [SpendableHC(coin, [pk])]
    receivers = [[[pk, pk2], [pk, pk3]]]
    amounts = [[10, 20]]
    spend_bundle = signed_spend_bundle(
        mod_code, pk, sk, TEST_GENESIS_CHALLENGE, spendable_hc_list, receivers, amounts
    )
    spend_bundle.debug()
    assert_output_lineages(spend_bundle.coin_spends[0], [[pk, pk2], [pk, pk3]])


def test_secondhand_spend():
    mod_code = HC_MOD
    sk, pk = generate_test_keys(MNEMONIC1)
    sk2, pk2 = generate_test_keys(MNEMONIC2)
    sk3, pk3 = generate_test_keys(MNEMONIC3)

    total_minted = 30

    lineage = Program.to([bytes(pk)])
    lineage_hash = lineage.get_tree_hash()
    spend_bundle = issue_hc_from_farmed_coin(
        mod_code, 1, lineage_hash, total_minted
    )

    coin = spend_bundle.coin_spends[0].additions()[0]
    spendable_hc_list = [SpendableHC(coin, [pk])]

    receivers = [[[pk, pk2], [pk, pk3]]]
    amounts = [[10, 20]]
    spend_bundle = signed_spend_bundle(
        mod_code, pk, sk, TEST_GENESIS_CHALLENGE, spendable_hc_list, receivers, amounts
    )
    spend_bundle.debug()
    assert_output_lineages(spend_bundle.coin_spends[0], [[pk, pk2], [pk, pk3]])

    coin = spend_bundle.coin_spends[0].additions()[0]
    spendable_hc_list = [SpendableHC(coin, [pk, pk2])]

    receivers = [[[pk2, pk3]]]
    amounts = [[10]]
    spend_bundle = signed_spend_bundle(
        mod_code, pk2, sk2, TEST_GENESIS_CHALLENGE, spendable_hc_list, receivers, amounts
    )
    spend_bundle.debug()

    coin_spend = spend_bundle.coin_spends[0]
    assert_output_lineages(coin_spend, [[pk, pk2, pk3]])


def test_genesis_clawback():
    mod_code = HC_MOD
    sk, pk = generate_test_keys(MNEMONIC1)
    sk2, pk2 = generate_test_keys(MNEMONIC2)
    sk3, pk3 = generate_test_keys(MNEMONIC3)

    total_minted = 30

    lineage = Program.to([bytes(pk)])
    lineage_hash = lineage.get_tree_hash()
    spend_bundle = issue_hc_from_farmed_coin(
        mod_code, 1, lineage_hash, total_minted
    )

    coin = spend_bundle.coin_spends[0].additions()[0]
    spendable_hc_list = [SpendableHC(coin, [pk])]

    receivers = [[[pk, pk2], [pk, pk3]]]
    amounts = [[10, 20]]
    spend_bundle = signed_spend_bundle(
        mod_code, pk, sk, TEST_GENESIS_CHALLENGE, spendable_hc_list, receivers, amounts
    )
    spend_bundle.debug()
    assert_output_lineages(spend_bundle.coin_spends[0], [[pk, pk2], [pk, pk3]])

    coin = spend_bundle.coin_spends[0].additions()[0]
    spendable_hc_list = [SpendableHC(coin, [pk, pk2])]
    receivers = [[[pk2, pk3]]]
    amounts = [[10]]
    spend_bundle = signed_spend_bundle(
        mod_code, pk2, sk2, TEST_GENESIS_CHALLENGE, spendable_hc_list, receivers, amounts
    )
    spend_bundle.debug()

    coin_spend = spend_bundle.coin_spends[0]
    assert_output_lineages(coin_spend, [[pk, pk2, pk3]])

    coin = spend_bundle.coin_spends[0].additions()[0]
    spendable_hc_list = [SpendableHC(coin, [pk, pk2, pk3])]
    receivers = [[[pk]]]
    amounts = [[10]]
    spend_bundle = signed_spend_bundle(
        mod_code, pk, sk, TEST_GENESIS_CHALLENGE, spendable_hc_list, receivers, amounts
    )
    spend_bundle.debug()

    coin_spend = spend_bundle.coin_spends[0]
    assert_output_lineages(coin_spend, [[pk]])


def test_secondhand_clawback():
    mod_code = HC_MOD
    sk, pk = generate_test_keys(MNEMONIC1)
    sk2, pk2 = generate_test_keys(MNEMONIC2)
    sk3, pk3 = generate_test_keys(MNEMONIC3)

    total_minted = 30

    lineage = Program.to([bytes(pk)])
    lineage_hash = lineage.get_tree_hash()
    spend_bundle = issue_hc_from_farmed_coin(
        mod_code, 1, lineage_hash, total_minted
    )

    coin = spend_bundle.coin_spends[0].additions()[0]
    spendable_hc_list = [SpendableHC(coin, [pk])]

    receivers = [[[pk, pk2], [pk, pk3]]]
    amounts = [[10, 20]]
    spend_bundle = signed_spend_bundle(
        mod_code, pk, sk, TEST_GENESIS_CHALLENGE, spendable_hc_list, receivers, amounts
    )
    spend_bundle.debug()
    assert_output_lineages(spend_bundle.coin_spends[0], [[pk, pk2], [pk, pk3]])

    coin = spend_bundle.coin_spends[0].additions()[0]
    spendable_hc_list = [SpendableHC(coin, [pk, pk2])]
    receivers = [[[pk2, pk3]]]
    amounts = [[10]]
    spend_bundle = signed_spend_bundle(
        mod_code, pk2, sk2, TEST_GENESIS_CHALLENGE, spendable_hc_list, receivers, amounts
    )
    spend_bundle.debug()

    coin_spend = spend_bundle.coin_spends[0]
    assert_output_lineages(coin_spend, [[pk, pk2, pk3]])

    coin = spend_bundle.coin_spends[0].additions()[0]
    spendable_hc_list = [SpendableHC(coin, [pk, pk2, pk3])]
    receivers = [[[pk2]]]
    amounts = [[10]]
    spend_bundle = signed_spend_bundle(
        mod_code, pk2, sk2, TEST_GENESIS_CHALLENGE, spendable_hc_list, receivers, amounts
    )
    spend_bundle.debug()

    coin_spend = spend_bundle.coin_spends[0]
    assert_output_lineages(coin_spend, [[pk, pk2]])


def main():
    print(HC_MOD)
    test_spend_to_two()
    test_secondhand_spend()
    test_genesis_clawback()
    test_secondhand_clawback()


if __name__ == "__main__":
    main()
