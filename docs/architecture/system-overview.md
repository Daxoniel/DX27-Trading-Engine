# DX27 Trading Engine — System Overview

## System Context

```mermaid
flowchart LR
    User[User / WESI]
    Market[Market Data Providers]
    Broker[Broker APIs]

    subgraph DX27["DX27 Trading Engine"]
        Engine[Trading Platform Core]
    end

    User <-->|REST / WebSocket| Engine
    Market -->|Market Data| Engine
    Engine <-->|Orders / Positions / Account| Broker