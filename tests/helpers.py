import httpx

from jobapp.http import Http


def mock_http(routes: dict, calls: list | None = None) -> Http:
    """routes: {substring: (status, body) | body | callable(request)->Response}. First match wins."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        for key, val in routes.items():
            if key in url:
                if callable(val):
                    return val(request)
                status, body = val if isinstance(val, tuple) else (200, val)
                return httpx.Response(status, text=body, headers={"content-type": "text/html"})
        return httpx.Response(404, text="")
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return Http(client=client, sleep=lambda s: None)
