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
from chia.wallet.hc_wallet.hc_utils import hc_puzzle_hash_for_lineage_hash
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


class TestHCWallet:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
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

        hc_wallet: HCWallet = await HCWallet.create(wallet_node.wallet_state_manager, wallet)
        await hc_wallet.create_new_hc(uint64(100))

    @pytest.mark.asyncio
    async def test_balance(self, two_wallet_nodes):
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

        hc_wallet: HCWallet = await HCWallet.create(wallet_node.wallet_state_manager, wallet)
        await hc_wallet.create_new_hc(uint64(100))

        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        lineage_hash = Program.to([bytes(hc_wallet.public_key)]).get_tree_hash()
        puzzle_hash = hc_puzzle_hash_for_lineage_hash(HC_MOD, lineage_hash)
        correct_balance = {puzzle_hash: uint64(100)}

        await time_out_assert(15, hc_wallet.get_unconfirmed_balance, correct_balance)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, hc_wallet.get_confirmed_balance, correct_balance)
        await time_out_assert(15, hc_wallet.get_unconfirmed_balance, correct_balance)



