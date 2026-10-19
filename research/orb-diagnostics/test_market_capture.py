import base64
from email.message import Message
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from market_capture import MarketCapture, HOST, LIMIT, inspect_entry, project_quote
from observed_signals import ObservedSignalJournal
from test_observed_signals import SESSION, bar


def body(kind='quote',at='2026-07-01T13:36:00.050000Z'):
    if kind=='quote':row=dict(t=at,bp=100,ap=100.02,bs=20,**{'as':20})
    else:row=dict(t='2026-07-01T13:35:00Z',o=100,h=102,l=99,c=101,v=10000)
    return json.dumps(dict(symbol='QQQ',**{kind:row})).encode()


def entry(raw=None,feed='sip',kind='quote'):
    raw=raw if raw is not None else body(kind)
    return dict(capture_id='md-test',kind=kind,feed=feed,status='CAPTURED',
        started_at='2026-07-01T13:36:00.030000Z',received_at='2026-07-01T13:36:00.060000Z',
        raw_base64=base64.b64encode(raw).decode(),raw_sha256=hashlib.sha256(raw).hexdigest())


def response(raw=None,url=HOST+'/v2/stocks/QQQ/quotes/latest?feed=sip',**headers):
    raw=body() if raw is None else raw
    r=Mock();r.status=200;r.geturl.return_value=url;r.read.return_value=raw
    r.headers=Message();r.headers['Content-Type']='application/json'
    for k,v in headers.items():
        name=k.replace('_','-')
        if name in r.headers:r.headers.replace_header(name,v)
        else:r.headers[name]=v
    r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False)
    return r


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'capture.sqlite'
        self.cap=MarketCapture(self.path,'test-key','test-secret',feed='sip')
        self.cap.opener=Mock()
    def tearDown(self):self.cap.close();self.tmp.cleanup()
    def sample(self,**kwargs):
        self.cap.opener.open.return_value=response(**kwargs)
        with patch('market_capture.utc_now',return_value='2026-07-01T13:36:00.060000Z'):
            return self.cap.sample('quote')

    def test_fixed_host_explicit_feed_get_raw_bytes_and_body_completion_clock(self):
        e=self.sample();self.assertEqual(e['status'],'CAPTURED')
        req=self.cap.opener.open.call_args.args[0]
        self.assertEqual(req.full_url,HOST+'/v2/stocks/QQQ/quotes/latest?feed=sip')
        self.assertEqual(req.get_method(),'GET');self.assertIsNone(req.data)
        self.assertEqual(base64.b64decode(e['raw_base64']),body())
        text=json.dumps(self.cap.journal.state)
        self.assertNotIn('test-key',text);self.assertNotIn('test-secret',text)

    def test_only_two_requests_and_no_arbitrary_path(self):
        self.sample();self.sample()
        with self.assertRaisesRegex(ValueError,'REQUEST_LIMIT'):self.cap.sample('quote')
        with self.assertRaisesRegex(ValueError,'QUOTE_OR_BAR'):self.cap.sample('/v2/orders')
        self.assertEqual(self.cap.opener.open.call_count,2)

    def test_http_denial_persists_stops_and_does_not_fallback(self):
        self.cap.opener.open.side_effect=HTTPError('https://private.invalid',403,'private-vendor-message',{},io.BytesIO(b'private'))
        e=self.cap.sample('quote');self.assertEqual(e['code'],'MARKET_HTTP_STATUS_403')
        self.assertNotIn('private',json.dumps(self.cap.summary()))
        self.cap.close();self.cap=MarketCapture(self.path,'test-key','test-secret',feed='sip')
        self.cap.opener=Mock()
        with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):self.cap.sample('bar')
        self.cap.opener.open.assert_not_called()

    def test_unresolved_pending_after_crash_cannot_resend(self):
        self.cap.opener.open.side_effect=RuntimeError('simulated process crash')
        with self.assertRaises(RuntimeError):self.cap.sample('quote')
        self.cap.close();self.cap=MarketCapture(self.path,'test-key','test-secret',feed='sip')
        self.assertEqual(self.cap.summary()['entries'][0]['status'],'PENDING')
        with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):self.cap.sample('quote')

    def test_network_error_is_sanitized(self):
        self.cap.opener.open.side_effect=URLError('sensitive-url')
        self.assertEqual(self.cap.sample('quote')['code'],'MARKET_NETWORK_UNAVAILABLE')

    def test_redirected_effective_url_is_not_accepted(self):
        self.assertEqual(self.sample(url='https://other.invalid')['status'],'INVALID_RESPONSE')

    def test_redirect_handler_refuses_forwarding(self):
        from dx27.adapters.alpaca.paper_recorder import RejectPaperRedirects
        self.assertIsNone(RejectPaperRedirects().redirect_request(None,None,302,'redirect',{},'https://other.invalid'))

    def test_oversize_wrong_encoding_type_and_truncation_rejected(self):
        cases=[dict(raw=b'x'*(LIMIT+1)),dict(Content_Length=str(LIMIT+1)),
               dict(Content_Encoding='gzip'),dict(Content_Length='1'),dict(Content_Type='text/plain')]
        for i,kwargs in enumerate(cases):
            with MarketCapture(Path(self.tmp.name)/f'case{i}','k','s',feed='sip') as c:
                c.opener=Mock();c.opener.open.return_value=response(**kwargs)
                self.assertEqual(c.sample('quote')['status'],'INVALID_RESPONSE')

    def test_invalid_json_duplicate_keys_nonfinite_or_wrong_symbol_retains_raw(self):
        for raw in [b'{"symbol":"QQQ","symbol":"SPY"}',b'{"quote":NaN}',body().replace(b'QQQ',b'SPY')]:
            with self.subTest(raw=raw):
                e=entry(raw)
                with self.assertRaises((ValueError,KeyError)):inspect_entry(e)
        e=self.sample(raw=b'not-json');self.assertEqual(e['status'],'INVALID_RESPONSE')
        self.assertEqual(base64.b64decode(e['raw_base64']),b'not-json')

    def test_nanos_preserved_and_never_truncated_for_projection(self):
        e=entry(body(at='2026-07-01T13:36:00.050000123Z'))
        r=inspect_entry(e);self.assertEqual(r['provider_event_ns']%1000,123)
        self.assertEqual(r['event_age_at_http_receipt_ns'],9999877)
        p=project_quote(e,receipt_sequence=1)
        self.assertIsNone(p['event']);self.assertIn('NANOSECOND_JOURNAL_ADAPTER_REQUIRED',p['reasons'])

    def test_exact_micro_conversion_and_current_sip_share_units(self):
        p=project_quote(entry(body(at='2026-07-01T13:36:00.050000000Z')),receipt_sequence=7)
        self.assertEqual(p['status'],'NORMALIZED_QUOTE_NOT_A_SIGNAL')
        self.assertEqual(p['event']['payload']['event_at'],'2026-07-01T13:36:00.050000Z')
        self.assertEqual(p['event']['payload']['ask_size'],20)

    def test_iex_or_prechange_units_are_not_invented(self):
        p=project_quote(entry(feed='iex'),receipt_sequence=1)
        self.assertIn('SIZE_UNIT_UNRESOLVED',p['reasons']);self.assertIn('FROZEN_R1_REQUIRES_SIP',p['reasons'])
        e=entry(body(at='2025-10-31T13:36:00Z'))
        self.assertEqual(inspect_entry(e)['size_unit'],'UNRESOLVED')

    def test_provider_clock_future_zero_sizes_crossing_and_seal_tamper(self):
        with self.assertRaisesRegex(ValueError,'AFTER_HTTP'):inspect_entry(entry(body(at='2026-07-01T13:36:01Z')))
        b=json.loads(body());b['quote']['as']=0
        p=project_quote(entry(json.dumps(b).encode()),receipt_sequence=1)
        self.assertIn('ZERO_DISPLAYED_SIZE',p['reasons'])
        b['quote']['ap']=99
        with self.assertRaisesRegex(ValueError,'CROSSED'):inspect_entry(entry(json.dumps(b).encode()))
        e=entry();e['raw_sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'SEAL_MISMATCH'):inspect_entry(e)

    def test_latest_bar_is_checked_for_completion_not_assumed_final(self):
        self.assertTrue(inspect_entry(entry(body('bar'),kind='bar'))['bar_complete_at_http_receipt'])
        b=json.loads(body('bar'));b['bar']['t']='2026-07-01T13:36:00Z'
        self.assertFalse(inspect_entry(entry(json.dumps(b).encode(),kind='bar'))['bar_complete_at_http_receipt'])

    def test_capture_feed_and_limits_cannot_change_on_reopen(self):
        self.cap.close()
        for change in [dict(feed='iex'),dict(feed='sip',max_requests=3)]:
            with self.assertRaises(ValueError):MarketCapture(self.path,'k','s',**change)
        self.cap=MarketCapture(self.path,'k','s',feed='sip')

    def test_exact_projection_connects_to_observation_in_constructed_case(self):
        now=['2026-07-01T13:30:00Z']
        with ObservedSignalJournal(Path(self.tmp.name)/'observation',SESSION,mode='SYNTHETIC',
             probe_quantity=10,max_quote_age_us=500000,max_input_age_us=1000000,
             synthetic_clock=lambda:now[0]) as book:
            for i in range(6):
                b=bar(i);now[0]=b['received_at'];book.accept(b)
            p=project_quote(entry(),receipt_sequence=7);now[0]=p['event']['received_at'];book.accept(p['event'])
            self.assertEqual(book.summary()['status'],'REFERENCE_OBSERVED_NO_ORDER_INTENT')
            self.assertEqual(book.summary()['actual_paper_intents_created'],0)


if __name__=='__main__':unittest.main()
