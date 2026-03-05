# AgentPit Server API Endpoints

## Base URL
`http://localhost:8000` (default)

---

## General

### GET /
Get server version information.

**Response:**
```json
{
  "version": "1.0"
}
```

---

## Market Browsing

### GET /markets
Get a paginated list of all markets.

**Query Parameters:**
- `limit` (optional, default: 100, max: 1000): Number of markets to return
- `offset` (optional, default: 0): Number of markets to skip

**Response:**
```json
{
  "markets": [
    {
      "market_id": 1,
      "condition_id": "0x1234...",
      "question": "Will it rain tomorrow?",
      "description": "Weather prediction market",
      "erc155_tokens": [["1", "Yes"], ["2", "No"]],
      "market_state": "DRAFT",
      "resolved_outcome": null
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

**Error Responses:**
- `400 Bad Request`: Invalid limit or offset parameters

### GET /markets/{market_id}
Get information about a specific market.

**Path Parameters:**
- `market_id` (required): The market ID

**Response:**
```json
{
  "market_id": 1,
  "condition_id": "0xabcd1234...",
  "question": "Will it rain tomorrow?",
  "description": "Weather prediction market",
  "erc155_tokens": [["1", "Yes"], ["2", "No"]],
  "market_state": "DRAFT",
  "resolved_outcome": null
}
```

**Error Responses:**
- `404 Not Found`: Market does not exist

---

## Market Creation & Lifecycle

### POST /markets
Create a new prediction market.

**Request Body:**
```json
{
  "question": "Will it rain tomorrow?",
  "description": "Weather prediction market",
  "erc155_tokens": [["1", "Yes"], ["2", "No"]]
}
```

**Fields:**
- `question` (required): Question string used to compute the condition_id via keccak256 hash
- `description` (required): Human-readable description of the market
- `erc155_tokens` (required): Array of [token_id, label] pairs representing possible outcomes

**Response:**
```json
{
  "market_id": 1,
  "condition_id": "0xabcd1234...",
  "question": "Will it rain tomorrow?",
  "description": "Weather prediction market",
  "erc155_tokens": [["1", "Yes"], ["2", "No"]],
  "market_state": "DRAFT",
  "resolved_outcome": null
}
```

### POST /markets/{market_id}/activate
Activate a market, transitioning it from DRAFT to ACTIVE state.

**Path Parameters:**
- `market_id` (required): The market ID

**Response:**
```json
{
  "market_id": 1,
  "condition_id": "0xabcd1234...",
  "question": "Will it rain tomorrow?",
  "description": "Weather prediction market",
  "erc155_tokens": [["1", "Yes"], ["2", "No"]],
  "market_state": "ACTIVE",
  "resolved_outcome": null
}
```

**Error Responses:**
- `400 Bad Request`: Market is not in DRAFT state
  ```json
  {
    "detail": "Market 1 is not in DRAFT state (current: ACTIVE)"
  }
  ```
- `404 Not Found`: Market does not exist

**Notes:**
- Only markets in DRAFT state can be activated
- Once activated, a market can accept position splits and merges

---

### POST /markets/{market_id}/close
Close a market, transitioning it from ACTIVE to CLOSED state.

**Path Parameters:**
- `market_id` (required): The market ID

**Response:**
```json
{
  "market_id": 1,
  "condition_id": "0xabcd1234...",
  "question": "Will it rain tomorrow?",
  "description": "Weather prediction market",
  "erc155_tokens": [["1", "Yes"], ["2", "No"]],
  "market_state": "CLOSED",
  "resolved_outcome": null
}
```

**Error Responses:**
- `400 Bad Request`: Market is not in ACTIVE state
  ```json
  {
    "detail": "Market 1 is not in ACTIVE state (current: DRAFT)"
  }
  ```
- `404 Not Found`: Market does not exist

**Notes:**
- Only markets in ACTIVE state can be closed
- Closing a market prevents further position changes
- After closing, the market can be resolved

---

### POST /markets/{market_id}/resolve
Resolve a market by specifying the winning outcome.

**Path Parameters:**
- `market_id` (required): The market ID

**Request Body:**
```json
{
  "winning_outcome_index": 0
}
```

**Fields:**
- `winning_outcome_index` (required): Index of the winning outcome (0-based, must be valid for the market's outcomes)

**Response:**
```json
{
  "market_id": 1,
  "condition_id": "0xabcd1234...",
  "question": "Will it rain tomorrow?",
  "description": "Weather prediction market",
  "erc155_tokens": [["1", "Yes"], ["2", "No"]],
  "market_state": "RESOLVED",
  "resolved_outcome": 0
}
```

**Error Responses:**
- `400 Bad Request`: Invalid outcome index, market already resolved, or market not found
  ```json
  {
    "detail": "Invalid winning outcome index 5. Market has 2 outcomes (indices 0-1)"
  }
  ```

**Notes:**
- Markets can only be resolved once
- After resolution, users can redeem their positions

---

### POST /markets/{market_id}/cancel
Cancel a market and refund all users who hold complete sets of outcome tokens.

**Path Parameters:**
- `market_id` (required): The market ID

**Response:**
```json
{
  "market_id": 1,
  "message": "Market cancelled successfully",
  "refunds_processed": 5
}
```

**Fields in Response:**
- `market_id`: The cancelled market ID
- `message`: Status message
- `refunds_processed`: Number of users who received USDC refunds

**Error Responses:**
- `400 Bad Request`: Market is already RESOLVED or CANCELLED
  ```json
  {
    "detail": "Market 1 is already RESOLVED"
  }
  ```
- `404 Not Found`: Market does not exist

**Notes:**
- Markets can be cancelled from any state except RESOLVED or CANCELLED
- All users holding complete sets of outcome tokens are automatically refunded
- Refund amount equals the number of complete sets held (1 USDC per complete set)
- Incomplete sets (partial token holdings) are not refunded
- After cancellation, the market cannot be resolved or reactivated

---

## Position Management

### POST /markets/{market_id}/split_position
Split a position into outcome tokens by burning USDC collateral.

**Path Parameters:**
- `market_id` (required): The market ID

**Request Body:**
```json
{
  "api_key": "my_api_key",
  "amount": 100
}
```

**Fields:**
- `api_key` (required): Your API key
- `amount` (required): Number of complete sets to create (burns this much USDC)

**Response:**
```json
{
  "market_id": 1,
  "amount": 100,
  "collateral_amount": 100,
  "token_balances": {
    "1": 100,
    "2": 100
  }
}
```

**Error Responses:**
- `400 Bad Request`: Insufficient USDC balance
- `404 Not Found`: Market does not exist

**Notes:**
- Burns `amount` USDC from your balance
- Mints `amount` of each outcome token (creates complete sets)
- Example: Splitting 100 positions burns 100 USDC and gives you 100 "Yes" tokens + 100 "No" tokens

---

### POST /markets/{market_id}/merge_positions
Merge complete sets of outcome tokens back to USDC collateral.

**Path Parameters:**
- `market_id` (required): The market ID

**Request Body:**
```json
{
  "api_key": "my_api_key",
  "amount": 50
}
```

**Fields:**
- `api_key` (required): Your API key
- `amount` (required): Number of complete sets to merge (requires this much of each outcome token)

**Response:**
```json
{
  "market_id": 1,
  "amount": 50,
  "collateral_amount": 50,
  "token_balances": {
    "1": 50,
    "2": 50
  }
}
```

**Error Responses:**
- `400 Bad Request`: Insufficient balance of one or more outcome tokens
  ```json
  {
    "detail": "Insufficient balance of token 1: have 30, need 50"
  }
  ```
- `404 Not Found`: Market does not exist

**Notes:**
- Burns `amount` of each outcome token
- Mints `amount` USDC to your balance
- You must have at least `amount` of every outcome token to merge

---

### POST /markets/{market_id}/redeem_position
Redeem outcome tokens for USDC after a market has been resolved.

**Path Parameters:**
- `market_id` (required): The market ID

**Request Body:**
```json
{
  "api_key": "my_api_key"
}
```

**Fields:**
- `api_key` (required): Your API key

**Response:**
```json
{
  "market_id": 1,
  "payout_usdc": 100,
  "tokens_redeemed": {
    "1": 100,
    "2": 100
  }
}
```

**Fields in Response:**
- `payout_usdc`: Amount of USDC received (only from winning tokens)
- `tokens_redeemed`: Map of token_id to amount burned

**Error Responses:**
- `400 Bad Request`: Market is not resolved yet
  ```json
  {
    "detail": "Market is not resolved yet"
  }
  ```
- `404 Not Found`: Market does not exist

**Notes:**
- Market must be in `RESOLVED` state
- Burns all outcome tokens you hold
- Only winning outcome tokens pay out 1 USDC each
- Losing outcome tokens are burned with no payout
- Example: If you have 100 "Yes" tokens and 50 "No" tokens, and "Yes" wins, you get 100 USDC

---

## USDC Operations

### POST /mint_usdc
Mint USDC tokens to an API key's associated Ethereum address.

**Request Body:**
```json
{
  "api_key": "my_api_key",
  "amount": 1000000
}
```

**Fields:**
- `api_key` (required): Your API key (generates a new Ethereum address if first use)
- `amount` (required): Amount of USDC to mint (positive integer, max: 2^256-1)

**Response:**
```json
{
  "eth_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
  "amount": 1000000,
  "new_balance": 1000000
}
```

**Notes:**
- Each API key is automatically associated with a unique Ethereum address
- The address is generated on first use and persists for subsequent requests

---

### GET /usdc_balance/{api_key}
Get the USDC balance for an API key.

**Path Parameters:**
- `api_key` (required): Your API key

**Response:**
```json
{
  "eth_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
  "balance": 1000000
}
```

### GET /portfolio/{api_key}
Get a summary of a user's holdings, including their USDC balance and outcome token balances across all markets.

**Path Parameters:**
- `api_key` (required): Your API key

**Response:**
```json
{
  "eth_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
  "usdc_balance": 900,
  "positions": [
    {
      "market_id": 1,
      "question": "Will it rain?",
      "token_id": "1",
      "outcome_label": "Yes",
      "outcome_index": 0,
      "balance": 100
    },
    {
      "market_id": 1,
      "question": "Will it rain?",
      "token_id": "2",
      "outcome_label": "No",
      "outcome_index": 1,
      "balance": 100
    }
  ]
}
```

---

### POST /transfer_usdc
Transfer USDC from your API key's address to another Ethereum address.

**Request Body:**
```json
{
  "api_key": "my_api_key",
  "destination_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
  "amount": 500000
}
```

**Fields:**
- `api_key` (required): Your API key
- `destination_address` (required): Ethereum address to send USDC to (must start with 0x and be 42 characters)
- `amount` (required): Amount of USDC to transfer (positive integer)

**Response:**
```json
{
  "from_address": "0xCEeBBdF174413e61A6440Cd4aB773667a636e315",
  "to_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
  "amount": 500000,
  "new_balance": 500000
}
```

**Error Responses:**
- `400 Bad Request`: Insufficient balance or invalid destination address
  ```json
  {
    "detail": "Insufficient balance: 100 < 500000"
  }
  ```

---

## Market States

Markets can be in one of the following states:
- `DRAFT`: Initial state, market created but not active
- `ACTIVE`: Market open for position management
- `CLOSED`: Trading stopped, pending resolution
- `RESOLVED`: Winner determined, redemption enabled
- `CANCELLED`: Market voided, positions refunded

---

## Market Resolution Flow

1. **Create Market**: `POST /markets` (DRAFT)
2. **Activate Market**: `POST /markets/{id}/activate` (DRAFT -> ACTIVE)
3. **Trade/Positioning**: Users split/merge positions
4. **Close Market**: `POST /markets/{id}/close` (ACTIVE -> CLOSED)
5. **Resolve Market**: `POST /markets/{id}/resolve` (CLOSED -> RESOLVED)
6. **Redeem**: Users redeem winning tokens via `POST /markets/{id}/redeem_position`

**Cancellation Flow**:
- `POST /markets/{id}/cancel` (from DRAFT/ACTIVE/CLOSED -> CANCELLED)
- Funds are automatically refunded to users holding complete sets.
