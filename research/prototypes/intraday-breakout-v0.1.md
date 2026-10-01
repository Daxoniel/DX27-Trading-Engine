# Intraday Breakout Bot v0.1

## Purpose

Minimal end-to-end intraday trading strategy for validating DX27.

## Universe

Initial test symbol:

SPY

Future validation:

QQQ
SOXX
SOXL

## Timeframe

5-minute bars.

## Trading Window

09:35 - 15:50 New York time.

No overnight positions.

## Entry

LONG only for v0.1.

Enter when:

1. Price breaks above the previous 20-bar high.
2. Current volume is greater than 1.5x the average volume of the previous 20 bars.
3. No blocking rule is triggered.

## Stop Loss

1 ATR below entry.

## Take Profit

2 ATR above entry.

## Exit

Exit when:

- Stop loss reached
- Take profit reached
- 15:50 New York time reached

## Position Rules

Only one open position at a time.

## v0.1 Limitations

- LONG only
- Single symbol
- No Doctrine
- No Coverage scanner
- No multi-bot coordination
- No live trading