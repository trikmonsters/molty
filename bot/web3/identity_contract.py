"""
ERC-8004 Identity Registry — on-chain registration via CROSS Tx Delegator.

How gas delegation works on CROSS chain:
  - Send a LEGACY tx (type 0) with gasPrice=0 directly to node
  - CROSS node's Tx Delegator middleware intercepts it
  - Delegator pays the actual gas on behalf of sender
  - Owner EOA balance stays at 0 — this is by design

ethers.js equivalent: registry.register({ gasLimit: 200000n })
  → ethers auto-sends legacy tx with gasPrice from provider,
    but CROSS node's delegator handles the fee.

Web3.py equivalent: send legacy tx with gasPrice=0 explicitly.
"""
import asyncio
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from bot.config import IDENTITY_REGISTRY, CROSS_CHAIN_ID, CROSS_RPC
from bot.web3.contracts import IDENTITY_ABI
from bot.utils.logger import get_logger

log = get_logger(__name__)


def _get_w3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(CROSS_RPC))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


async def register_identity_onchain(owner_private_key: str) -> int | None:
    """
    Call register() on ERC-8004 Identity Registry via CROSS Tx Delegator.

    Sends a LEGACY tx (type 0) with gasPrice=0 — CROSS node's Tx Delegator
    intercepts and pays gas. Owner EOA needs zero CROSS balance.

    Returns tokenId (agentId) on success, None on failure.
    """
    acct = Account.from_key(owner_private_key)
    w3 = _get_w3()

    try:
        registry = w3.eth.contract(
            address=Web3.to_checksum_address(IDENTITY_REGISTRY),
            abi=IDENTITY_ABI,
        )

        nonce = w3.eth.get_transaction_count(acct.address)

        # LEGACY tx (type 0) with gasPrice=0
        # CROSS Tx Delegator intercepts txs with gasPrice=0 and pays gas.
        # Do NOT use EIP-1559 (type 2) — delegator only handles legacy txs.
        tx = registry.functions.register().build_transaction({
            "from": acct.address,
            "nonce": nonce,
            "gas": 200_000,
            "gasPrice": 0,          # Tx Delegator pays — do not change
            "chainId": CROSS_CHAIN_ID,
        })

        signed = w3.eth.account.sign_transaction(tx, owner_private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        hex_hash = tx_hash.hex()
        log.info(
            "register() tx sent via Tx Delegator: hash=%s nonce=%d",
            hex_hash[:20] + "...", nonce
        )

    except Exception as e:
        err = str(e)
        if "gas tip cap" in err or "insufficient funds" in err:
            log.error(
                "ERC-8004 register() error (gas is delegated — this is a client-side issue): %s\n"
                "→ CROSS Tx Delegator did not intercept this tx.\n"
                "→ Check RPC URL: should be https://mainnet.crosstoken.io:22001\n"
                "→ Check tx type: must be legacy (type=0) with gasPrice=0",
                err
            )
        else:
            log.error("ERC-8004 register() error: %s", e)
        return None

    # Poll for receipt
    token_id = await _wait_and_extract_token_id(w3, tx_hash, registry)
    return token_id


async def _wait_and_extract_token_id(
    w3: Web3,
    tx_hash: bytes,
    registry,
    timeout: int = 90,
) -> int | None:
    """Poll for receipt and extract tokenId from Registered event."""
    hex_hash = tx_hash.hex()
    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                if receipt.status != 1:
                    log.error("register() tx reverted: %s", hex_hash)
                    return None

                # Extract tokenId from Registered(address,uint256) event
                try:
                    logs = registry.events.Registered().process_receipt(receipt)
                    if logs:
                        token_id = logs[0].args.get("agentId") or logs[0].args.get("tokenId")
                        if token_id is not None:
                            log.info(
                                "✅ ERC-8004 registered: tokenId=%d tx=%s",
                                token_id, hex_hash[:20] + "..."
                            )
                            return token_id
                except Exception:
                    pass

                # Fallback: scan raw logs for Transfer(0x0 → owner, tokenId)
                for raw_log in receipt.logs:
                    if len(raw_log.topics) >= 4:
                        token_id = int(raw_log.topics[3].hex(), 16)
                        log.info(
                            "✅ ERC-8004 tokenId from Transfer log: %d tx=%s",
                            token_id, hex_hash[:20] + "..."
                        )
                        return token_id

                log.warning("register() confirmed but tokenId not found in logs")
                return None

        except Exception:
            pass

        await asyncio.sleep(3)

    log.warning("register() tx receipt timeout after %ds", timeout)
    return None
