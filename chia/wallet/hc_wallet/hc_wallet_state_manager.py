from blspy import G1Element

from chia.wallet.wallet_state_manager import WalletStateManager
import warnings

class HCWalletStateManager:

    """
    Version of WalletStateManager where we use a fixed public key
    Repeating puzzle hashes are fine because the HC contact does not
    contain hidden spends.

    Maybe not needed. just have HCWallet always use index 0
    """

    @staticmethod
    async def create(
        wallet_state_manager: WalletStateManager
    ):
        self = wallet_state_manager
        # TODO override some functions

        return self

    """
    get_derivation_index: remove
    get_public_key: modify
    load_wallets: modify
    get_keys: remove
    create_more_puzzle_hashes: 
    """