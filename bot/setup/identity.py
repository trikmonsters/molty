"""
ERC-8004 Identity registration setup.

Flow:
  1. Check if already registered (GET /identity)
  2. Call register() on-chain via CROSS Tx Delegator (gasPrice=0, delegator pays)
  3. Extract tokenId from tx receipt
  4. POST /api/identity { agentId: tokenId }

Never crashes — returns False on any failure so heartbeat retries.
"""
from bot.api_client import MoltyAPI, APIError
from bot.web3.identity_contract import register_identity_onchain
from bot.credentials import (
    get_owner_private_key,
    load_credentials,
    save_credentials,
)
from bot.config import ADVANCED_MODE
from bot.utils.logger import get_logger

log = get_logger(__name__)


async def ensure_identity(api: MoltyAPI) -> bool:
    """
    Ensure ERC-8004 identity is registered.
    Returns True if identity confirmed. Never crashes.
    """
    # ── Step 1: Already registered? ──────────────────────────────────
    try:
        identity = await api.get_identity()
        erc8004_id = identity.get("erc8004Id")
        if erc8004_id is not None:
            log.info("ERC-8004 identity already registered: tokenId=%s", erc8004_id)
            return True
    except APIError:
        pass

    if not ADVANCED_MODE:
        log.info(
            "ERC-8004 identity not registered. "
            "Register manually and set tokenId, or enable ADVANCED_MODE=true."
        )
        return False

    # ── Step 2: Get owner private key ────────────────────────────────
    owner_pk = get_owner_private_key()
    if not owner_pk:
        log.error("ADVANCED_MODE=true but Owner private key not available.")
        return False

    # ── Step 3: Call register() on-chain via Tx Delegator ────────────
    log.info("Registering ERC-8004 identity on-chain...")
    token_id = await register_identity_onchain(owner_pk)

    if token_id is None:
        log.warning("On-chain registration did not return tokenId. Will retry later.")
        return False

    # ── Step 4: POST /api/identity to link tokenId to account ────────
    try:
        await api.post_identity(token_id)
        log.info("✅ ERC-8004 identity registered: tokenId=%d", token_id)

        creds = load_credentials() or {}
        creds["erc8004_token_id"] = token_id
        save_credentials(creds)
        return True

    except APIError as e:
        if e.code == "CONFLICT":
            log.info(
                "Identity tokenId=%d already linked to another account. "
                "This NFT may have been used before. Will retry later.",
                token_id
            )
        elif e.code == "OWNER_MISMATCH":
            log.error(
                "Owner mismatch: ownerOf(%d) does not match your Owner EOA. "
                "Registration succeeded on-chain but server rejected it.",
                token_id
            )
        else:
            log.error("POST /api/identity failed: [%s] %s", e.code, e.message)
        return False
