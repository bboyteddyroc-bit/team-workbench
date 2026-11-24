"""LibTV 取回前必须先确认画布真有成片，否则会把“没生成出来”误报成“下载失败”。"""
import unittest
from unittest import mock

import libtv_gateway as gw


class OutputGateTest(unittest.TestCase):
    def collect(self):
        stages = []
        return stages, stages.append

    def test_finished_video_downloads_without_waiting(self):
        stages, announce = self.collect()
        with mock.patch.object(gw, 'node_output', return_value=(['https://x/a.mp4'], '', 2, True, True)), \
                mock.patch.object(gw, 'time') as fake:
            urls = gw.ensure_output('p', '.', announce)
            fake.sleep.assert_not_called()
        self.assertEqual(urls, ['https://x/a.mp4'])
        self.assertEqual(stages, [])

    def test_review_failure_reports_reason_not_download_error(self):
        stages, announce = self.collect()
        with mock.patch.object(gw, 'node_output',
                               return_value=([], '输入内容未通过安全审核，积分将会在2小时内返还', 3, True, True)):
            with self.assertRaises(RuntimeError) as ctx:
                gw.ensure_output('p', '.', announce)
        text = str(ctx.exception)
        self.assertIn('LibTV 生成未通过', text)
        self.assertIn('安全审核', text)
        self.assertIn('未自动重试', text)
        self.assertNotIn('下载', text)

    def test_canvas_without_any_task_fails_fast(self):
        stages, announce = self.collect()
        with mock.patch.object(gw, 'node_output', return_value=([], '', None, False, True)), \
                mock.patch.object(gw, 'time') as fake:
            with self.assertRaises(RuntimeError) as ctx:
                gw.ensure_output('p', '.', announce)
            fake.sleep.assert_not_called()
        text = str(ctx.exception)
        self.assertIn('画布上没有可下载成片', text)
        self.assertIn('不会重复扣费', text)

    def test_running_task_is_polled_until_video_appears(self):
        stages, announce = self.collect()
        results = [([], '', 1, True, True), ([], '', 1, True, True), (['https://x/b.mp4'], '', 2, True, True)]
        with mock.patch.object(gw, 'node_output', side_effect=results), \
                mock.patch.object(gw, 'time') as fake:
            fake.time.return_value = 0
            fake.sleep.return_value = None
            urls = gw.ensure_output('p', '.', announce, wait_seconds=240)
            self.assertEqual(fake.sleep.call_count, 2)
        self.assertEqual(urls, ['https://x/b.mp4'])
        self.assertTrue(all('等待 LibTV 出片' in s for s in stages))

    def test_polling_gives_up_with_clear_message(self):
        stages, announce = self.collect()
        with mock.patch.object(gw, 'node_output', return_value=([], '', 1, True, True)), \
                mock.patch.object(gw, 'time') as fake:
            fake.time.side_effect = [0, 0, 10, 20, 300]
            with self.assertRaises(gw.Transient) as ctx:
                gw.ensure_output('p', '.', announce, wait_seconds=240)
        # still queued/rendering after the wait window: not a failure, retrieved automatically later
        self.assertIn('仍在生成中', str(ctx.exception))
        self.assertIn('无需重新生成', str(ctx.exception))

    def test_download_error_text_is_mapped(self):
        text = gw.cli_failure(['download'], '该节点（及组内子节点）没有可下载的资源（图片/视频/音频/脚本/文本）', '')
        self.assertIn('没有可下载的成片', text)
        self.assertIn('不会重复扣费', text)

    def test_unavailable_probe_falls_back_to_download(self):
        stages, announce = self.collect()
        with mock.patch.object(gw, 'node_output', side_effect=RuntimeError('LibTV 返回格式无法识别')):
            self.assertIsNone(gw.ensure_output('p', '.', announce))
        self.assertEqual(stages, [])


if __name__ == '__main__':
    unittest.main()

