"""Real-CLI check: what the card will now say for the colleague's canvases."""
import libtv_gateway as gw

CANVASES = {
    '88e3': '88e3176c2cfd4117b1f3707f70958a19',
    '3ea8': '3ea85a83051c465cbbaf75b3bbf09312',
    '9bba': '9bba6499191a4f05935a21d27348c8a1',
}
CANVASES['3ea8'] = '3ea85a83051b465cbbaf75b3bbf09312'

for tag, project in CANVASES.items():
    try:
        out = gw.ensure_output(project, '.', lambda text: None, wait_seconds=0)
        print(tag, 'OK ->', out)
    except RuntimeError as error:
        print(tag, 'ERROR ->', error)
