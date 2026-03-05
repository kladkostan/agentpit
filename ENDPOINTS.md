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

## Markets

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

---

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

**Notes:**
- The `condition_id` is automatically computed from the question and number of outcomes using:
  ```
  condition_id = keccak256(abi.encodePacked(oracle, keccak256(question), outcomeSlotCount))
  ```

---

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
- `DRAFT`: Market has been created but not yet active
- `ACTIVE`: Market is open for trading
- `CLOSED`: Market is closed, no more trading
- `RESOLVING`: Market outcome is being determined
- `RESOLVED`: Market has been resolved with a final outcome
- `CANCELLED`: Market has been cancelled

---

## Market Resolution Flow

1. **Create Market** - `POST /markets`
   - Market starts in `DRAFT` state
   - Users can start trading immediately

2. **Split Positions** - `POST /markets/{id}/split_position`
   - Users burn USDC to get outcome tokens
   - Can trade or hold outcome tokens

3. **Merge Positions** - `POST /markets/{id}/merge_positions` (optional)
   - Users can burn complete sets to get USDC back
   - Useful before market resolution

4. **Resolve Market** - `POST /markets/{id}/resolve`
   - Market transitions to `RESOLVED` state
   - Winning outcome is recorded

5. **Redeem Positions** - `POST /markets/{id}/redeem_position`
   - Users burn all outcome tokens
   - Receive USDC for winning tokens only

---

## Error Handling

All endpoints return standard HTTP status codes:
- `200 OK`: Successful request
- `400 Bad Request`: Invalid parameters or insufficient balance
- `404 Not Found`: Resource not found
- `422 Unprocessable Entity`: Validation error in request body
- `500 Internal Server Error`: Server error

Error responses follow this format:
```json
{
  "detail": "Error message here"
}
```
