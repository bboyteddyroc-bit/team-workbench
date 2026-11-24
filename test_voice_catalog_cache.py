import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from voice_catalog import catalog_data

class CatalogCacheTests(unittest.TestCase):
    def setUp(self):
        self.voice=SimpleNamespace(_api_key=Mock(return_value='fake-one'))
        self.params={'page_number':1}

    def test_hit_refresh_key_isolation_and_copy(self):
        with patch('voice_catalog.read_model',return_value={'items':[{'title':'original'}]}) as read:
            first=catalog_data(self.voice,self.params);first['items'][0]['title']='mutated'
            self.assertEqual(catalog_data(self.voice,self.params)['items'][0]['title'],'original')
            self.assertEqual(read.call_count,1)
            catalog_data(self.voice,self.params,True);self.assertEqual(read.call_count,2)
            self.voice._api_key.return_value='fake-two'
            catalog_data(self.voice,self.params);self.assertEqual(read.call_count,3)
            catalog_data(SimpleNamespace(_api_key=lambda:'fake-two'),self.params)
            self.assertEqual(read.call_count,4)

    def test_expiry_filters_failure_and_bound(self):
        with patch('voice_catalog.read_model',return_value={'items':[]}) as read:
            with patch('voice_catalog.time.monotonic',return_value=10):catalog_data(self.voice,self.params)
            with patch('voice_catalog.time.monotonic',return_value=71):catalog_data(self.voice,self.params)
            self.assertEqual(read.call_count,2)
            for n in range(40):catalog_data(self.voice,{'page_number':n})
            self.assertLessEqual(len(self.voice._catalog_cache),32)
        with patch('voice_catalog.read_model',side_effect=ValueError('failure')) as read:
            for _ in range(2):
                with self.assertRaises(ValueError):catalog_data(self.voice,{'title':'new'})
            self.assertEqual(read.call_count,2)

if __name__=='__main__':unittest.main()
