
#
import asyncio
import logging
from typing import List, Optional, Set, Tuple

import aiosqlite
from blspy import G1Element

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32
# from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.util.wallet_types import WalletType

log = logging.getLogger(__name__)


class HCWalletPuzzleStore:

    db_connection: aiosqlite.Connection
    lock: asyncio.Lock
    cache_size: uint32
    all_puzzle_hashes: Set[bytes32]
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size

        self.db_wrapper = db_wrapper
        self.db_connection = self.db_wrapper.db
        await self.db_connection.execute("pragma journal_mode=wal")
        await self.db_connection.execute("pragma synchronous=2")
        await self.db_connection.execute(
            (
                "CREATE TABLE IF NOT EXISTS lineage_paths("
                "lineage_index int,"
                " pubkeys_concat text,"
                " puzzle_hash text PRIMARY_KEY,"
                " wallet_type int,"
                " wallet_id int,"
                " used tinyint)"
            )
        )
        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS derivation_index_index on derivation_paths(derivation_index)"
        )

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS ph on derivation_paths(puzzle_hash)")

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS pubkey on derivation_paths(pubkey)")

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS wallet_type on derivation_paths(wallet_type)")

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS wallet_id on derivation_paths(wallet_id)")

        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS used on derivation_paths(wallet_type)")

        await self.db_connection.commit()
        # Lock
        self.lock = asyncio.Lock()  # external
        await self._init_cache()
        return self
