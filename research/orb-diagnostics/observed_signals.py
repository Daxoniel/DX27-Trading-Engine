"""Durable, bounded observation of R1 direction and later ask-reference readiness.

No broker/market-data transport, quantity sizing, order intent, or submission.
Caller-supplied receipt clocks and feed labels are not authenticated.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib
import os
from pathlib import Path

from dx27.adapters.intraday.lifecycle_journal import LifecycleJournal, canonical
from dx27.core.models.market_context import MarketContext
from dx27.research.opening_direction import OpeningDirectionFixture
from execution_timing import clock, evaluate_timing, micros, positive_integer
from historical_signals import stamp
from paper_intents import require, utc_now

CONTRACT = 'ORB_OBSERVED_SIGNAL_READINESS:1'
MINUTE = timedelta(minutes=1)


class ObservedSignalJournal:
    """One session, single writer, at most 2048 accepted receipt events.

    Replayed identical receipts do not advance state. Missing sequence, conflicting
    identity or clock regression persist a halt. Receipt sequence is local input
    continuity, not proof of provider completeness. A reference is not an order.
    """
    def __init__(self, path, session, *, mode, probe_quantity,
                 max_quote_age_us=None, max_input_age_us=None, synthetic_clock=None):
        require(mode in ('SYNTHETIC','RECORDED_OBSERVATION'), 'OBSERVATION_MODE_REQUIRED')
        require(mode=='SYNTHETIC' or synthetic_clock is None, 'REAL_PROCESSING_CLOCK_NOT_INJECTABLE')
        positive_integer(probe_quantity)
        for v in (max_quote_age_us,max_input_age_us):
            if v is not None: positive_integer(v)
        # Reuse the frozen model's session checks without changing its source.
        OpeningDirectionFixture(session,'R1')
        self.session=session; self.mode=mode; self.clock=synthetic_clock or utc_now
        self.quantity=probe_quantity; self.quote_age=max_quote_age_us; self.input_age=max_input_age_us
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.journal=LifecycleJournal(path,dict(contract=CONTRACT,mode=mode,feed='sip',symbol='QQQ',
            session=session.session_id,opens_at=stamp(session.opens_at),closes_at=stamp(session.closes_at),
            probe_quantity=probe_quantity,max_quote_age_us=max_quote_age_us,max_input_age_us=max_input_age_us),
            dict(events={},bars=[],quotes=[],last_receipt=None,last_processed=None,trace=None,
                 reference=None,status='WAITING_FOR_SIX_CLOSED_MINUTES',integrity_halt=None))
        for p in (path,Path(str(path)+'.lease.sqlite3')):
            try:os.chmod(p,0o600)
            except OSError:pass

    def close(self):self.journal.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def _halt(self,code):
        state=deepcopy(self.journal.state);state['integrity_halt']=code
        self.journal.save(state,dict(kind='INTEGRITY_HALT',code=code))
        raise ValueError(code)

    def accept(self,event):
        require(isinstance(event,dict) and set(event)=={'event_id','receipt_sequence','received_at','feed','kind','payload'},
                'EXACT_RECEIPT_ENVELOPE_REQUIRED')
        eid=event['event_id']
        require(isinstance(eid,str) and 0<len(eid)<=128,'RECEIPT_ID_REQUIRED')
        raw=canonical(event);state=deepcopy(self.journal.state)
        if eid in state['events']:
            if state['events'][eid]!=raw:self._halt('RECEIPT_IDENTITY_CONFLICT')
            return 'DUPLICATE'
        require(state['integrity_halt'] is None,'OBSERVATION_HALTED')
        require(state['reference'] is None,'REFERENCE_ALREADY_FROZEN')
        require(len(state['events'])<2048,'BOUNDED_RECEIPT_LIMIT')
        seq=positive_integer(event['receipt_sequence'])
        if seq!=len(state['events'])+1:self._halt('RECEIPT_SEQUENCE_GAP_OR_REORDER')
        received=clock(event['received_at']);processed=clock(self.clock())
        require(self.session.opens_at<=received<self.session.closes_at,'RECEIPT_OUTSIDE_SESSION')
        require(received<=processed,'RECEIPT_IN_PROCESSING_FUTURE')
        if state['last_receipt'] and received<clock(state['last_receipt']):self._halt('RECEIPT_CLOCK_REGRESSED')
        if state['last_processed'] and processed<clock(state['last_processed']):self._halt('PROCESSING_CLOCK_REGRESSED')
        require(event['feed']=='sip','FROZEN_R1_REQUIRES_SIP_NO_FALLBACK')
        payload=event['payload']
        if event['kind']=='BAR':
            require(len(state['bars'])<6,'OPENING_PREFIX_ALREADY_COMPLETE')
            require(isinstance(payload,dict) and set(payload)==set(MarketContext.__dataclass_fields__),
                    'EXACT_BAR_PAYLOAD_REQUIRED')
            require(all(type(payload[n]) in (int,float) for n in ('open','high','low','close','volume')),
                    'FINITE_NUMERIC_BAR_FIELDS_REQUIRED')
            bar=MarketContext(**{**payload,'timestamp':clock(payload['timestamp'])})
            require(bar.timestamp+MINUTE<=received,'BAR_RECEIVED_BEFORE_COMPLETION')
            # Rebuild a six-minute prefix only; never call the fixture's entry path.
            model=OpeningDirectionFixture(self.session,'R1')
            for item in state['bars']+[event]:
                b=item['payload'];b=MarketContext(**{**b,'timestamp':clock(b['timestamp'])})
                model.on_closed_minute(model.next_at,b,as_of=model.next_at+MINUTE)
            state['bars'].append(deepcopy(event))
            if len(state['bars'])==6:
                if not model.data_valid:state['status']='INVALID_OPENING_PREFIX'
                elif model.direction!=1:state['status']='NO_LONG_DIRECTION'
                elif self.input_age is None or self.quote_age is None:state['status']='BLOCKED_MISSING_FRESHNESS_POLICY'
                elif processed>=self.session.closes_at-10*MINUTE:state['status']='PAST_FROZEN_ENTRY_CUTOFF'
                elif (micros(processed-received)>self.input_age or max(
                        micros(clock(b['received_at'])-clock(b['payload']['timestamp'])-MINUTE)
                        for b in state['bars'])>self.input_age):
                    state['status']='BLOCKED_STALE_INPUT_RECEIPTS'
                else:
                    # Availability is a bar-end assumption. Receipt is explicit,
                    # decision/readiness is THIS processing time, never backdated.
                    state['trace']=dict(contract='ORB_OFFLINE_TIMING:1',observation_kind=self.mode,
                        symbol='QQQ',side='BUY',quantity=self.quantity,required_feed='sip',
                        signal_window_end=stamp(model.signal_at),
                        last_input_available_at=stamp(model.entry_at),
                        last_input_received_at=event['received_at'],decision_at=stamp(processed),
                        intent_ready_at=stamp(processed))
                    state['status']='WAITING_FOR_POST_PROCESSING_QUOTE'
        elif event['kind']=='QUOTE':
            require(isinstance(payload,dict) and set(payload)=={'symbol','event_at','bid','ask','bid_size','ask_size','size_unit'},
                    'EXACT_QUOTE_PAYLOAD_REQUIRED')
            require(payload['symbol']=='QQQ','QQQ_QUOTE_REQUIRED')
            q=dict(**payload,quote_id=eid,feed=event['feed'],receipt_sequence=seq,received_at=event['received_at'])
            dummy=dict(contract='ORB_OFFLINE_TIMING:1',observation_kind=self.mode,symbol='QQQ',side='BUY',
                quantity=self.quantity,required_feed='sip',**{n:stamp(self.session.opens_at) for n in
                ('signal_window_end','last_input_available_at','last_input_received_at','decision_at','intent_ready_at')})
            # Validate quotes even before a complete signal or when policy is absent.
            evaluate_timing(dummy,[q],max_quote_age_us=self.quote_age or 1)
            q['processing_delay_us']=micros(processed-received)
            state['quotes'].append(q)
            if state['trace']:
                eligible=[q for q in state['quotes'] if q['processing_delay_us']<=self.quote_age]
                result=evaluate_timing(state['trace'],eligible,max_quote_age_us=self.quote_age)
                if processed>=self.session.closes_at-10*MINUTE:state['status']='PAST_FROZEN_ENTRY_CUTOFF'
                elif micros(processed-clock(state['trace']['last_input_received_at']))>self.input_age:
                    state['status']='BLOCKED_SIGNAL_EXPIRED'
                elif result['status'] in ('SYNTHETIC_MODEL_MATCH','UNAUTHENTICATED_MODEL_MATCH'):
                    state['reference']=result;state['status']='REFERENCE_OBSERVED_NO_ORDER_INTENT'
                elif q['processing_delay_us']>self.quote_age:state['status']='BLOCKED_PROCESSING_DELAY'
        else:raise ValueError('BAR_OR_QUOTE_REQUIRED')
        state['events'][eid]=raw;state['last_receipt']=event['received_at'];state['last_processed']=stamp(processed)
        self.journal.save(state,dict(kind='RECEIPT_ACCEPTED',event_id=eid,processed_at=stamp(processed)))
        return state['status']

    def summary(self):
        s=self.journal.state
        return dict(contract=CONTRACT,mode=self.mode,status=s['status'],integrity_halt=s['integrity_halt'],
            accepted_receipts=len(s['events']),closed_minutes=len(s['bars']),quotes=len(s['quotes']),
            quotes_excluded_for_processing_delay=sum(q['processing_delay_us']>(self.quote_age or 0) for q in s['quotes']),
            journal_sequence=self.journal.sequence,trace=deepcopy(s['trace']),reference=deepcopy(s['reference']),
            receipt_prefix_sha256=hashlib.sha256(canonical(s['events']).encode()).hexdigest(),
            availability='ASSUMED_BAR_END_RECEIPTS_CALLER_DECLARED',
            quantity_basis='EXPLICIT_ENGINEERING_PROBE_NOT_R1_SIZING',
            source_authenticity_verified=False,provider_completeness_verified=False,
            actual_paper_intents_created=0,actual_strategy_paper_pnl=None,execution_enabled=False)
