# DX27 Trading Engine — System Overview

## System Context

```mermaid
flowchart LR

    User["User / External Client"]

    DX27["DX27 Decision System"]

    Infra["Trading Infrastructure<br/>LEAN · Other Engines · Broker APIs"]

    Market["Markets / Brokers"]

    User -->|Analyze · Configure · Control| DX27
    DX27 -->|Data Requests · Trade Intents| Infra
    Infra -->|Market / Portfolio State| DX27
    Infra -->|Orders| Market
    Market -->|Quotes · Fills · Account| Infra
    DX27 -->|Advice · Signals · Status| User
```

## Internal Architecture

```mermaid
flowchart TB

    subgraph Modes["Operating Modes"]
        Advisory["Advisory Mode"]
        Auto["Autonomous / Intraday Mode"]
        Strategic["Strategic / Rebalance Mode"]
    end

    Coverage["Coverage / Discovery"]

    subgraph Bots["Strategy Bot Pool"]
        Intraday["Intraday Bots"]
        Swing["Swing Bots"]
        LongTerm["Long-Term Bots"]
    end

    Features["Feature Service"]
    Rules["Rule Engine / Rule Packs"]

    Coordinator["Strategy Coordinator"]
    Doctrine["Capital Doctrine"]
    Risk["Risk Policy"]
    Approval["Approval / Control"]

    Interfaces["Core Interfaces"]
    Adapters["Infrastructure Adapters"]
    External["LEAN / Other Engine / Broker"]

    Advisory --> Bots
    Auto --> Coverage
    Coverage --> Bots
    Strategic --> Bots

    Bots -->|Request| Features
    Bots -->|Evaluate| Rules

    Features -->|Results| Bots
    Rules -->|Results| Bots

    Bots -->|BotSignals| Coordinator

    Coordinator --> Doctrine
    Doctrine --> Risk
    Risk --> Approval

    Approval --> Interfaces
    Interfaces --> Adapters
    Adapters --> External

    External -.->|Market / Portfolio State| Interfaces
```

## Bot Contract

```mermaid
flowchart LR

    Scope["Scope<br/>Symbol · Sector · Universe"]
    Config["Bot Configuration"]

    subgraph Bot["Strategy Bot"]
        Logic["Strategy Logic"]
        Request["Service Requests"]
    end

    Features["Feature Service"]
    Rules["Rule Service"]
    Market["Market Data Interface"]

    Signal["BotSignal"]

    Scope --> Logic
    Config --> Logic

    Logic --> Request

    Request --> Market
    Market --> Logic

    Request --> Features
    Features --> Logic

    Request --> Rules
    Rules --> Logic

    Logic --> Signal
```