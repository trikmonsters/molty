"""
ERC-8004 Identity Registry on-chain calls.
register() from Owner EOA → returns tokenId → POST /api/identity.
Uses PoA-enabled Web3 provider.

v1.5.2+fix: Gas is DELEGATED via Molty Royale relay endpoint (/relay/identity).
Flow:
  1. Build + sign EIP-1559 tx from Owner EOA (do NOT send to node directly)
  2. POST signed raw tx to /relay/identity — server adds FeePayer signature
  3. Server submits FeeDelegatedDynamicFeeTx (type 0x07) to CROSS node
  4. Poll tx receipt via txHash returned by relay endpoint
"""
import asyncio
from web3 import Web3
from eth_account import Account
from bot.config import IDENTITY_REGISTRY, CROSS_CHAIN_ID
from bot.web3.contracts import IDENTITY_ABI
from bot.web3.provider import get_w3
from bot.utils.logger import get_logger

log = get_logger(__name__)


def build_signed_register_tx(owner_private_key: str) -> str | None:
    """
    Build and sign the ERC-8004 register() tx from Owner EOA.
    Returns hex-encoded signed raw tx, or None on failure.
    Does NOT send to node — relay endpoint handles submission.
    """
    acct = Account.from_key(owner_private_key)
    try:
        w3 = get_w3()
        registry = w3.eth.contract(
            address=Web3.to_checksum_address(IDENTITY_REGISTRY),
            abi=IDENTITY_ABI,
        )

        # EIP-1559 tx fields — set explicit fee values so Web3.py doesn't
        # auto-query node gasPrice (which would fail with balance=0).
        # Gas will be paid by Molty Royale FeePayer via relay.
        nonce = w3.eth.get_transaction_count(acct.address)
        
        try:
            # Try to get base fee from latest block for accurate maxFeePerGas
            latest = w3.eth.get_block("latest")
            base_fee = latest.get("baseFeePerGas", 1_000_000_000)  # fallback 1 gwei
        except Exception:
            base_fee = 1_000_000_000  # 1 gwei fallback

        max_priority_fee = 1_000_000_000   # 1 gwei tip
        max_fee = base_fee + max_priority_fee

        tx = registry.functions.register().build_transaction({
            "from": acct.address,
            "nonce": nonce,
            "gas": 300_000,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": max_priority_fee,
            "chainId": CROSS_CHAIN_ID,
            "type": 2,  # EIP-1559
        })

        signed = w3.eth.account.sign_transaction(tx, owner_private_key)
        raw_hex = "0x" + signed.raw_transaction.hex()
        log.info(
            "Signed register() tx: from=%s nonce=%d gas=300000",
            acct.address[:12] + "...", nonce
        )
        return raw_hex

    except Exception as e:
        log.error("Failed to build/sign register() tx: %s", e)
        return None


async def wait_for_relay_receipt(tx_hash: str, timeout: int = 90) -> bool:
    """
    Poll CROSS node for tx receipt until confirmed or timeout.
    Returns True if tx succeeded (status=1).
    """
    w3 = get_w3()
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                if receipt.status == 1:
                    log.info("✅ Relay tx confirmed: %s", tx_hash[:20] + "...")
                    return True
                else:
                    log.error("Relay tx failed on-chain: %s", tx_hash)
                    return False
        except Exception:
            pass
        await asyncio.sleep(3)
    log.warning("Relay tx receipt timeout after %ds: %s", timeout, tx_hash[:20] + "...")
    return False


async def extract_token_id_from_tx(tx_hash: str) -> int | None:
    """
    Read ERC-721 Transfer event logs to extract minted tokenId.
    Returns tokenId or None.
    """
    try:
        w3 = get_w3()
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if not receipt:
            return None
        for event_log in receipt.logs:
            if len(event_log.topics) >= 4:
                token_id = int(event_log.topics[3].hex(), 16)
                log.info(
                    "ERC-8004 tokenId extracted: %d tx=%s",
                    token_id, tx_hash[:20] + "..."
                )
                return token_id
        log.warning("Could not extract tokenId from logs — tx=%s", tx_hash)
        return None
    except Exception as e:
        log.warning("Error extracting tokenId: %s", e)
        return None
