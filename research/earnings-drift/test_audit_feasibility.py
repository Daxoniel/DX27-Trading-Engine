"""Evidence integrity and coverage failures must not become strategy results."""
import json
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from audit_feasibility import EXPECTED_URLS, audit, instant, news_inventory, sealed
from capture_feasibility import NEWS


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def write(self,name,body,url=None,status=200):
        raw=json.dumps(body).encode();(self.root/(name+'.raw')).write_bytes(raw)
        m=dict(id=name,url=url or EXPECTED_URLS.get(name,''),http_status=status,
            bytes=len(raw),sha256=sha256(raw).hexdigest())
        (self.root/(name+'.meta.json')).write_text(json.dumps(m))

    def news(self,token=None):
        self.write('alpaca-news',dict(news=[dict(id=1,created_at='2025-05-28T16:00:00Z',
            updated_at='2025-05-28T12:01:00-04:00')],next_page_token=token),
            'https://data.alpaca.markets/v1beta1/news?'+urlencode(NEWS))

    def test_changed_raw_response_is_rejected(self):
        self.write('sec-eps',{})
        (self.root/'sec-eps.raw').write_text('{"new":true}')
        with self.assertRaisesRegex(ValueError,'SOURCE_SEAL_FAILED'):sealed(self.root,'sec-eps')

    def test_rebound_source_request_is_rejected(self):
        self.write('sec-eps',{},'https://example.com/other-company')
        with self.assertRaisesRegex(ValueError,'REQUEST_BINDING_FAILED'):sealed(self.root,'sec-eps')

    def test_missing_second_page_cannot_pass_completeness(self):
        self.news('next')
        with self.assertRaises(FileNotFoundError):news_inventory(self.root)

    def test_duplicate_news_across_pages_is_rejected(self):
        self.news('next');body=json.loads((self.root/'alpaca-news.raw').read_text());body['next_page_token']=None
        self.write('alpaca-news-001',body,'https://data.alpaca.markets/v1beta1/news?'+urlencode(dict(NEWS,page_token='next')))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_NEWS_ID'):news_inventory(self.root)

    def test_offset_timestamps_are_compared_as_instants(self):
        self.news();result,_=news_inventory(self.root)
        self.assertEqual(result['updated_after_creation'],1)
        with self.assertRaisesRegex(ValueError,'TIMEZONE_REQUIRED'):instant('2025-05-28T16:00:00')

    def test_demo_eps_and_known_dates_do_not_create_an_eligible_universe(self):
        self.news()
        self.write('sec-submissions',dict(filings=dict(recent=dict(acceptanceDateTime=[]))))
        self.write('sec-eps',dict(units={'USD/shares':[
            dict(start='2024-01-01',end='2024-03-31',val=1,filed='2024-05-01'),
            dict(start='2024-01-01',end='2024-03-31',val=2,filed='2026-05-01')]}))
        self.write('alphavantage-ibm-demo',dict(quarterlyEarnings=[dict(reportedDate='2025-01-30',
            reportedEPS='1',estimatedEPS='.9',reportTime='post-market')]))
        self.write('alpaca-doc-index',{})
        old=self.root/'events.json';old.write_text(json.dumps([dict(release_time='UNKNOWN',announcement_date='2025-01-30')]))
        result=audit(self.root,old)
        self.assertFalse(result['backtest_permitted']);self.assertFalse(result['returns_computed'])
        self.assertIsNone(result['historical_pit_event_count'])
        self.assertEqual(result['providers']['sec-eps']['periods_with_multiple_values_across_filings'],1)
        self.assertEqual(result['providers']['existing_blackout_events']['actual_eps_records'],0)

    def test_http_denial_does_not_establish_access(self):
        self.write('sec-eps',{},status=403)
        _,body=sealed(self.root,'sec-eps');self.assertIsNone(body)


if __name__=='__main__':unittest.main()
