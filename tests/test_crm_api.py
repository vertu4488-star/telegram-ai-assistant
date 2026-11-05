import unittest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import crm_api

class CRMTests(unittest.TestCase):
    def setUp(self):
        app=FastAPI();app.include_router(crm_api.router);self.client=TestClient(app)
        crm_api._rates.clear()
    def sample(self):
        return {'transcript':'Купил дисплей за 5000, взял 8000, прибыль 2000', 'warnings':[], 'stated_profit':2000,
          'entries':[{'kind':'expense','amount':5000,'date':'2026-11-05','category':'Запчасти'}, {'kind':'income','amount':8000,'date':'2026-11-05','category':'Ремонт'}]}
    def test_auth_required(self):
        self.assertEqual(self.client.post('/crm/finance/extract',json={'text':'x'}).status_code,401)
    def test_profit_calculated_not_trusted(self):
        result=crm_api.validate_extraction(self.sample());self.assertEqual(result['cash_difference'],3000);self.assertTrue(result['warnings'])
    def test_invalid_amounts(self):
        for value in [-1,0,float('nan'),float('inf'),True,1.001]:
            raw=self.sample();raw['entries'][0]['amount']=value
            with self.assertRaises(ValueError):crm_api.validate_extraction(raw)
    def test_staff_gate(self):
        with patch.object(crm_api,'supabase_get',side_effect=[{'id':'11111111-1111-4111-8111-111111111111'},[{'role':'technician','active':True}]]):
            r=self.client.post('/crm/finance/extract',json={'text':'x'},headers={'Authorization':'Bearer test'})
            self.assertEqual(r.status_code,403)
    def test_authorized_extract_is_draft_only(self):
        with patch.object(crm_api,'staff_auth',AsyncMock(return_value=('test','token'))),patch.object(crm_api,'extract_finance',AsyncMock(return_value=crm_api.validate_extraction(self.sample()))) as extract:
            r=self.client.post('/crm/finance/extract',json={'text':'sample'})
            self.assertEqual(r.status_code,200);self.assertEqual(len(r.json()['entries']),2);extract.assert_awaited_once()
    def test_rate_limit(self):
        for _ in range(6):crm_api.rate_limit('test')
        with self.assertRaises(Exception) as cm:crm_api.rate_limit('test')
        self.assertEqual(cm.exception.status_code,429)

if __name__=='__main__':unittest.main()
