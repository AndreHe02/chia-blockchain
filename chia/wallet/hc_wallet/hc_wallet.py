from __future__ import annotations

import logging
import time
from dataclasses import replace
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Set

from blspy import AugSchemeMPL, G2Element, G1Element

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
from chia.wallet.hc_wallet.hc_utils import hc_puzzle_hash_for_lineage_hash, spend_bundle_for_spendable_hcs, \
    signed_spend_bundle, SpendableHC, hc_puzzle_hash_for_lineage
from chia.wallet.puzzles.genesis_by_coin_id_with_0 import (
    create_genesis_or_zero_coin_checker,
    genesis_coin_id_for_genesis_coin_checker,
    lineage_proof_for_genesis,
)
from chia.wallet.hc_wallet.hc_utils import HC_MOD
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
    standard_wallet: Wallet
    cost_of_single_tx: Optional[int]
    registered_lineages: Dict[bytes32, List[G1Element]]
    public_key: G1Element

    async def create_new_hc(
            self,
            amount: uint64,
    ):

        spend_bundle = await self.generate_new_hierarchical_coin(amount)

        await self.wallet_state_manager.add_new_wallet(self, self.id())

        non_ephemeral_spends: List[Coin] = spend_bundle.not_ephemeral_additions()
        hc_coin = None
        puzzle_store = self.wallet_state_manager.puzzle_store

        for c in non_ephemeral_spends:
            info = await puzzle_store.wallet_info_for_puzzle_hash(c.puzzle_hash)
            if info is None:
                raise ValueError("Internal Error")
            id, wallet_type = info
            if id == self.id():
                hc_coin = c

        if hc_coin is None:
            raise ValueError("Internal Error, unable to generate new hierarchical coin")

        regular_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=hc_coin.puzzle_hash,
            amount=uint64(hc_coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_state_manager.main_wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=token_bytes(),
        )
        hc_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=hc_coin.puzzle_hash,
            amount=uint64(hc_coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(10),
            spend_bundle=None,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=token_bytes(),
        )
        await self.standard_wallet.push_transaction(regular_record)
        await self.standard_wallet.push_transaction(hc_record)
        return self

    @staticmethod
    async def create(
            wallet_state_manager: Any,
            wallet: Wallet
    ):
        self = HCWallet()
        self.cost_of_single_tx = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.public_key = wallet_state_manager.private_key.get_g1()
        self.registered_lineages = {}

        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "HC Wallet", WalletType.HC_WALLET, bytes(self.public_key)
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")

        await self.wallet_state_manager.add_new_wallet(self, self.id())
        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.HC_WALLET)

    def id(self) -> uint32:
        return self.wallet_info.id

    # keep separate balances for coins of different lineages
    # this avoids mixing coins (bleaching lineages)
    # and helps keep track of coins available for clawback
    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None
                                    ) -> Dict[bytes32, uint64]:
        if record_list is None:
            record_list = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.id())

        amounts = {}

        for record in record_list:
            ph = record.coin.puzzle_hash
            if ph not in amounts:
                amounts[ph] = uint64(0)
            amounts[ph] = uint64(amounts[ph] + record.coin.amount)

        # self.log.info(f"Confirmed balance for hc wallet {self.id()} is")
        # for ph in amounts:
        #    self.log.info(f"{amounts[ph]} for lineage with fingerprints \
        #        {[_.get_fingerprint() for _ in self.registered_lineages[ph]]}")
        return amounts

    async def get_unconfirmed_balance(self, unspent_records=None) -> Dict[bytes32, uint128]:
        confirmed = await self.get_confirmed_balance(unspent_records)
        unconfirmed_tx: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
            self.id()
        )

        for record in unconfirmed_tx:
            for coin in record.spend_bundle.additions():
                ph = coin.puzzle_hash
                if ph not in self.registered_lineages:  # this is not a hc
                    continue
                if ph not in confirmed:
                    confirmed[ph] = uint64(0)
                confirmed[ph] += coin.amount
            for coin in record.spend_bundle.removals():
                ph = coin.puzzle_hash
                if ph not in self.registered_lineages:
                    continue
                if ph not in confirmed:
                    confirmed[ph] = uint64(0)
                confirmed[ph] -= coin.amount
        return {key: uint128(confirmed[key]) for key in confirmed}

    async def generate_new_hierarchical_coin(self, amount: uint64) -> SpendBundle:
        coins = await self.standard_wallet.select_coins(amount)

        origin = coins.copy().pop()
        origin_id = origin.name()

        genesis_lineage = [self.public_key]
        lineage_puzzle = Program.to([bytes(_) for _ in genesis_lineage])
        minted_hc_puzzle_hash = hc_puzzle_hash_for_lineage_hash(HC_MOD, lineage_puzzle.get_tree_hash())

        await self.register_lineage(genesis_lineage)

        tx_record: TransactionRecord = await self.standard_wallet.generate_signed_transaction(
            amount, minted_hc_puzzle_hash, uint64(0), origin_id, coins
        )
        assert tx_record.spend_bundle is not None
        return tx_record.spend_bundle

    async def register_lineage_(self, hc_puzzle_hash: bytes32, lineage: List[G1Element]):
        last: Optional[uint32] = await self.wallet_state_manager.puzzle_store.get_last_derivation_path_for_wallet(
            self.id())
        if last is not None:
            index = last + 1
        else:
            index = 0

        derivation_record = DerivationRecord(
            uint32(index),
            hc_puzzle_hash,
            self.public_key,
            WalletType.HC_WALLET,
            uint32(self.id()),
        )
        await self.wallet_state_manager.puzzle_store.add_derivation_paths([derivation_record], in_transaction=False)

        self.registered_lineages[hc_puzzle_hash] = lineage

    async def register_lineage(self, lineage: List[G1Element]):
        await self.register_lineage_(
            hc_puzzle_hash_for_lineage(HC_MOD, lineage),
            lineage
        )

    async def get_max_send_amount_for_ph(self, puzzle_hash, records=None):
        spendable: List[WalletCoinRecord] = list(
            await self.get_spendable_coins_for_ph(puzzle_hash, records)
        )
        if len(spendable) == 0:
            return 0
        spendable.sort(reverse=True, key=lambda record: record.coin.amount)
        if self.cost_of_single_tx is None:
            coin = spendable[0].coin
            tx = await self.generate_signed_transactions(
                # this should be a fake spend to self
                [coin.amount], [self.public_key], [False], puzzle_hash, coins={coin}, ignore_max_send_amount=True
            )
            program: BlockGenerator = simple_solution_generator(tx.spend_bundle)
            # npc contains names of the coins removed, puzzle_hashes and their spend conditions
            result: NPCResult = get_name_puzzle_conditions(
                program,
                self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
                cost_per_byte=self.wallet_state_manager.constants.COST_PER_BYTE,
                safe_mode=True,
            )
            cost_result: uint64 = calculate_cost_of_program(
                program.program, result, self.wallet_state_manager.constants.COST_PER_BYTE
            )
            self.cost_of_single_tx = cost_result
            self.log.info(f"Cost of a single tx for standard wallet: {self.cost_of_single_tx}")

        max_cost = self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM / 2  # avoid full block TXs
        current_cost = 0
        total_amount = 0
        total_coin_count = 0

        for record in spendable:
            current_cost += self.cost_of_single_tx
            total_amount += record.coin.amount
            total_coin_count += 1
            if current_cost + self.cost_of_single_tx > max_cost:
                break

        return total_amount

    async def get_hc_spendable_coins(self, records=None) -> List[WalletCoinRecord]:
        result: List[WalletCoinRecord] = []

        record_list: Set[WalletCoinRecord] = await self.wallet_state_manager.get_spendable_coins_for_wallet(
            self.id(), records
        )

        for record in record_list:
            if record.coin.puzzle_hash in self.registered_lineages:
                result.append(record)

        return result

    async def get_spendable_coins_for_ph(self, puzzle_hash: bytes32, records=None) -> List[WalletCoinRecord]:
        all_spendable = await self.get_hc_spendable_coins(records)
        return [r for r in all_spendable if r.coin.puzzle_hash == puzzle_hash]

    async def get_spendable_balance_for_ph(self, puzzle_hash: bytes32, records=None) -> uint64:
        coins = await self.get_spendable_coins_for_ph(puzzle_hash)
        amount = 0
        for record in coins:
            amount += record.coin.amount
        return uint64(amount)

    async def select_coins_for_ph(self, amount: uint64, puzzle_hash: bytes32):
        spendable_amts = await self.get_confirmed_balance()

        if puzzle_hash not in spendable_amts:
            raise ValueError("no spendable balance for this puzzle hash")
        spendable_am = spendable_amts[puzzle_hash]
        if amount > spendable_am:
            error_msg = f"Can't select amount higher than our spendable balance {amount}, spendable {spendable_am}"
            raise ValueError(error_msg)

        spendable = await self.get_spendable_coins_for_ph(puzzle_hash)

        sum = 0
        used_coins: Set = set()

        spendable.sort(key=lambda r: r.confirmed_block_height)

        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.id()
        )
        for coinrecord in spendable:
            if sum >= amount and len(used_coins) > 0:
                break
            if coinrecord.coin.name() in unconfirmed_removals:
                continue
            sum += coinrecord.coin.amount
            used_coins.add(coinrecord.coin)

        if sum < amount:
            raise ValueError(
                "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
            )

        return used_coins

    async def generate_signed_transactions(
            self,
            amounts: List[uint64],
            receivers: List[G1Element],
            from_puzzle_hash: bytes32,
            fee: uint64 = uint64(0),
            coins: Set[Coin] = None,
            ignore_max_send_amount: bool = False,
            extra_signatures: List[G2Element] = []
            # admin might just want to sign all relevant coins
    ) -> TransactionRecord:

        if from_puzzle_hash not in self.registered_lineages:
            raise ValueError(f"Unrecognized puzzle hash {from_puzzle_hash}")

        outgoing_amount = uint64(sum(amounts))
        total_outgoing = outgoing_amount #+ fee

        # change this to use XCH as fee later
        if not ignore_max_send_amount:
            max_send = await self.get_max_send_amount_for_ph(from_puzzle_hash)
            if total_outgoing > max_send:
                raise ValueError(f"Can't send more than {max_send} in a single transaction")

        if coins is None:
            selected_coins: Set[Coin] = await self.select_coins_for_ph(uint64(total_outgoing), from_puzzle_hash)
        else:
            selected_coins = coins

        total_amount = sum([x.amount for x in selected_coins])
        change = total_amount - total_outgoing

        # this is to make a change coin with the same lineage as its parent
        spender_index = 0
        spent_coin_lineage = self.registered_lineages[from_puzzle_hash]
        for i in range(len(spent_coin_lineage)):
            if spent_coin_lineage[i] == self.public_key:
                spender_index = i
                break
        change_coin_receiver = spent_coin_lineage[spender_index:]
        receivers.append(change_coin_receiver)
        amounts.append(change)

        # have the first coin produce the outputs
        receivers_bundle: List[List[List[G1Element]]] = [[[self.public_key]] for coin in selected_coins]
        amounts_bundle: List[List[uint64]] = [[coin.amount] for coin in selected_coins]
        receivers_bundle[0] = receivers
        amounts_bundle[0] = amounts

        spendable_hc_list = []
        for coin in selected_coins:
            spendable_hc_list.append(
                SpendableHC(
                    coin,
                    self.registered_lineages[coin.puzzle_hash])
            )

        spend_bundle = signed_spend_bundle(
            HC_MOD,
            self.public_key,
            self.wallet_state_manager.private_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            spendable_hc_list,
            receivers_bundle,
            amounts_bundle,
            extra_signatures
        )

        # take the first one, mimicking cc_wallet
        to_puzzle_hash = spend_bundle.additions()[0].puzzle_hash

        return TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=to_puzzle_hash,
            amount=uint64(outgoing_amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
        )

    def puzzle_for_pk(self, pubkey) -> Program:
        # this doesn't actually do anything
        return HC_MOD
