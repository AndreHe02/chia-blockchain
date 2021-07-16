import dataclasses

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.hc_loader import HC_MOD

@dataclasses.dataclass
class SpendableHC:
    coin: Coin
    ancestry_pks: Program


def hc_puzzle_for_ancestry(mod_code, ancestry) -> Program:
    return mod_code.curry(ancestry)


#we also need this function in chialisp
def hc_puzzle_hash_for_ancestry_hash(mod_code, ancestry) -> bytes32:
    ancestry_hash = ancestry.get_tree_hash()
    return mod_code.curry(ancestry_hash).get_tree_hash(ancestry_hash)


# to verify coin is an HC we check that its puzzle hash
# is equal to an HC hash with the same ancestry curried in (no cross spending)

def bundle_for_spendable_hc_list(spendable_hc: SpendableHC):
    pair = spendable_hc.coin.as_list() #(spendable_hc.coin.as_list(), spendable_hc.ancestry_pks)
    return Program.to(pair)

