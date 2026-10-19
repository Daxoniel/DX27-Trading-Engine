"""Durable Paper-owned intent/observation journal, with no submission transport."""
from copy import deepcopy
from datetime import datetime, timezone, date
from decimal import Decimal
import hashlib
import os
from pathlib import Path
import re

from dx27.adapters.intraday.lifecycle_journal import LifecycleJournal, canonical
from dx27.adapters.alpaca.paper_contract import PAPER_ENDPOINT, timestamp_revision
from dx27.domains.intraday.order_lifecycle import OrderReport, identifier, symbol_value, whole_quantity, TERMINAL

NAMESPACE = 'orb-paper-r1-v1'
FIELDS = {'intent_id','signal_key','session','symbol','side','quantity','signal_at','intent_ready_at','origin','feed','data_sha256'}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')


def require(ok, code):
    if not ok:
        raise ValueError(code)


class PaperIntentJournal:
    """Single writer. Hash chain detects local corruption, not producer authenticity.

    Cumulative reports are supplied explicitly. Unknown fees remain unknown.
    Contributions are NOT a full account reconciliation or strategy PnL.
    """
    def __init__(self, path, mode, *, synthetic_clock=None):
        require(mode in ('SYNTHETIC','HISTORICAL_REPLAY','PAPER_OBSERVATION'),'EXPLICIT_JOURNAL_MODE_REQUIRED')
        require(mode!='PAPER_OBSERVATION' or synthetic_clock is None,'REAL_JOURNAL_CLOCK_NOT_INJECTABLE')
        self.mode=mode;self.clock=synthetic_clock or utc_now
        self.path=Path(path);self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.journal=LifecycleJournal(self.path,dict(contract='ORB_PAPER_INTENTS:1',namespace=NAMESPACE,
            endpoint=PAPER_ENDPOINT,mode=mode),dict(intents={},intent_ids={},signal_keys={},latest={},
            events={},broker_owners={},seen_unowned_clients=[],integrity_halt=None))
        for p in (self.path,Path(str(self.path)+'.lease.sqlite3')):
            try:os.chmod(p,0o600)
            except OSError:pass

    def close(self):self.journal.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def _halt(self,code):
        state=deepcopy(self.journal.state);state['integrity_halt']=code
        self.journal.save(state,dict(kind='INTEGRITY_HALT',code=code))
        raise ValueError(code)

    def register(self,intent):
        require(isinstance(intent,dict) and set(intent)==FIELDS,'EXACT_INTENT_FIELDS_REQUIRED')
        identifier(intent['intent_id']);identifier(intent['signal_key']);symbol_value(intent['symbol'])
        whole_quantity(intent['quantity']);date.fromisoformat(intent['session'])
        require(intent['side'] in ('buy','sell') and intent['feed'] in ('sip','iex'),'INVALID_INTENT_DIRECTION_OR_FEED')
        require(isinstance(intent['data_sha256'],str) and re.fullmatch('[0-9a-f]{64}',intent['data_sha256']), 'INPUT_SEAL_REQUIRED')
        expected={'SYNTHETIC':'SYNTHETIC','HISTORICAL_REPLAY':'HISTORICAL_REPLAY',
                  'PAPER_OBSERVATION':'OBSERVED_PAPER_SIGNAL'}[self.mode]
        require(intent['origin']==expected,'HISTORICAL_OR_CROSS_MODE_INTENT_REJECTED')
        now=self.clock();registered=timestamp_revision(now)
        require(timestamp_revision(intent['signal_at'])<=timestamp_revision(intent['intent_ready_at'])<=registered,
                'INTENT_PRECEDES_SIGNAL_OR_IS_FUTURE')
        prefix='orb-hst1-' if self.mode=='HISTORICAL_REPLAY' else 'orb-ppr1-'
        cid=prefix+hashlib.sha256((NAMESPACE+':'+intent['intent_id']).encode()).hexdigest()[:32]
        state=deepcopy(self.journal.state)
        if cid in state['intents']:
            if state['intents'][cid]['intent'] != intent:self._halt('INTENT_IDENTITY_CONFLICT')
            return cid
        require(state['integrity_halt'] is None,'REGISTRATION_HALTED')
        if intent['signal_key'] in state['signal_keys']:self._halt('SIGNAL_ALREADY_REGISTERED_UNDER_OTHER_ID')
        if cid in state['seen_unowned_clients']:self._halt('RETROACTIVE_OWNERSHIP_REJECTED')
        state['intents'][cid]=dict(intent=deepcopy(intent),registered_at=now)
        state['intent_ids'][intent['intent_id']]=cid;state['signal_keys'][intent['signal_key']]=cid
        self.journal.save(state,dict(kind='INTENT_REGISTERED',client_order_id=cid))
        return cid

    def observe(self,report,*,broker_created_at,observed_at,fee_known):
        require(self.mode!='HISTORICAL_REPLAY','HISTORICAL_REFERENCE_CANNOT_OBSERVE_BROKER_REPORTS')
        require(type(report) is OrderReport and type(fee_known) is bool,'NORMALIZED_REPORT_AND_FEE_STATUS_REQUIRED')
        report.validate()
        require(fee_known or report.fee==0,'UNKNOWN_FEE_MUST_USE_EXPLICIT_ZERO_PLACEHOLDER')
        created,observed=timestamp_revision(broker_created_at),timestamp_revision(observed_at)
        require(created<=report.revision<=observed,'ORDER_OBSERVATION_CLOCK_CONFLICT')
        if self.mode=='PAPER_OBSERVATION':require(observed<=timestamp_revision(self.clock()),'FUTURE_OBSERVATION_REJECTED')
        body=report.to_dict()
        event=dict(report=body,broker_created_revision=created,fee_known=fee_known)
        state=deepcopy(self.journal.state)
        previous=state['events'].get(report.event_id)
        if previous:
            if previous['event']!=event:self._halt('EVENT_IDENTITY_CONFLICT')
            return 'DUPLICATE'
        prior_owner=state['broker_owners'].get(report.broker_order_id)
        if prior_owner not in (None,report.client_order_id):self._halt('BROKER_ORDER_OWNERSHIP_CONFLICT')
        entry=state['intents'].get(report.client_order_id)
        if entry is None:
            if report.client_order_id not in state['seen_unowned_clients']:
                state['seen_unowned_clients'].append(report.client_order_id)
            disposition='UNOWNED_NO_ATTRIBUTION'
        else:
            intent=entry['intent']
            if created<timestamp_revision(entry['registered_at']):self._halt('ORDER_PRECEDES_DURABLE_INTENT')
            if (report.symbol,report.side.value,report.quantity)!=(intent['symbol'],intent['side'],intent['quantity']):
                self._halt('ORDER_INTENT_IDENTITY_CONFLICT')
            owner=state['broker_owners'].get(report.broker_order_id)
            if owner not in (None,report.client_order_id):self._halt('BROKER_ORDER_OWNERSHIP_CONFLICT')
            latest=state['latest'].get(report.client_order_id)
            if latest:
                old=latest['report']
                if old['broker_order_id']!=report.broker_order_id:self._halt('CLIENT_BOUND_TO_DIFFERENT_BROKER_ORDER')
                if latest['broker_created_revision']!=created:self._halt('ORDER_CREATION_CLOCK_CHANGED')
                if report.revision<old['revision']:
                    disposition='STALE'
                elif report.revision==old['revision']:
                    sans_id=lambda b:{k:v for k,v in b.items() if k!='event_id'}
                    if sans_id(body)!=sans_id(old) or fee_known!=latest['fee_known']:self._halt('REVISION_CONFLICT')
                    disposition='SAME_REVISION'
                else:
                    dq=report.filled_quantity-old['filled_quantity']
                    dn=report.filled_notional-Decimal(old['filled_notional'])
                    if dq<0 or dn<0 or (dq==0 and dn!=0) or (dq>0 and dn<=0):self._halt('CUMULATIVE_EXECUTIONS_REGRESSED_OR_REPRICED')
                    if latest['fee_known'] and (not fee_known or report.fee<Decimal(old['fee'])):self._halt('KNOWN_FEES_REGRESSED')
                    if old['status'] in TERMINAL:
                        allowed={old['status']}|({'filled'} if old['status'] in ('canceled','expired') else set())
                        if report.status not in allowed:self._halt('TERMINAL_ORDER_REOPENED')
                    disposition='APPLIED'
            else:disposition='APPLIED'
            if disposition=='APPLIED':
                state['latest'][report.client_order_id]=event
                state['broker_owners'][report.broker_order_id]=report.client_order_id
        state['events'][report.event_id]=dict(event=event,disposition=disposition)
        self.journal.save(state,dict(kind='OBSERVATION',event_id=report.event_id,disposition=disposition))
        return disposition

    def summary(self):
        state=self.journal.state;gross=Decimal(0);known_fees=Decimal(0);inventory={};unknown=0
        for latest in state['latest'].values():
            r=latest['report'];sign=1 if r['side']=='buy' else -1
            gross-=sign*Decimal(r['filled_notional'])
            inventory[r['symbol']]=inventory.get(r['symbol'],0)+sign*r['filled_quantity']
            if latest['fee_known']:known_fees+=Decimal(r['fee'])
            else:unknown+=1
        observed=bool(state['latest'])
        return dict(contract='ORB_PAPER_INTENTS:1',mode=self.mode,registered_intents=len(state['intents']),
            observed_owned_orders=len(state['latest']),unowned_clients_seen=len(state['seen_unowned_clients']),
            journal_sequence=self.journal.sequence,integrity_halt=state['integrity_halt'],
            owned_gross_cash_delta=str(gross),known_recorded_fees=str(known_fees),unknown_fee_orders=unknown,
            owned_cash_delta_including_all_recorded_fees=str(gross-known_fees) if observed and not unknown else None,
            owned_inventory_contribution={k:v for k,v in inventory.items() if v},
            actual_strategy_paper_pnl=None,account_reconciliation_complete=False,
            source_authenticity_verified=False,execution_enabled=False,live_endpoint_supported=False)
