# Discord Configuration — CooperCorp PRJ-002

## Server
- Guild ID: `1467898695436730420`
- Name: CooperCorp Trading

## Channels

| Channel | ID | Purpose |
|---|---|---|
| #war-room-hive-mind | `1469763123010342953` | Analysis, scan results, system status |
| #paper-trades | `1468597633756037385` | All trade entries/exits/monitoring |
| #winning-trades | `1468620383019077744` | Closed winners |
| #losing-trades | `1468620412849229825` | Closed losers + lessons |
| #cooper-study | `1468621074999541810` | Weekly reviews, sector rotation, learning |
| #trading-chat | `1467904044675629258` | Morning brief, general market discussion |
| #options-trades | `1468250120490324141` | Options-specific trades |
| #gamespoofer-trades | `1469519503174926568` | Private trade log (gamespoofer) |
| #prj-002-trading | `1473915686790369414` | Development channel |

## Posting

All Discord posts use the OpenClaw CLI:
```bash
openclaw message send --channel discord --target <CHANNEL_ID> --message "YOUR MESSAGE"
```

## Routing Rules

| Event | Channel |
|---|---|
| Scan result (any) | #war-room-hive-mind (1469763123010342953) |
| Trade entry | #paper-trades (1468597633756037385) |
| Trade exit — profit | #winning-trades + #paper-trades |
| Trade exit — loss | #losing-trades + #paper-trades |
| System ready (9:25 AM) | #war-room-hive-mind |
| Morning brief | #trading-chat (1467904044675629258) |
| Weekly review | #cooper-study + #paper-trades |
| Sector rotation | #cooper-study (1468621074999541810) |
| Breaking news | #war-room-hive-mind |
| Private log | #gamespoofer-trades (1469519503174926568) |
