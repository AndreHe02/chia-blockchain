import asyncio
from collections import defaultdict
from typing import List

import pytest

from chia.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.hc_wallet.hc_utils import hc_puzzle_hash_for_lineage_hash, hc_puzzle_for_lineage, \
    hc_puzzle_hash_for_lineage
from chia.wallet.hc_wallet.hc_wallet import HCWallet
from chia.wallet.puzzles.hc_loader import HC_MOD
from chia.wallet.transaction_record import TransactionRecord
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32):
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


def make_balance_by_lineage(lineages, amounts):
    balance = {}
    for lineage, a in zip(lineages, amounts):
        balance[hc_puzzle_hash_for_lineage(HC_MOD, lineage)] = a
    return balance


class TestHCWallet:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 3, {}):
            yield _

    @pytest.mark.asyncio
    async def test_genesis(self, two_wallet_nodes):
        num_blocks = 3
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        # GENESIS
        hc_wallet: HCWallet = await HCWallet.create(wallet_node.wallet_state_manager, wallet)
        await hc_wallet.create_new_hc(uint64(100))

        # PUSH GENESIS TRANSACTION
        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        lineage_hash = Program.to([bytes(hc_wallet.public_key)]).get_tree_hash()
        puzzle_hash = hc_puzzle_hash_for_lineage_hash(HC_MOD, lineage_hash)
        correct_balance = {puzzle_hash: uint64(100)}

        await time_out_assert(15, hc_wallet.get_unconfirmed_balance, correct_balance)

        # WAIT FOR CONFIRMATION
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, hc_wallet.get_confirmed_balance, correct_balance)
        await time_out_assert(15, hc_wallet.get_unconfirmed_balance, correct_balance)

    @pytest.mark.asyncio
    async def test_vertical_spend(self, two_wallet_nodes):
        num_blocks = 3
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        # GENESIS
        hc_wallet: HCWallet = await HCWallet.create(wallet_node.wallet_state_manager, wallet)
        await hc_wallet.create_new_hc(uint64(100))

        # PUSH GENESIS TRANSACTION
        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        lineage_hash = Program.to([bytes(hc_wallet.public_key)]).get_tree_hash()
        puzzle_hash = hc_puzzle_hash_for_lineage_hash(HC_MOD, lineage_hash)
        correct_balance = {puzzle_hash: uint64(100)}

        await time_out_assert(15, hc_wallet.get_unconfirmed_balance, correct_balance)

        # WAIT FOR CONFIRMATION
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, hc_wallet.get_confirmed_balance, correct_balance)
        await time_out_assert(15, hc_wallet.get_unconfirmed_balance, correct_balance)

        hc_wallet_2: HCWallet = await HCWallet.create(wallet_node_2.wallet_state_manager, wallet2)
        pk = hc_wallet.public_key
        pk2 = hc_wallet_2.public_key

        await hc_wallet_2.register_lineage([pk, pk2])
        await hc_wallet.register_lineage([pk, pk2])

        tx_record = await hc_wallet.generate_signed_transactions(
            [50], [pk2], [False], hc_puzzle_hash_for_lineage(HC_MOD, [pk])
        )
        await wallet.wallet_state_manager.add_pending_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        sender_ph = hc_puzzle_hash_for_lineage(HC_MOD, [pk])
        receiver_ph = hc_puzzle_hash_for_lineage(HC_MOD, [pk, pk2])
        wallet1_balance = {sender_ph: 50, receiver_ph: 50}
        wallet2_balance = {receiver_ph: 50}

        await time_out_assert(15, hc_wallet.get_confirmed_balance, wallet1_balance)
        await time_out_assert(15, hc_wallet_2.get_confirmed_balance, wallet2_balance)

    @pytest.mark.asyncio
    async def test_horizontal_spend(self, two_wallet_nodes):
        num_blocks = 3
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        # GENESIS
        hc_wallet: HCWallet = await HCWallet.create(wallet_node.wallet_state_manager, wallet)
        await hc_wallet.create_new_hc(uint64(100))

        # PUSH GENESIS TRANSACTION
        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        lineage_hash = Program.to([hc_wallet.public_key]).get_tree_hash()
        puzzle_hash = hc_puzzle_hash_for_lineage_hash(HC_MOD, lineage_hash)
        correct_balance = {puzzle_hash: uint64(100)}

        # WAIT FOR CONFIRMATION
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, hc_wallet.get_confirmed_balance, correct_balance)
        await time_out_assert(15, hc_wallet.get_unconfirmed_balance, correct_balance)

        hc_wallet_2: HCWallet = await HCWallet.create(wallet_node_2.wallet_state_manager, wallet2)
        pk = hc_wallet.public_key
        pk2 = hc_wallet_2.public_key

        await hc_wallet_2.register_lineage([pk2])

        tx_record = await hc_wallet.generate_signed_transactions(
            [50], [pk2], [True], hc_puzzle_hash_for_lineage(HC_MOD, [pk])
        )
        await wallet.wallet_state_manager.add_pending_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        sender_ph = hc_puzzle_hash_for_lineage(HC_MOD, [pk])
        receiver_ph = hc_puzzle_hash_for_lineage(HC_MOD, [pk2])
        wallet1_balance = {sender_ph: 50}
        wallet2_balance = {receiver_ph: 50}

        await time_out_assert(15, hc_wallet.get_confirmed_balance, wallet1_balance)
        await time_out_assert(15, hc_wallet_2.get_confirmed_balance, wallet2_balance)

    @pytest.mark.asyncio
    async def test_many_spends(self, three_wallet_nodes):
        num_blocks = 3
        full_nodes, wallets = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet_node_3, server_4 = wallets[2]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet
        wallet3 = wallet_node_3.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_4.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        ''' GENESIS IN WALLET 1'''
        hc_wallet: HCWallet = await HCWallet.create(wallet_node.wallet_state_manager, wallet)
        await hc_wallet.create_new_hc(uint64(100))

        pk = hc_wallet.public_key

        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, hc_wallet.get_confirmed_balance, make_balance_by_lineage([[pk]], [100]))

        ''' VERTICAL SPEND TO WALLET 2 '''
        hc_wallet_2: HCWallet = await HCWallet.create(wallet_node_2.wallet_state_manager, wallet2)
        pk2 = hc_wallet_2.public_key

        await hc_wallet.register_lineage([pk, pk2])
        await hc_wallet_2.register_lineage([pk, pk2])

        tx_record = await hc_wallet.generate_signed_transactions(
            [50], [pk2], [False], hc_puzzle_hash_for_lineage(HC_MOD, [pk])
        )
        await wallet.wallet_state_manager.add_pending_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, hc_wallet.get_confirmed_balance,
                              make_balance_by_lineage([[pk], [pk, pk2]], [50, 50]))
        await time_out_assert(15, hc_wallet_2.get_confirmed_balance,
                              make_balance_by_lineage([[pk, pk2]], [50, 50]))

        ''' VERTICAL SPEND TO WALLET 3 '''
        hc_wallet_3: HCWallet = await HCWallet.create(wallet_node_3.wallet_state_manager, wallet3)
        pk3 = hc_wallet_3.public_key

        await hc_wallet.register_lineage([pk, pk2, pk3])
        await hc_wallet_2.register_lineage([pk, pk2, pk3])
        await hc_wallet_3.register_lineage([pk, pk2, pk3])

        tx_record = await hc_wallet_2.generate_signed_transactions(
            [20], [pk3], [False], hc_puzzle_hash_for_lineage(HC_MOD, [pk, pk2])
        )
        await wallet2.wallet_state_manager.add_pending_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, hc_wallet.get_confirmed_balance,
                              make_balance_by_lineage(
                                  [[pk], [pk, pk2], [pk, pk2, pk3]],
                                  [50, 30, 20]
                              ))
        await time_out_assert(15, hc_wallet_2.get_confirmed_balance,
                              make_balance_by_lineage(
                                  [[pk, pk2], [pk, pk2, pk3]],
                                  [30, 20]
                              ))
        await time_out_assert(15, hc_wallet_3.get_confirmed_balance,
                              make_balance_by_lineage(
                                  [[pk, pk2, pk3]],
                                  [20]
                              ))

        ''' WALLET 1 CLAWBACK AND HORIZONTAL SPEND TO WALLET 3 '''
        await hc_wallet_3.register_lineage([pk3])

        tx_record = await hc_wallet.generate_signed_transactions(
            [10], [pk3], [True], hc_puzzle_hash_for_lineage(HC_MOD, [pk, pk2, pk3])
        )
        await wallet.wallet_state_manager.add_pending_transaction(tx_record)

        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, hc_wallet.get_confirmed_balance,
                              make_balance_by_lineage(
                                  [[pk], [pk, pk2], [pk, pk2, pk3]],
                                  [50, 30, 10]
                              ))
        await time_out_assert(15, hc_wallet_2.get_confirmed_balance,
                              make_balance_by_lineage(
                                  [[pk, pk2], [pk, pk2, pk3]],
                                  [30, 10]
                              ))
        await time_out_assert(15, hc_wallet_3.get_confirmed_balance,
                              make_balance_by_lineage(
                                  [[pk3], [pk, pk2, pk3]],
                                  [10, 10]
                              ))