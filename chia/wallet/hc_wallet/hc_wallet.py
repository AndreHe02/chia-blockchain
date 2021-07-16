from __future__ import annotations

import logging
import time
from dataclasses import replace
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Set

from blspy import AugSchemeMPL, G2Element

from chia.consensus.cost_calculator import calculate_cost_of_program, NPCResult
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.protocols.wallet_protocol import PuzzleSolutionResponse
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.json_util import dict_to_json_str
from chia.wallet.block_record import HeaderBlockRecord
from chia.wallet.cc_wallet.cc_info import CCInfo
from chia.wallet.cc_wallet.cc_utils import (
    CC_MOD,
    SpendableCC,
    cc_puzzle_for_inner_puzzle,
    cc_puzzle_hash_for_inner_puzzle_hash,
    get_lineage_proof_from_coin_and_puz,
    spend_bundle_for_spendable_ccs,
    uncurry_cc,
)
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.puzzles.genesis_by_coin_id_with_0 import (
    create_genesis_or_zero_coin_checker,
    genesis_coin_id_for_genesis_coin_checker,
    lineage_proof_for_genesis,
)
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo


class HCWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    hc_coin_record: WalletCoinRecord

    # don't need lineage / genesis proof, enforce in chialisp
    #hc_info: HCInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[bytes]
    base_inner_puzzle_hash: Optional[bytes32]
    cost_of_single_tx: Optional[int]

    @staticmethod
    async def create_new_hc(
        wallet_state_manager: Any,
        wallet: Wallet,
        amount: uint64,
    ):
        self = HCWallet()
