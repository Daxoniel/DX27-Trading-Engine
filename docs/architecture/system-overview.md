# DX27 Trading Engine — System Overview

## System Context

```mermaid
flowchart LR

    Client["External Client<br/>CLI · Web UI · WESI"]
    Market["Market Data"]
    Broker["Broker API"]

    subgraph DX27["DX27 Trading Engine"]
        Core["Platform Core"]
    end

    Client <-->|Control · Monitoring| Core
    Market -->|Quotes · Bars| Core
    Core -->|Orders| Broker
    Broker -->|Fills · Positions · Account| Core
```
## Internal Architecture

```mermaid
flowchart TB

    Market["Market Data"]
    Features["Feature Engine"]

    subgraph Strategies["Strategy Pool"]
        direction LR
        S1["Bot A"]
        S2["Bot B"]
        SN["Bot N"]
    end

    Coordinator["Strategy Coordinator"]
    Proposal["Trade Proposal"]
    Gate["Decision Gate"]
    Execution["Execution Engine"]
    Broker["Broker Adapter"]
    Portfolio["Portfolio State"]

    Rules["Rule Packs"]
    Risk["Risk Engine"]
    Approval["Approval Mode<br/>Human / Autonomous"]
    Supervision["Supervision"]

    Market --> Features
    Features --> Strategies
    Strategies --> Coordinator
    Coordinator --> Proposal
    Proposal --> Gate
    Gate --> Execution
    Execution --> Broker
    Broker --> Portfolio

    Rules -.-> Strategies
    Risk -.-> Gate
    Approval -.-> Gate
    Supervision -.-> Gate
    Portfolio -.-> Risk
```

## Bot Contract

```mermaid
flowchart LR

    State[Market State]
    Features[Features]
    Rules[Rule Packs]
    Config[Bot Config]

    subgraph Bot["Strategy Bot"]
        Logic[Strategy Logic]
    end

    Signal[Signal]

    State --> Logic
    Features --> Logic
    Rules --> Logic
    Config --> Logic

    Logic --> Signal
```