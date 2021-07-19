import dataclasses
from typing import List, Optional

from blspy import G1Element, G2Element, AugSchemeMPL

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.wallet.cc_wallet.cc_utils import subtotals_for_deltas
from chia.wallet.puzzles.hc_loader import HC_MOD
from chia.wallet.puzzles.test_hc import NULL_SIGNATURE


@dataclasses.dataclass
class SpendableHC:
    coin: Coin
    lineage: List[G1Element]


def hc_puzzle_for_lineage_program(mod_code, lineage: Program) -> Program:
    return mod_code.curry(mod_code.get_tree_hash(), lineage)

def hc_puzzle_for_lineage(mod_code, lineage: List[G1Element]) -> Program:
    lineage_program = Program.to([bytes(public_key) for public_key in lineage])
    return hc_puzzle_for_lineage_program(mod_code, lineage_program)

def hc_puzzle_hash_for_lineage_hash(mod_code, lineage_hash) -> bytes32:
    return mod_code.curry(mod_code.get_tree_hash(), lineage_hash).get_tree_hash(lineage_hash)


# to verify coin is an HC we check that its puzzle hash
# is equal to an HC hash with the same ancestry curried in (no cross spending)

def bundle_for_spendable_hc_list(spendable_hc: SpendableHC):
    coin = spendable_hc.coin.as_list() #(spendable_hc.coin.as_list(), spendable_hc.ancestry_pks)
    return Program.to(coin)

def spend_bundle_for_spendable_hcs(
    mod_code: Program,
    spendable_hc_list: List[SpendableHC],
    receivers: List[List[G1Element]],
    amounts: List[List[int]],
    sigs: Optional[List[G2Element]] = [],
) -> SpendBundle:

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

        solution = [
            #construct zip(lineage, amounts) here
            prev_bundle,
            my_bundle,
            next_bundle,
            subtotals[index],
        ]

        coin_spend = CoinSpend(input_coins[index], puzzle_reveal, Program.to(solution))
        coin_spends.append(coin_spend)

    if sigs is None or sigs == []:
        return SpendBundle(coin_spends, NULL_SIGNATURE)
    else:
        return SpendBundle(coin_spends, AugSchemeMPL.aggregate(sigs))