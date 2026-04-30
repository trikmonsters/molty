"""
ERC-8004 Identity registration — fee-delegated relay flow.

v1.5.2+fix Flow:
  1. Check if identity already registered (GET /identity)
  2. Build + sign register() tx from Owner EOA (no direct node submission)
  3. POST signed raw tx to /relay/identity (Molty server adds FeePayer, submits type 0x07 tx)
  4. Wait for relay tx confirmation on-chain
  5. Extract tokenId from tx logs
  6. POST /api/identity { agentId: tokenId } to link identity to account

Never crashes — returns False if any step fails (caller retries).
"""
from bot.api_client import MoltyAPI, APIError
from bot.web3.identity_contract import (
    build_signed_register_tx,
    wait_for_relay_receipt,
    extract_token_id_from_tx,
)
from bot.credentials import get_owner_private_key, get_owner_eoa, load_credentials, save_credentials
from bot.config import ADVANCED_MODE
from bot.utils.logger import get_logger

log = get_logger(__name__)


async def ensure_identity(api: MoltyAPI) -> bool:
    """
    Ensure ERC-8004 identity is registered via fee-delegated relay.
    Returns True if identity is set. Never crashes.
    """
    # ── Step 1: Check if already registered ──────────────────────────
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
            "ERC-8004 identity not registered. In default mode, "
            "register manually then set the tokenId."
        )
        return False

    # ── Step 2: Get owner credentials ────────────────────────────────
    owner_pk = get_owner_private_key()
    if not owner_pk:
        log.error("Advanced mode but no Owner private key available")
        return False

    owner_eoa = get_owner_eoa()
    if not owner_eoa:
        log.error("Advanced mode but no Owner EOA address available")
        return False

    # ── Step 3: Build + sign register() tx ───────────────────────────
    log.info("Registering ERC-8004 identity on-chain (fee-delegated relay)...")
    signed_raw_tx = build_signed_register_tx(owner_pk)
    if not signed_raw_tx:
        log.warning("Failed to build signed tx. Will retry later.")
        return False

    # ── Step 4: POST to /relay/identity ──────────────────────────────
    try:
        relay_result = await api.post_relay_identity(signed_raw_tx, owner_eoa)
        tx_hash = relay_result.get("txHash") or relay_result.get("tx_hash") or relay_result.get("hash")

        if not tx_hash:
            log.warning(
                "Relay endpoint responded but no txHash in response: %s. "
                "Will retry later.", relay_result
            )
            return False

        log.info("Relay accepted tx: txHash=%s", tx_hash[:20] + "...")

    except APIError as e:
        if e.status == 403:
            log.error(
                "═══════════════════════════════════════════════════════════════\n"
                "  ❌ RELAY ENDPOINT DENIED (403) — Fee delegation unavailable\n"
                "  Error: %s\n"
                "  \n"
                "  This means the /relay/identity endpoint exists but your\n"
                "  Railway deployment IP is not whitelisted by Molty Royale.\n"
                "  \n"
                "  WORKAROUND OPTIONS:\n"
                "  1. Contact Molty Royale support to whitelist Railway IPs\n"
                "  2. Send a small amount of CROSS to your Owner EOA:\n"
                "     → Address: %s\n"
                "     → Amount: 0.001 CROSS (< $0.01)\n"
                "     → Buy on: Upbit / Gate.io, bridge at x.crosstoken.io\n"
                "═══════════════════════════════════════════════════════════════",
                e.message, owner_eoa
            )
        elif e.status == 409:
            # Already registered — just need to POST /api/identity
            log.info("Relay: identity already registered on-chain, fetching tokenId...")
            # Fall through to check identity again
            try:
                identity = await api.get_identity()
                erc8004_id = identity.get("erc8004Id")
                if erc8004_id is not None:
                    log.info("✅ Identity confirmed: tokenId=%s", erc8004_id)
                    return True
            except APIError:
                pass
            return False
        else:
            log.error(
                "Relay endpoint error [%d %s]: %s. Will retry later.",
                e.status, e.code, e.message
            )
        return False

    except Exception as e:
        log.error("Unexpected relay error: %s. Will retry later.", e)
        return False

    # ── Step 5: Wait for on-chain confirmation ────────────────────────
    confirmed = await wait_for_relay_receipt(tx_hash, timeout=90)
    if not confirmed:
        log.warning("Relay tx not confirmed within 90s. Will retry later.")
        return False

    # ── Step 6: Extract tokenId from logs ────────────────────────────
    token_id = await extract_token_id_from_tx(tx_hash)
    if token_id is None:
        log.warning("Could not extract tokenId from relay tx. Will retry later.")
        return False

    # ── Step 7: POST /api/identity to link account ───────────────────
    try:
        result = await api.post_identity(token_id)
        log.info("✅ ERC-8004 identity registered via relay: tokenId=%d", token_id)

        creds = load_credentials() or {}
        creds["erc8004_token_id"] = token_id
        save_credentials(creds)
        return True

    except APIError as e:
        if e.code == "CONFLICT":
            log.info("Identity already linked to account (CONFLICT) — treating as success")
            return True
        log.error("Identity API link failed: %s", e)
        return False
