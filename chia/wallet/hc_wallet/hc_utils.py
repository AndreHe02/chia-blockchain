import dataclasses
from typing import List, Optional, Tuple

from blspy import G1Element, G2Element, AugSchemeMPL

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.wallet.cc_wallet.cc_utils import subtotals_for_deltas
from chia.wallet.puzzles.hc_loader import HC_MOD

NULL_SIGNATURE = G2Element()


@dataclasses.dataclass
class SpendableHC:
    coin: Coin
    lineage: List[G1Element]


def hc_puzzle_for_lineage_program(mod_code, lineage: Program) -> Program:
    return mod_code.curry(mod_code.get_tree_hash(), lineage)


def hc_puzzle_for_lineage(mod_code, lineage: List[G1Element]) -> Program:
    lineage_program = Program.to(lineage)
    return hc_puzzle_for_lineage_program(mod_code, lineage_program)


def hc_puzzle_hash_for_lineage(mod_code, lineage: List[G1Element]) -> Program:
    return hc_puzzle_hash_for_lineage_hash(mod_code, Program.to(lineage).get_tree_hash())


def hc_puzzle_hash_for_lineage_hash(mod_code, lineage_hash) -> bytes32:
    return mod_code.curry(mod_code.get_tree_hash(), lineage_hash).get_tree_hash(lineage_hash)


# to verify coin is an HC we check that its puzzle hash
# is equal to an HC hash with the same ancestry curried in (no cross spending)

def bundle_for_spendable_hc_list(spendable_hc: SpendableHC):
    coin = spendable_hc.coin.as_list()  # (spendable_hc.coin.as_list(), spendable_hc.ancestry_pks)
    return Program.to(coin)


def unsigned_coin_spends(
        mod_code: Program,
        spender: G1Element,
        spendable_hc_list: List[SpendableHC],
        receivers: List[List[List[G1Element]]],
        amounts: List[List[uint64]],
        extra_signers: Optional[List[G1Element]] = []
):
    N = len(spendable_hc_list)

    if len(receivers) != N or len(amounts) != N:
        raise ValueError("spendable_hc_list and receivers or amounts are different lengths")

    input_coins = [_.coin for _ in spendable_hc_list]

    output_amounts = [sum(coin_output_amounts) for coin_output_amounts in amounts]

    coin_spends = []

    deltas = [input_coins[_].amount - output_amounts[_] for _ in range(N)]
    subtotals = subtotals_for_deltas(deltas)

    # this is also enforced in the smart contract
    if sum(deltas) != 0:
        raise ValueError("input and output amounts don't match")

    bundles = [bundle_for_spendable_hc_list(_) for _ in spendable_hc_list]

    for index in range(N):
        hc_spend_info = spendable_hc_list[index]

        puzzle_reveal = hc_puzzle_for_lineage(mod_code, hc_spend_info.lineage)

        prev_index = (index - 1) % N
        next_index = (index + 1) % N
        prev_bundle = bundles[prev_index]
        my_bundle = bundles[index]
        next_bundle = bundles[next_index]

        coin_receivers = receivers[index]
        coin_output_amounts = amounts[index]
        outputs = list(zip(coin_receivers, coin_output_amounts))

        solution = [
            spender,
            outputs,
            extra_signers,
            prev_bundle,
            my_bundle,
            next_bundle,
            subtotals[index],
        ]

        coin_spend = CoinSpend(input_coins[index], puzzle_reveal, Program.to(solution))
        coin_spends.append(coin_spend)
    return coin_spends


def is_hc_mod(inner_f: Program):
    return inner_f == HC_MOD


def uncurry_hc(puzzle: Program) -> Optional[Tuple[Program, Program]]:
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    if not is_hc_mod(inner_f):
        return None

    mod_hash, lineage = list(args.as_iter())
    return mod_hash, lineage

