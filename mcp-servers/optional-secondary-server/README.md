# Optional secondary MCP server (not implemented)

This slot is reserved by the required repository layout. The primary `alarm-management` server covers every mandatory
capability, so no second server was built.

The planned second server is a maintenance / CMMS server with:

- **Read tools:** work-order history per asset, spare-part stock.
- **Write tool:** `create_work_order`, marked `destructiveHint`.

The copilot would require explicit human approval in the GUI before calling the write tool. See
[docs/known-limitations.md](../../docs/known-limitations.md).
