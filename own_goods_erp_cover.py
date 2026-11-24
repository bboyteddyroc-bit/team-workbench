"""Read only the exact TikTok product-level image field from an authorized LingXing MCP.

No connection is inherited from the desktop assistant. The Hub needs its own
administrator-configured key. This module cannot call other business tools.
"""
import json
import re
import threading
import time
from concurrent.futures import Future, TimeoutError
from datetime import datetime, timedelta, timezone

import httpx

from safe_cover import image_url

URL = 'https://openmcp.lingxing.com/mcp-servers/lingxing-mcp'
TOOL = 'platform_tiktok_product_analysis_list'
MAX_RESPONSE = 2 * 1024 * 1024
MAX_SECONDS = 25
_slot = threading.BoundedSemaphore(1)


class SourceError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def exact_image(rows, market, pid):
    """Accept the top-level product result only; never match by SKU, title or a nearby market."""
    if not isinstance(rows, list) or len(rows) > 20:
        raise SourceError('erp_unavailable')
    matched = set()
    for row in rows:
        if not isinstance(row, dict) or row.get('site_code') != '10011-'+market:
            continue
        ident = row.get('platform_product_id')
        if type(ident) not in (str, int) or str(ident) != pid:
            continue
        try:
            matched.add(image_url(row.get('image_url'), product=True).geturl())
        except ValueError:
            continue
    if len(matched) != 1:
        raise SourceError('no_exact_image')
    return matched.pop()


def _matching(message, seq):
    return (isinstance(message, dict) and message.get('jsonrpc')=='2.0'
            and type(message.get('id')) is int and message['id']==seq)


def _reply(response, seq, deadline):
    ctype = response.headers.get('content-type','').split(';',1)[0].strip().lower()
    if ctype not in ('application/json','text/event-stream'):
        raise SourceError('erp_unavailable')
    received = 0
    if ctype=='text/event-stream':
        data, remaining = [], b''
        # Bound bytes before decoding, including an unfinished line or a heartbeat stream.
        for chunk in response.iter_bytes():
            received += len(chunk)
            if received>MAX_RESPONSE or time.monotonic()>=deadline:
                raise SourceError('erp_unavailable')
            *lines, remaining = (remaining+chunk).split(b'\n')
            for line in lines:
                line = line.removesuffix(b'\r')
                if not line:
                    if data:
                        msg=json.loads(b'\n'.join(data))
                        if _matching(msg,seq):
                            return msg
                        data.clear()
                elif line.startswith(b'data:'):
                    data.append(line[5:].removeprefix(b' '))
    else:
        raw = bytearray()
        for chunk in response.iter_bytes():
            received += len(chunk)
            if received>MAX_RESPONSE or time.monotonic()>=deadline:
                raise SourceError('erp_unavailable')
            raw.extend(chunk)
        msg = json.loads(raw)
        if _matching(msg,seq):
            return msg
    raise SourceError('erp_unavailable')


def _tool_data(result):
    if not isinstance(result, dict) or result.get('isError'):
        raise SourceError('erp_unavailable')
    if isinstance(result.get('structuredContent'), dict):
        return result['structuredContent']
    content = result.get('content')
    if not isinstance(content, list):
        return result
    values = [x.get('text') for x in content if isinstance(x, dict) and x.get('type') == 'text']
    if len(values) != 1 or not isinstance(values[0], str):
        raise SourceError('erp_unavailable')
    data = json.loads(values[0])
    if not isinstance(data,dict):
        raise SourceError('erp_unavailable')
    return data


def fetch_image(key, market, pid):
    if market != 'US' or not isinstance(pid,str) or not re.fullmatch('[0-9]{5,32}',pid):
        raise SourceError('no_exact_image')
    if not _slot.acquire(blocking=False):
        raise SourceError('erp_unavailable')
    # OS DNS can outlive HTTPX timeouts. Bound the queue's wait and keep at most
    # one detached call; the deadline prevents it from starting subsequent RPCs.
    result = Future()
    deadline = time.monotonic()+MAX_SECONDS

    def work():
        picture, error = '', None
        try:
            picture = _read_image(key,market,pid,deadline)
        except SourceError as exc:
            error = exc
        except Exception:
            error = SourceError('erp_unavailable')
        finally:
            _slot.release()
        if error:
            result.set_exception(error)
        else:
            result.set_result(picture)

    try:
        threading.Thread(target=work,name='own-cover-erp-read',daemon=True).start()
    except Exception:
        _slot.release()
        raise SourceError('erp_unavailable') from None
    try:
        return result.result(timeout=max(0,deadline-time.monotonic()))
    except TimeoutError:
        raise SourceError('erp_unavailable') from None


def _read_image(key, market, pid, deadline):
    day = datetime.now(timezone.utc).date()-timedelta(days=1)
    params = dict(dimension_type=2, start_date=(day-timedelta(days=29)).isoformat(), end_date=day.isoformat(),
                  search_field=1, search_value=[pid], site_codes=['10011-'+market], page_num=1, page_size=8)
    headers = {'X-Mcp-Key':key, 'Accept':'application/json, text/event-stream', 'Accept-Encoding':'identity'}
    sequence = 0
    try:
        with httpx.Client(trust_env=False, follow_redirects=False) as client:
            def rpc(method, payload, *, notify=False):
                nonlocal sequence
                sequence += 1
                message = dict(jsonrpc='2.0', method=method, params=payload)
                if not notify:
                    message['id'] = sequence
                seconds = deadline-time.monotonic()
                if seconds <= 0:
                    raise SourceError('erp_unavailable')
                with client.stream('POST', URL, headers=headers, json=message, timeout=min(7, seconds)) as response:
                    if response.status_code in (401,403):
                        raise SourceError('erp_forbidden')
                    if notify and response.status_code in (200,202,204):
                        return None
                    if response.status_code != 200:
                        raise SourceError('erp_unavailable')
                    if method == 'initialize' and (session := response.headers.get('Mcp-Session-Id')):
                        if not re.fullmatch(r'[!-~]{1,256}',session):
                            raise SourceError('erp_unavailable')
                        headers['Mcp-Session-Id'] = session
                    if response.headers.get('content-encoding','identity').lower()!='identity':
                        raise SourceError('erp_unavailable')
                    found = _reply(response,sequence,deadline)
                if 'error' in found or 'result' not in found:
                    raise SourceError('erp_unavailable')
                return found['result']

            hello = rpc('initialize', {'protocolVersion':'2025-03-26','capabilities':{},
                                      'clientInfo':{'name':'Seedance Hub listing covers','version':'1.0'}})
            version = hello.get('protocolVersion') if isinstance(hello,dict) else None
            if version not in ('2024-11-05','2025-03-26','2025-06-18','2025-11-25'):
                raise SourceError('erp_unavailable')
            headers['MCP-Protocol-Version']=version
            rpc('notifications/initialized', {}, notify=True)
            listing = rpc('tools/list', {})
            tools = {t['name'] for t in listing.get('tools',[]) if isinstance(t,dict)
                     and isinstance(t.get('name'),str)} if isinstance(listing,dict) else set()
            if TOOL in tools:
                name, arguments = TOOL, params
            elif {'search','action'} <= tools:
                schema = _tool_data(rpc('tools/call', {'name':'search','arguments':{'toolId':TOOL}}))
                info = schema.get('data',schema)
                if not isinstance(info,dict) or info.get('toolId') != TOOL or info.get('toolType') != 'read':
                    raise SourceError('erp_unavailable')
                name, arguments = 'action', {'toolId':TOOL,'params':params}
            else:
                raise SourceError('erp_unavailable')
            result = _tool_data(rpc('tools/call', {'name':name,'arguments':arguments}))
    except SourceError:
        raise
    except (httpx.HTTPError, OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise SourceError('erp_unavailable') from None

    # Observed envelopes: report rows, the business reply {code:1,data:report},
    # or the same business reply wrapped by the MCP action adapter.
    for _ in range(3):
        if (not isinstance(result,dict) or result.get('success') is False or
                ('code' in result and str(result['code'])!='1')):
            break
        rows = result.get('data')
        if isinstance(rows,list):
            if type(result.get('count')) is int and result['count']>len(rows):
                raise SourceError('no_exact_image')  # Don't guess across truncated/conflicting pages.
            return exact_image(rows,market,pid)
        result = rows
    raise SourceError('erp_unavailable')
